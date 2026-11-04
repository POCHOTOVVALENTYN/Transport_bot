"""Wialon Remote API integration service for КП «Одесміськелектротранс».

Provides authenticated access to live unit positions, vehicle telemetry,
and zero-run / turnaround loop audit data using the RORO pattern.
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from config.settings import WIALON_HOST, WIALON_TOKEN, WIALON_TIMEOUT_SEC

logger = logging.getLogger(__name__)

# Anti-EW (РЕБ) and geographical boundary constants for Odesa
ODESA_LAT_MIN = 46.30
ODESA_LAT_MAX = 46.65
ODESA_LON_MIN = 30.60
ODESA_LON_MAX = 30.85
MAX_VALID_SPEED_KMH = 100.0

# Session cache
_cached_eid: Optional[str] = None
_session_lock = asyncio.Lock()


class WialonAuthRequest(BaseModel):
    token: str = Field(default_factory=lambda: WIALON_TOKEN)
    host: str = Field(default_factory=lambda: WIALON_HOST)


class WialonAuthResponse(BaseModel):
    is_success: bool
    eid: Optional[str] = None
    user_name: Optional[str] = None
    error_code: Optional[int] = None
    error_message: Optional[str] = None


class WialonVehiclePoint(BaseModel):
    unit_id: int
    name: str
    lat: float
    lon: float
    speed_kmh: float
    course: float
    timestamp: int
    satellites: int
    is_valid_coordinates: bool


class WialonTelemetryQuery(BaseModel):
    filter_odesa_only: bool = True
    filter_anti_ew: bool = True
    transport_kind: Optional[str] = None  # "tram", "trolleybus", or None for all


class WialonTelemetryResult(BaseModel):
    is_success: bool
    total_units: int
    active_in_odesa: int
    vehicles: List[WialonVehiclePoint]
    error_message: Optional[str] = None


def is_coordinate_in_odesa(lat: float, lon: float) -> bool:
    """Check whether coordinates fall inside Odesa bounding box."""
    if not (ODESA_LAT_MIN <= lat <= ODESA_LAT_MAX):
        return False
    if not (ODESA_LON_MIN <= lon <= ODESA_LON_MAX):
        return False
    return True


def has_valid_telemetry(lat: float, lon: float, speed_kmh: float) -> bool:
    """Validate point against GPS spoofing and physical speed limits."""
    if not is_coordinate_in_odesa(lat, lon):
        return False
    if speed_kmh < 0.0 or speed_kmh > MAX_VALID_SPEED_KMH:
        return False
    return True


def _execute_wialon_request_sync(host: str, svc: str, params: Dict[str, Any], sid: Optional[str] = None) -> Dict[str, Any]:
    """Execute synchronous POST request to Wialon Remote API."""
    data_dict = {
        "svc": svc,
        "params": json.dumps(params, ensure_ascii=False)
    }
    if sid:
        data_dict["sid"] = sid

    encoded_data = urllib.parse.urlencode(data_dict).encode("utf-8")
    req = urllib.request.Request(host, data=encoded_data, headers={"User-Agent": "TransportBot-Wialon/1.0"})

    with urllib.request.urlopen(req, timeout=WIALON_TIMEOUT_SEC) as response:
        raw_body = response.read().decode("utf-8")
        return json.loads(raw_body)


async def execute_wialon_request(svc: str, params: Dict[str, Any], sid: Optional[str] = None) -> Dict[str, Any]:
    """Non-blocking asynchronous wrapper for Wialon Remote API calls."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _execute_wialon_request_sync, WIALON_HOST, svc, params, sid)


async def authenticate_wialon(request: Optional[WialonAuthRequest] = None) -> WialonAuthResponse:
    """Authenticate with Wialon Remote API using API Access Token."""
    global _cached_eid
    auth_req = request or WialonAuthRequest()

    if not auth_req.token or len(auth_req.token) < 20:
        return WialonAuthResponse(
            is_success=False,
            error_message="WIALON_TOKEN is missing or too short"
        )

    async with _session_lock:
        try:
            res = await execute_wialon_request("token/login", {"token": auth_req.token})
            if "eid" in res:
                _cached_eid = res["eid"]
                user_nm = res.get("user", {}).get("nm", "")
                logger.info(f"Wialon authenticated as {user_nm} with eid: {_cached_eid[:8]}...")
                return WialonAuthResponse(
                    is_success=True,
                    eid=_cached_eid,
                    user_name=user_nm
                )

            err_code = res.get("error", -1)
            err_reason = res.get("reason", "Unknown authentication error")
            return WialonAuthResponse(
                is_success=False,
                error_code=err_code,
                error_message=f"Error {err_code}: {err_reason}"
            )
        except Exception as exc:
            logger.error(f"Wialon auth exception: {exc}")
            return WialonAuthResponse(
                is_success=False,
                error_message=str(exc)
            )


async def get_active_session_eid() -> Optional[str]:
    """Return valid cached session eid or perform fresh login."""
    global _cached_eid
    if _cached_eid:
        return _cached_eid

    auth_res = await authenticate_wialon()
    if not auth_res.is_success:
        return None

    return auth_res.eid


async def fetch_live_vehicles_telemetry(query: Optional[WialonTelemetryQuery] = None) -> WialonTelemetryResult:
    """Fetch current GPS telemetry of all transit vehicles from Wialon."""
    telemetry_query = query or WialonTelemetryQuery()
    sid = await get_active_session_eid()

    if not sid:
        return WialonTelemetryResult(
            is_success=False,
            total_units=0,
            active_in_odesa=0,
            vehicles=[],
            error_message="Could not obtain active Wialon session"
        )

    search_params = {
        "spec": {
            "itemsType": "avl_unit",
            "propName": "sys_name",
            "propValueMask": "*",
            "sortType": "sys_name"
        },
        "force": 1,
        "flags": 1025,  # Base properties + current GPS pos
        "from": 0,
        "to": 0
    }

    try:
        search_res = await execute_wialon_request("core/search_items", search_params, sid=sid)
        # Handle expired session error code 1 or 2
        if search_res.get("error") in (1, 2):
            global _cached_eid
            _cached_eid = None
            sid = await get_active_session_eid()
            if not sid:
                return WialonTelemetryResult(
                    is_success=False,
                    total_units=0,
                    active_in_odesa=0,
                    vehicles=[],
                    error_message="Re-authentication failed after session expiry"
                )
            search_res = await execute_wialon_request("core/search_items", search_params, sid=sid)

        raw_items = search_res.get("items", [])
    except Exception as exc:
        logger.error(f"Error fetching Wialon telemetry: {exc}")
        return WialonTelemetryResult(
            is_success=False,
            total_units=0,
            active_in_odesa=0,
            vehicles=[],
            error_message=str(exc)
        )

    parsed_vehicles: List[WialonVehiclePoint] = []
    active_in_odesa_count = 0

    for item in raw_items:
        unit_id = item.get("id", 0)
        unit_name = item.get("nm", "")
        pos = item.get("pos")

        if not pos:
            continue

        lat = float(pos.get("y", 0.0))
        lon = float(pos.get("x", 0.0))
        speed_kmh = float(pos.get("s", 0.0))
        course = float(pos.get("c", 0.0))
        timestamp = int(pos.get("t", 0))
        sats = int(pos.get("sc", 0))

        is_valid_point = has_valid_telemetry(lat, lon, speed_kmh)
        if is_valid_point:
            active_in_odesa_count += 1

        if telemetry_query.filter_anti_ew and not is_valid_point:
            continue

        if telemetry_query.transport_kind == "tram":
            name_lower = unit_name.lower()
            is_tram = "трам" in name_lower or "tram" in name_lower or (unit_name.isdigit() and int(unit_name) > 1000)
            if not is_tram:
                continue
        elif telemetry_query.transport_kind == "trolleybus":
            name_lower = unit_name.lower()
            is_trol = "трол" in name_lower or "trol" in name_lower or (unit_name.isdigit() and int(unit_name) < 1000)
            if not is_trol:
                continue

        parsed_vehicles.append(
            WialonVehiclePoint(
                unit_id=unit_id,
                name=unit_name,
                lat=lat,
                lon=lon,
                speed_kmh=speed_kmh,
                course=course,
                timestamp=timestamp,
                satellites=sats,
                is_valid_coordinates=is_valid_point
            )
        )

    return WialonTelemetryResult(
        is_success=True,
        total_units=len(raw_items),
        active_in_odesa=active_in_odesa_count,
        vehicles=parsed_vehicles
    )

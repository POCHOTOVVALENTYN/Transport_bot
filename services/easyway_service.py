# services/easyway_service.py
import aiohttp
import json
import time
import logging
import asyncio
from typing import List, Dict, Optional
from cachetools import TTLCache

from config.settings import (
    EASYWAY_API_URL, EASYWAY_LOGIN, EASYWAY_PASSWORD, EASYWAY_CITY,
    EASYWAY_STOP_INFO_VERSION, TIME_SOURCE_ICONS,
    EASYWAY_STOP_CACHE_TTL, EASYWAY_PLACES_CACHE_TTL,
    EASYWAY_ROUTES_CACHE_TTL, EASYWAY_ROUTE_GPS_CACHE_TTL
)
from config.accessible_vehicles import ACCESSIBLE_TRAMS, ACCESSIBLE_TROLS

from geopy.distance import geodesic

from config.vehicle_mapping import VEHICLE_ID_MAP

try:
    from config.easyway_config import EasyWayConfig
except ImportError:
    logging.warning("config/easyway_config.py не знайдено")


    class EasyWayConfig:
        BASE_URL = EASYWAY_API_URL
        LOGIN = EASYWAY_LOGIN
        PASSWORD = EASYWAY_PASSWORD
        STOP_INFO_VERSION = EASYWAY_STOP_INFO_VERSION
        DEFAULT_CITY = EASYWAY_CITY
        DEFAULT_FORMAT = "json"
        TIME_SOURCE_ICONS = TIME_SOURCE_ICONS

logger = logging.getLogger("transport_bot")

EASYWAY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7"
}


def safe_int(value: any, default: int = 0) -> int:
    """Безпечне приведення значення до цілого числа без падіння на None або ''."""
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def safe_float(value: any, default: float = 0.0) -> float:
    """Безпечне приведення значення до числа з плаваючою крапкою без падіння на None або ''."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


class EasyWayService:
    """Сервіс для роботи з API EasyWay v1.2"""

    def __init__(self):
        self.config = EasyWayConfig()
        self.base_url = EASYWAY_API_URL
        self.login = EASYWAY_LOGIN
        self.password = EASYWAY_PASSWORD
        self.city = EASYWAY_CITY

        self.transport_icons = {
            "bus": "🚌",
            "trol": "🚎",
            "tram": "🚋",
        }
        self.time_icons = TIME_SOURCE_ICONS
        self.stop_cache = TTLCache(maxsize=1000, ttl=EASYWAY_STOP_CACHE_TTL)
        self.places_cache = TTLCache(maxsize=2000, ttl=EASYWAY_PLACES_CACHE_TTL)
        self.routes_cache = TTLCache(maxsize=1, ttl=EASYWAY_ROUTES_CACHE_TTL)
        self.route_gps_cache = TTLCache(maxsize=2000, ttl=EASYWAY_ROUTE_GPS_CACHE_TTL)
        logger.info(
            "✅ EasyWay Cache initialized "
            f"(stop={EASYWAY_STOP_CACHE_TTL}s, places={EASYWAY_PLACES_CACHE_TTL}s, "
            f"routes={EASYWAY_ROUTES_CACHE_TTL}s, gps={EASYWAY_ROUTE_GPS_CACHE_TTL}s)"
        )

    def _log_api_duration(self, name: str, start_ts: float, extra: str = ""):
        duration = time.monotonic() - start_ts
        if duration >= 1.0:
            logger.info(f"⏱️ EasyWay {name} took {duration:.2f}s {extra}".strip())

    async def get_routes_list(self) -> dict:
        """Отримує список маршрутів"""
        cached = self.routes_cache.get("routes_list")
        if cached:
            return cached

        start_ts = time.monotonic()
        params = {
            "login": self.login,
            "password": self.password,
            "function": "cities.GetRoutesList",
            "city": self.city,
            "format": self.config.DEFAULT_FORMAT
        }
        url = self._build_url(params)
        timeout = aiohttp.ClientTimeout(total=20)

        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(ssl=False),
                    headers=EASYWAY_HEADERS
                ) as session:
                    async with session.get(url, timeout=timeout) as response:
                        if response.status == 200:
                            data = await response.json(content_type=None)
                            if isinstance(data, dict) and not data.get("error"):
                                self.routes_cache["routes_list"] = data
                            self._log_api_duration("GetRoutesList", start_ts)
                            return data
                        else:
                            logger.warning(f"GetRoutesList API returned status {response.status} on attempt {attempt + 1}")
                            if attempt < 2:
                                await asyncio.sleep(1.0 * (attempt + 1))
            except Exception as e:
                logger.warning(f"GetRoutesList error on attempt {attempt + 1}: {e}")
                if attempt < 2:
                    await asyncio.sleep(1.0 * (attempt + 1))
        return {"error": "Не вдалося завантажити список маршрутів."}

    async def get_places_by_name(self, search_term: str) -> dict:
        """Пошук зупинок за назвою"""
        cache_key = search_term.strip().lower()
        cached = self.places_cache.get(cache_key)
        if cached:
            return cached

        start_ts = time.monotonic()
        params = {
            "login": self.config.LOGIN,
            "password": self.config.PASSWORD,
            "function": "cities.GetPlacesByName",
            "city": self.config.DEFAULT_CITY,
            "term": search_term,
            "format": self.config.DEFAULT_FORMAT,
        }
        url = self._build_url(params)
        timeout = aiohttp.ClientTimeout(total=10)

        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(ssl=False),
                    headers=EASYWAY_HEADERS
                ) as session:
                    async with session.get(url, timeout=timeout) as response:
                        if response.status == 200:
                            parsed = self._parse_places_response(await response.json(content_type=None))
                            if not parsed.get("error"):
                                self.places_cache[cache_key] = parsed
                            self._log_api_duration("GetPlacesByName", start_ts, f"(term={cache_key})")
                            return parsed
                        else:
                            logger.warning(f"GetPlacesByName status {response.status} for term '{search_term}' on attempt {attempt + 1}")
                            if attempt < 2:
                                await asyncio.sleep(0.5 * (attempt + 1))
            except Exception as e:
                logger.warning(f"Search error on attempt {attempt + 1}: {e}")
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
        return {"error": "Сервер не відповів вчасно."}

    async def get_stop_info_v12(self, stop_id: int) -> dict:
        """Отримання інформації про зупинку"""
        if stop_id in self.stop_cache:
            return self.stop_cache[stop_id]

        start_ts = time.monotonic()
        params = {
            "login": self.config.LOGIN,
            "password": self.config.PASSWORD,
            "function": "stops.GetStopInfo",
            "city": self.config.DEFAULT_CITY,
            "id": stop_id,
            "v": self.config.STOP_INFO_VERSION,
            "format": self.config.DEFAULT_FORMAT,
        }
        url = self._build_url(params)
        timeout = aiohttp.ClientTimeout(total=8)

        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(ssl=False),
                    headers=EASYWAY_HEADERS
                ) as session:
                    logger.info(f"EasyWay API Call v1.2 (REAL REQUEST): {url} (attempt {attempt + 1})")
                    async with session.get(url, timeout=timeout) as response:
                        if response.status == 200:
                            parsed = self._parse_stop_info_v12(await response.json(content_type=None))
                            if not parsed.get("error"):
                                self.stop_cache[stop_id] = parsed
                            self._log_api_duration("GetStopInfo", start_ts, f"(stop_id={stop_id})")
                            return parsed
                        else:
                            logger.warning(f"EasyWay GetStopInfo status {response.status} for stop_id={stop_id} on attempt {attempt + 1}")
                            if attempt < 2:
                                await asyncio.sleep(0.5 * (attempt + 1))
            except Exception as e:
                logger.warning(f"StopInfo error on attempt {attempt + 1}: {e}")
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
        return {"error": "Сервер не відповів вчасно."}

    async def get_vehicles_on_route(self, route_id: int) -> List[dict]:
        """
        Отримує список ВСЬОГО транспорту на маршруті.
        Ми прибрали фільтрацію, щоб показувати реальну кількість машин.
        """
        cached = self.route_gps_cache.get(route_id)
        if cached is not None:
            return cached

        start_ts = time.monotonic()
        params = {
            "login": self.config.LOGIN,
            "password": self.config.PASSWORD,
            "function": "routes.GetRouteGPS",
            "city": self.config.DEFAULT_CITY,
            "id": route_id,
            "format": self.config.DEFAULT_FORMAT,
        }

        url = self._build_url(params)

        for attempt in range(2):
            try:
                async with aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(ssl=False),
                    headers=EASYWAY_HEADERS
                ) as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as response:
                        if response.status == 200:
                            data = await response.json(content_type=None)
                            parsed = self._parse_route_gps(data)
                            self.route_gps_cache[route_id] = parsed
                            self._log_api_duration("GetRouteGPS", start_ts, f"(route_id={route_id})")
                            return parsed
                        else:
                            logger.warning(f"API returned status {response.status} for GetRouteGPS (route_id={route_id})")
                            if attempt < 1:
                                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Error getting route GPS (route_id={route_id}): {e}")
                if attempt < 1:
                    await asyncio.sleep(0.5)

        return []

    def _parse_route_gps(self, data: dict) -> List[dict]:
        """Парсить відповідь routes.GetRouteGPS. Повертає ВСІ активні машини."""
        accessible_vehicles = []

        try:
            if not isinstance(data, dict):
                return []

            vehicles = data.get("vehicle", [])
            if isinstance(vehicles, dict):
                vehicles = [vehicles]
            elif not isinstance(vehicles, list):
                vehicles = []

            # Лог для відладки
            if vehicles:
                logger.info(f"🔍 RAW VEHICLE DATA (First item): {vehicles[0]}")

            all_ids = [str(v.get("id")) for v in vehicles if isinstance(v, dict)]
            logger.info(f"📋 Всі ID на маршруті: {all_ids}")

            for v in vehicles:
                if not isinstance(v, dict):
                    continue
                if v.get('data_relevance') == 0:
                    continue

                # 2. 🔥 ГОЛОВНЕ ВИПРАВЛЕННЯ: Фільтруємо за інклюзивністю 🔥
                # Підтримуємо і числове 1, і рядкове '1', і булеве True
                is_handicapped = str(v.get("handicapped", "0")).lower() in ["1", "true"]
                if not is_handicapped:
                    continue

                raw_id = str(v.get("id") or v.get("bortNumber") or "").strip()

                # Спробуємо знайти мапінг, але використовуємо raw_id як основний
                real_bort = VEHICLE_ID_MAP.get(raw_id)
                bort_number = real_bort if real_bort else raw_id

                lat = safe_float(v.get("lat"), 0.0)
                lng = safe_float(v.get("lng"), 0.0)
                direction = safe_int(v.get("direction"), 0)

                # Зберігаємо флаг handicapped про всяк випадок, але додаємо ВСІХ
                is_accessible_api = v.get("handicapped", False)

                # ВИПРАВЛЕННЯ: Додаємо в список ВСІ машини, щоб лічильник був правильний
                accessible_vehicles.append({
                    "bort": bort_number,
                    "raw_id": raw_id,
                    "lat": lat,
                    "lng": lng,
                    "direction": direction,
                    "is_accessible_api": is_accessible_api  # Може знадобитись в майбутньому
                })

        except Exception as e:
            logger.error(f"Error parsing route GPS: {e}")

        return accessible_vehicles

    def _build_url(self, params: Dict) -> str:
        base = self.base_url
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{base}/?{query_string}"

    def _parse_places_response(self, data: dict, root_key: str = "item") -> dict:
        try:
            if not isinstance(data, dict):
                return {"error": "Некоректний формат відповіді API"}
            if data.get("error"):
                return {"error": str(data.get("error"))}

            items = data.get(root_key, [])
            if not isinstance(items, list):
                items = [items]
            parsed_stops = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@attributes", {}).get("type") == "stop":
                    trams = []
                    trols = []
                    routes_data = item.get("routes", {}).get("route", [])
                    if not isinstance(routes_data, list):
                        routes_data = [routes_data]
                    for route in routes_data:
                        if not isinstance(route, dict):
                            continue
                        title = route.get("title")
                        rtype = route.get("@attributes", {}).get("type") or route.get("type")
                        if rtype == "tram":
                            trams.append(title)
                        elif rtype == "trol":
                            trols.append(title)
                    summary_parts = []
                    if trams:
                        summary_parts.append(f"🚋 {', '.join(trams)}")
                    if trols:
                        summary_parts.append(f"🚎 {', '.join(trols)}")
                    routes_summary = " | ".join(summary_parts)
                    if routes_summary:
                        parsed_stops.append({
                            "id": safe_int(item.get("id")),
                            "title": item.get("title", ""),
                            "routes_summary": routes_summary
                        })
            return {"stops": parsed_stops}
        except Exception as e:
            return {"error": str(e)}

    def _parse_stop_info_v12(self, data: Dict) -> Dict:
        try:
            if not isinstance(data, dict):
                return {"error": "Некоректний формат відповіді API"}
            if data.get("error"):
                return {"error": str(data.get("error"))}

            stop = data
            parsed = {
                "id": safe_int(stop.get("id")),
                "title": str(stop.get("title") or ""),
                "lat": safe_float(stop.get("lat"), 0.0),
                "lng": safe_float(stop.get("lng"), 0.0),
                "routes": [],
            }

            raw_routes = stop.get("routes")
            if isinstance(raw_routes, dict) and "route" in raw_routes:
                raw_routes = raw_routes["route"]

            if not raw_routes:
                transports = stop.get("transports", [])
                if isinstance(transports, list):
                    raw_routes = []
                    for t in transports:
                        if not isinstance(t, dict):
                            continue
                        t_routes = t.get("routes", [])
                        if isinstance(t_routes, list):
                            raw_routes.extend(t_routes)
                        elif isinstance(t_routes, dict):
                            if "route" in t_routes:
                                r_inner = t_routes["route"]
                                if isinstance(r_inner, list):
                                    raw_routes.extend(r_inner)
                                else:
                                    raw_routes.append(r_inner)
                            else:
                                raw_routes.append(t_routes)

            if not isinstance(raw_routes, list):
                raw_routes = [raw_routes] if raw_routes else []

            for route in raw_routes:
                if not isinstance(route, dict):
                    continue

                bort_number = str(route.get("bortNumber") or "").strip()
                transport_key = route.get("transportKey")

                is_api_handicapped = bool(route.get("handicapped", False))
                is_local_handicapped = False
                if transport_key == 'tram' and bort_number in ACCESSIBLE_TRAMS:
                    is_local_handicapped = True
                elif transport_key == 'trol' and bort_number in ACCESSIBLE_TROLS:
                    is_local_handicapped = True

                parsed_route = {
                    "id": safe_int(route.get("id")),
                    "title": str(route.get("title") or "").strip(),
                    "direction": safe_int(route.get("direction"), 0),
                    "direction_title": route.get("directionTitle"),
                    "transport_name": route.get("transportName"),
                    "transport_key": transport_key,
                    "handicapped": is_api_handicapped or is_local_handicapped,
                    "bort_number": bort_number,
                    "time_left": safe_float(route.get("timeLeft"), default=9999.0),
                    "time_left_formatted": str(route.get("timeLeftFormatted") or ""),
                    "time_source": str(route.get("timeSource") or "unknown"),
                    "wifi": bool(route.get("wifi", False)),
                    "aircond": bool(route.get("aircond", False)),
                }
                parsed["routes"].append(parsed_route)
            return parsed
        except Exception as e:
            logger.error(f"Error parsing stop info: {e}", exc_info=True)
            return {"error": str(e)}

    def filter_handicapped_routes(self, stop_info: dict) -> List[dict]:
        return [r for r in stop_info.get("routes", []) if
                r.get("handicapped") and r.get("transport_key") != "marshrutka"]

    def get_transport_icon(self, key: str) -> str:
        return self.transport_icons.get(key, "❓")

    def get_time_source_icon(self, key: str) -> str:
        return self.time_icons.get(key, "❓")

    async def check_vehicle_status_relative_to_stop(self, route_id: int, user_stop_id: int, direction: int) -> dict:
        return {"status": "unknown"}


easyway_service = EasyWayService()
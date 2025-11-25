# services/easyway_service.py
import aiohttp
import json
import logging
import asyncio
from typing import List, Dict, Optional
from cachetools import TTLCache

from config.settings import (
    EASYWAY_API_URL, EASYWAY_LOGIN, EASYWAY_PASSWORD, EASYWAY_CITY,
    EASYWAY_STOP_INFO_VERSION, TIME_SOURCE_ICONS
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
        self.stop_cache = TTLCache(maxsize=1000, ttl=30)
        logger.info("✅ EasyWay Stop Cache initialized (TTL=30s)")

    async def get_routes_list(self) -> dict:
        """Отримує список маршрутів"""
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
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                    async with session.get(url, timeout=timeout) as response:
                        if response.status == 200:
                            return await response.json(content_type=None)
            except Exception as e:
                logger.warning(f"GetRoutesList error: {e}")
                if attempt < 2: await asyncio.sleep(2)
        return {"error": "Не вдалося завантажити список маршрутів."}

    async def get_places_by_name(self, search_term: str) -> dict:
        """Пошук зупинок за назвою"""
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
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                    async with session.get(url, timeout=timeout) as response:
                        if response.status == 200:
                            return self._parse_places_response(await response.json(content_type=None))
            except Exception as e:
                logger.warning(f"Search error: {e}")
                if attempt < 2: await asyncio.sleep(1)
        return {"error": "Сервер не відповів."}

    async def get_stop_info_v12(self, stop_id: int) -> dict:
        """Отримання інформації про зупинку"""
        if stop_id in self.stop_cache:
            return self.stop_cache[stop_id]

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
        timeout = aiohttp.ClientTimeout(total=10)

        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                    logger.info(f"EasyWay API Call v1.2 (REAL REQUEST): {url}")
                    async with session.get(url, timeout=timeout) as response:
                        if response.status == 200:
                            parsed = self._parse_stop_info_v12(await response.json(content_type=None))
                            if not parsed.get("error"):
                                self.stop_cache[stop_id] = parsed
                            return parsed
            except Exception as e:
                logger.warning(f"StopInfo error: {e}")
                if attempt < 2: await asyncio.sleep(0.5)
        return {"error": "Сервер не відповів."}

    async def get_vehicles_on_route(self, route_id: int) -> List[dict]:
        """
        Отримує список ВСЬОГО транспорту на маршруті.
        Ми прибрали фільтрацію, щоб показувати реальну кількість машин.
        """
        params = {
            "login": self.config.LOGIN,
            "password": self.config.PASSWORD,
            "function": "routes.GetRouteGPS",
            "city": self.config.DEFAULT_CITY,
            "id": route_id,
            "format": self.config.DEFAULT_FORMAT,
        }

        url = self._build_url(params)

        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                async with session.get(url, timeout=8) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        return self._parse_route_gps(data)
                    else:
                        logger.warning(f"API returned status {response.status} for GetRouteGPS")
        except Exception as e:
            logger.error(f"Error getting route GPS: {e}")

        return []

    def _parse_route_gps(self, data: dict) -> List[dict]:
        """Парсить відповідь routes.GetRouteGPS. Повертає ВСІ активні машини."""
        accessible_vehicles = []

        try:
            vehicles = data.get("vehicle", [])
            if isinstance(vehicles, dict):
                vehicles = [vehicles]
            elif not isinstance(vehicles, list):
                vehicles = []

            # Лог для відладки
            if vehicles:
                logger.info(f"🔍 RAW VEHICLE DATA (First item): {vehicles[0]}")

            all_ids = [str(v.get("id")) for v in vehicles]
            logger.info(f"📋 Всі ID на маршруті: {all_ids}")

            for v in vehicles:
                if v.get('data_relevance') == 0: continue

                raw_id = str(v.get("id") or v.get("bortNumber") or "").strip()

                # Спробуємо знайти мапінг, але використовуємо raw_id як основний
                real_bort = VEHICLE_ID_MAP.get(raw_id)
                bort_number = real_bort if real_bort else raw_id

                lat = float(v.get("lat", 0))
                lng = float(v.get("lng", 0))
                direction = int(v.get("direction", 0))

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
            items = data.get(root_key, [])
            if not isinstance(items, list): items = [items]
            parsed_stops = []
            for item in items:
                if item.get("@attributes", {}).get("type") == "stop":
                    trams = []
                    trols = []
                    routes_data = item.get("routes", {}).get("route", [])
                    if not isinstance(routes_data, list): routes_data = [routes_data]
                    for route in routes_data:
                        title = route.get("title")
                        rtype = route.get("@attributes", {}).get("type") or route.get("type")
                        if rtype == "tram":
                            trams.append(title)
                        elif rtype == "trol":
                            trols.append(title)
                    summary_parts = []
                    if trams: summary_parts.append(f"🚋 {', '.join(trams)}")
                    if trols: summary_parts.append(f"🚎 {', '.join(trols)}")
                    routes_summary = " | ".join(summary_parts)
                    if routes_summary:
                        parsed_stops.append({
                            "id": int(item.get("id", 0)),
                            "title": item.get("title", ""),
                            "routes_summary": routes_summary
                        })
            return {"stops": parsed_stops}
        except Exception as e:
            return {"error": str(e)}

    def _parse_stop_info_v12(self, data: Dict) -> Dict:
        try:
            stop = data
            parsed = {
                "id": stop.get("id"),
                "title": stop.get("title"),
                "lat": float(stop.get("lat", 0)),
                "lng": float(stop.get("lng", 0)),
                "routes": [],
            }

            raw_routes = stop.get("routes", [])
            if not raw_routes:
                transports = stop.get("transports", [])
                if isinstance(transports, list):
                    for t in transports:
                        t_routes = t.get("routes", [])
                        if isinstance(t_routes, list):
                            raw_routes.extend(t_routes)
                        elif isinstance(t_routes, dict):
                            raw_routes.append(t_routes)

            if not isinstance(raw_routes, list):
                raw_routes = [raw_routes]

            for route in raw_routes:
                bort_number = str(route.get("bortNumber", "")).strip()
                transport_key = route.get("transportKey")

                is_api_handicapped = route.get("handicapped", False)
                is_local_handicapped = False
                if transport_key == 'tram' and bort_number in ACCESSIBLE_TRAMS:
                    is_local_handicapped = True
                elif transport_key == 'trol' and bort_number in ACCESSIBLE_TROLS:
                    is_local_handicapped = True

                parsed_route = {
                    "id": route.get("id"),
                    "title": route.get("title"),
                    "direction": int(route.get("direction", 0)),
                    "direction_title": route.get("directionTitle"),
                    "transport_name": route.get("transportName"),
                    "transport_key": transport_key,
                    "handicapped": is_api_handicapped or is_local_handicapped,
                    "bort_number": bort_number,
                    "time_left": float(route.get("timeLeft", 9999)),
                    "time_left_formatted": route.get("timeLeftFormatted", ""),
                    "time_source": route.get("timeSource", "unknown"),
                    "wifi": route.get("wifi", False),
                    "aircond": route.get("aircond", False),
                }
                parsed["routes"].append(parsed_route)
            return parsed
        except Exception as e:
            logger.error(f"Error parsing stop info: {e}")
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
# services/easyway_service.py
import aiohttp
import json
import logging
import asyncio
from typing import List, Dict, Optional

from config.settings import (
    EASYWAY_API_URL, EASYWAY_LOGIN, EASYWAY_PASSWORD, EASYWAY_CITY,
    EASYWAY_STOP_INFO_VERSION, TIME_SOURCE_ICONS
)

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
            "tram": "🚊",
        }
        self.time_icons = TIME_SOURCE_ICONS

    async def get_routes_list(self) -> dict:
        """Отримує список маршрутів"""
        params = {
            "login": self.login,
            "password": self.password,
            "function": "cities.GetRoutesList",
            "city": self.city,
            "format": self.config.DEFAULT_FORMAT
        }

        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                url = self._build_url(params)
                logger.info(f"EasyWay API Call: {url}")

                timeout = aiohttp.ClientTimeout(total=15)
                async with session.get(url, timeout=timeout) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        return data
                    else:
                        raise Exception(f"API returned {response.status}")

        except asyncio.TimeoutError:
            logger.error("GetRoutesList error: Request timed out")
            return {"error": "Сервер EasyWay не відповів вчасно (10 сек)."}
        except Exception as e:
            logger.error(f"GetRoutesList error: {e}")
            return {"error": str(e)}

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
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                url = self._build_url(params)
                logger.info(f"EasyWay API Call: {url}")

                timeout = aiohttp.ClientTimeout(total=15)
                async with session.get(url, timeout=timeout) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        # --- ПОЧАТОК ДІАГНОСТИЧНОГО ЛОГУ ---
                        try:
                            import json
                            # Використовуємо json.dumps для гарного форматування
                            raw_json_data = json.dumps(data, indent=2, ensure_ascii=False)

                            logger.info(f"===== RAW API RESPONSE for term '{search_term}' =====")
                            logger.info(raw_json_data)
                            logger.info(f"=====================================================")
                        except Exception as log_e:
                            logger.error(f"Error during diagnostic logging: {log_e}")
                        # --- КІНЕЦЬ ДІАГНОСТИЧНОГО ЛОГУ ---
                        return self._parse_places_response(data, root_key="item")
                    else:
                        raise Exception(f"API returned {response.status}")
        except asyncio.TimeoutError:
            logger.error("GetPlacesByName error: Request timed out")
            return {"error": "Сервер EasyWay не відповів вчасно (10 сек)."}
        except Exception as e:
            logger.error(f"GetPlacesByName error: {e}")
            return {"error": str(e)}

    async def get_stop_info_v12(self, stop_id: int) -> dict:
        """Отримання інформації v1.2 про зупинку (з GPS)"""
        params = {
            "login": self.config.LOGIN,
            "password": self.config.PASSWORD,
            "function": "stops.GetStopInfo",
            "city": self.config.DEFAULT_CITY,
            "id": stop_id,
            "v": self.config.STOP_INFO_VERSION,  # v1.2!
            "format": self.config.DEFAULT_FORMAT,
        }
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                url = self._build_url(params)
                logger.info(f"EasyWay API Call (v1.2): {url}")

                timeout = aiohttp.ClientTimeout(total=15)
                async with session.get(url, timeout=timeout) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        logger.info(f"EasyWay API Response v1.2: {str(data)[:200]}")
                        return self._parse_stop_info_v12(data)
                    else:
                        raise Exception(f"API returned {response.status}")
        except asyncio.TimeoutError:
            logger.error("GetStopInfo v1.2 error: Request timed out")
            return {"error": "Сервер EasyWay не відповів вчасно (10 сек)."}
        except Exception as e:
            logger.error(f"GetStopInfo v1.2 error: {e}")
            return {"error": str(e)}

    def _build_url(self, params: Dict) -> str:
        """Будує URL для API запиту"""
        base = self.base_url
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{base}/?{query_string}"

    def _parse_places_response(self, data: dict, root_key: str = "item") -> dict:
        """Парсить відповідь cities.GetPlacesByName"""
        try:
            items = data.get(root_key, [])
            if not isinstance(items, list):
                items = [items]

            parsed_stops = []
            for item in items:
                # Отримуємо вкладений словник "@attributes"
                attributes = item.get("@attributes", {})
                # Шукаємо "type" вже всередині нього
                item_type = attributes.get("type")

                if item_type == "stop":
                    parsed_stops.append({
                        "id": int(item.get("id", 0)),
                        "title": item.get("title", ""),
                        "lat": float(item.get("lat", 0)),
                        "lng": float(item.get("lng", 0)),
                    })
            logger.info(f"Parsed {len(parsed_stops)} stops")
            return {"stops": parsed_stops}
        except Exception as e:
            logger.error(f"Error parsing places response: {e}")
            return {"error": f"Error parsing places response: {e}"}

    def _parse_stop_info_v12(self, data: Dict) -> Dict:
        """Парсить відповідь stops.GetStopInfo v1.2"""
        try:
            stop = data
            parsed = {
                "id": stop.get("id"),
                "title": stop.get("title"),
                "lat": float(stop.get("lat", 0)),
                "lng": float(stop.get("lng", 0)),
                "routes": [],
            }

            transports = stop.get("routes", [])
            if not isinstance(transports, list):
                transports = [transports]

            for route in transports:
                parsed_route = {
                    "id": route.get("id"),
                    "title": route.get("title"),
                    "direction": route.get("directionTitle"),
                    "transport_name": route.get("transportName"),
                    "transport_key": route.get("transportKey"),
                    "handicapped": route.get("handicapped", False),
                    "bort_number": route.get("bortNumber"),
                    "time_left": int(route.get("timeLeft", 9999)),
                    "time_left_formatted": route.get("timeLeftFormatted", ""),
                    "time_source": route.get("timeSource", "unknown"),
                    "wifi": route.get("wifi", False),
                    "aircond": route.get("aircond", False),
                }
                parsed["routes"].append(parsed_route)

            logger.info(f"Parsed {len(parsed['routes'])} routes")
            return parsed
        except Exception as e:
            logger.error(f"Error parsing stop info v1.2: {e}")
            return {"error": f"Error parsing stop info v1.2: {e}"}

    def filter_handicapped_routes(self, stop_info: dict) -> List[dict]:
        """Фільтрує тільки низькопідлоговий транспорт"""
        handicapped_routes = []
        for route in stop_info.get("routes", []):
            if route.get("handicapped"):
                if route.get("transport_key") != "marshrutka":
                    handicapped_routes.append(route)

        handicapped_routes.sort(key=lambda r: r["time_left"])
        return handicapped_routes

    def get_transport_icon(self, transport_key: str) -> str:
        """Отримує іконку для типу транспорту"""
        return self.transport_icons.get(transport_key, "❓")

    def get_time_source_icon(self, time_source: str) -> str:
        """Отримує іконку для джерела часу"""
        return self.time_icons.get(time_source, "❓")


# Глобальний екземпляр сервісу
easyway_service = EasyWayService()
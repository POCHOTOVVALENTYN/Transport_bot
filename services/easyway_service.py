# services/easyway_service.py
from utils.logger import logger
import aiohttp
import json
import logging
from config.settings import (
    EASYWAY_API_URL, EASYWAY_LOGIN, EASYWAY_PASSWORD, EASYWAY_CITY,
    EASYWAY_STOP_INFO_VERSION, TIME_SOURCE_ICONS  # <-- Нові імпорти
)
from typing import List, Dict, Optional  # <-- Додано для типізації

# Використовуємо logger з utils
logger = logging.getLogger("transport_bot")


class EasyWayService:
    def __init__(self):
        self.base_url = EASYWAY_API_URL
        self.base_params = {
            "login": EASYWAY_LOGIN,
            "password": EASYWAY_PASSWORD,
            "format": "json"  # Встановимо JSON як стандарт [cite: 1084]
        }
        # Іконки для UI [cite: 1321-1326]
        self.transport_icons = {
            "bus": "🚌",
            "trol": "🚎",
            "tram": "🚊",
            # "marshrutka" видалено згідно вашого запиту
        }
        self.time_icons = TIME_SOURCE_ICONS

    async def _get(self, params: dict) -> dict:
        full_params = self.base_params.copy()
        full_params.update(params)

        # (Залишаємо 'ssl=False')
        connector = aiohttp.TCPConnector(ssl=False)

        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                # Будуємо URL для логування [cite: 1211-1215]
                query_string = "&".join(f"{k}={v}" for k, v in full_params.items())
                full_url = f"{self.base_url}/?{query_string}"
                logger.info(f"EasyWay API Call: {self.base_url}/?{full_params.get('function')}...")

                async with session.get(self.base_url, params=full_params) as response:
                    if response.status == 200:
                        raw_text = await response.text()
                        if not raw_text:
                            return {"error": "Empty response from API"}

                        logger.info(f"EasyWay API Raw Response (first 100 chars): {raw_text[:100]}")

                        # Обробка JSONP (якщо є)
                        json_part = raw_text
                        if "(" in raw_text and raw_text.endswith(")"):
                            start_brace = raw_text.find("(")
                            if start_brace != -1:
                                json_part = raw_text[start_brace + 1: -1]

                        try:
                            data = json.loads(json_part)
                        except json.JSONDecodeError as e:
                            return {"error": f"JSON Decode Error: {e}"}

                        if data.get("error"):
                            error_details = data['error']
                            error_message = "Unknown API error"
                            if isinstance(error_details, dict):
                                error_message = error_details.get("message", "Unknown API error")
                            elif isinstance(error_details, str):
                                error_message = error_details
                            logger.error(f"EasyWay API Error: {error_details}")
                            return {"error": error_message}

                        return data
                    else:
                        return {"error": f"HTTP Error: {response.status}"}
            except Exception as e:
                logger.error(f"EasyWay aiohttp Error: {e}", exc_info=True)
                return {"error": f"Connection error: {e}"}

    # === ФУНКЦІЇ, ЩО ЗАЛИШАЮТЬСЯ (для інших модулів) ===

    async def get_routes_list(self) -> dict:
        """ (ЗАЛИШЕНО) Використовується 'load_easyway_route_ids' при старті. """
        params = {
            "function": "cities.GetRoutesList",
            "city": EASYWAY_CITY
        }
        return await self._get(params)

    async def get_route_info(self, route_id: str) -> dict:
        """ (ЗАЛИШЕНО) Може знадобитись для інших модулів. """
        params = {
            "function": "routes.GetRouteInfo",
            "city": EASYWAY_CITY,
            "id": route_id
        }
        return await self._get(params)

    # === ФУНКЦІЇ, ЩО ВИДАЛЯЮТЬСЯ (згідно плану v1.2) ===
    # ❌ def get_route_to_display(...) - ВИДАЛЕНО [cite: 1831]
    # ❌ def get_route_gps(...) - ВИДАЛЕНО [cite: 1833]

    # === НОВІ ФУНКЦІЇ (з плану v1.2) ===

    async def get_places_by_name(self, search_term: str) -> dict:
        """
        Крок 1: Пошук зупинок за назвою. [cite: 1116-1120]
        """
        params = {
            "function": "cities.GetPlacesByName",
            "city": EASYWAY_CITY,
            "term": search_term,
        }
        data = await self._get(params)
        if data.get("error"):
            return data
        return self._parse_places_response(data)

    async def get_stop_info_v12(self, stop_id: int) -> dict:
        """
        Крок 2: Отримання інформації v1.2 про зупинку. [cite: 1150-1154]
        """
        params = {
            "function": "stops.GetStopInfo",
            "city": EASYWAY_CITY,
            "id": stop_id,
            "v": EASYWAY_STOP_INFO_VERSION  # <-- ВКАЗУЄМО ВЕРСІЮ 1.2 [cite: 1194]
        }
        data = await self._get(params)
        if data.get("error"):
            return data
        return self._parse_stop_info_v12(data)

    # === НОВІ ПРИВАТНІ МЕТОДИ (ПАРСЕРИ з плану v1.2) ===

    def _parse_places_response(self, data: dict) -> dict:
        """ Парсить відповідь cities.GetPlacesByName [cite: 1216-1217] """
        try:
            items = data.get("response", [])
            parsed_stops = []
            for item in items:
                # Беремо тільки зупинки, ігноруємо 'place'
                if item.get("type") == "stop":
                    parsed_stops.append({
                        "id": int(item.get("id", 0)),
                        "title": item.get("title", ""),
                        "lat": float(item.get("lat", 0)),
                        "lng": float(item.get("lng", 0)),
                    })
            logger.info(f"Parsed {len(parsed_stops)} stops from GetPlacesByName")
            return {"stops": parsed_stops}
        except Exception as e:
            logger.error(f"Error parsing places response: {e}")
            return {"error": f"Error parsing places response: {e}"}

    def _parse_stop_info_v12(self, data: dict) -> dict:
        """ Парсить відповідь stops.GetStopInfo v1.2 [cite: 1247-1248] """
        try:
            stop = data.get("stop", {})
            parsed = {
                "id": stop.get("id"),
                "title": stop.get("title"),
                "lat": float(stop.get("lat", 0)),
                "lng": float(stop.get("lng", 0)),
                "routes": [],
            }

            transports = stop.get("transports", [])
            if not isinstance(transports, list):
                transports = [transports]  # Виправлення для 1 маршруту

            for route in transports:
                parsed_route = {
                    "id": route.get("id"),
                    "title": route.get("title"),
                    "direction": route.get("directionTitle"),
                    "transport_name": route.get("transportName"),
                    "transport_key": route.get("transportKey"),
                    "handicapped": route.get("handicapped", False),  # [cite: 1292]
                    "bort_number": route.get("bortNumber"),  # [cite: 1293]
                    "time_left": int(route.get("timeLeft", 9999)),  # [cite: 1294]
                    "time_left_formatted": route.get("timeLeftFormatted", ""),  # [cite: 1295]
                    "time_source": route.get("timeSource", "unknown"),  # [cite: 1296]
                    "wifi": route.get("wifi", False),
                    "aircond": route.get("aircond", False),
                }
                parsed["routes"].append(parsed_route)

            logger.info(f"Parsed {len(parsed['routes'])} routes from GetStopInfo v1.2")
            return parsed
        except Exception as e:
            logger.error(f"Error parsing stop info v1.2: {e}")
            return {"error": f"Error parsing stop info v1.2: {e}"}

    # === НОВА БІЗНЕС-ЛОГІКА (з плану v1.2) ===

    def filter_handicapped_routes(self, stop_info: dict) -> List[dict]:
        """
        Фільтрує тільки низькопідлоговий транспорт.
        Сортує за часом прибуття. [cite: 1306-1308]
        """
        handicapped_routes = []
        for route in stop_info.get("routes", []):
            # Фільтр по "handicapped" [cite: 1311]
            if route.get("handicapped"):
                # Ігноруємо "marshrutka" згідно вашого запиту
                if route.get("transport_key") != "marshrutka":
                    handicapped_routes.append(route)

        # Сортуємо за часом прибуття (спочатку найближчі) [cite: 1317]
        handicapped_routes.sort(key=lambda r: r["time_left"])
        return handicapped_routes

    def get_transport_icon(self, transport_key: str) -> str:
        """ Отримує іконку для типу транспорту [cite: 1319-1320] """
        return self.transport_icons.get(transport_key, "❓")

    def get_time_source_icon(self, time_source: str) -> str:
        """ Отримує іконку для джерела часу [cite: 1327-1328] """
        return self.time_icons.get(time_source, "❓")


easyway_service = EasyWayService()
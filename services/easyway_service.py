# services/easyway_service.py
import aiohttp
import json
import logging
import asyncio  # <-- Важливий імпорт для обробки тайм-аутів
from typing import List, Dict, Optional

from config.settings import (
    EASYWAY_API_URL, EASYWAY_LOGIN, EASYWAY_PASSWORD, EASYWAY_CITY,
    EASYWAY_STOP_INFO_VERSION, TIME_SOURCE_ICONS
)

# Ми імпортуємо конфігурацію, як це робить PDF-план
# (Припускаємо, що у вас є цей файл, як у PDF)
try:
    from config.easyway_config import EasyWayConfig
except ImportError:
    # Запасний варіант, якщо easyway_config.py не створено
    logging.Logger.warning("config/easyway_config.py не знайдено, використовуються налаштування з settings.py")


    class EasyWayConfig:
        BASE_URL = EASYWAY_API_URL
        LOGIN = EASYWAY_LOGIN
        PASSWORD = EASYWAY_PASSWORD
        STOP_INFO_VERSION = EASYWAY_STOP_INFO_VERSION
        DEFAULT_CITY = EASYWAY_CITY
        DEFAULT_FORMAT = "json"
        TIME_SOURCE_ICONS = TIME_SOURCE_ICONS

# Використовуємо logger з utils
logger = logging.getLogger("transport_bot")


class EasyWayService:
    """
    Сервіс для роботи з API Easy Way (ПОВНА ВЕРСІЯ v1.2)
    Включає нові методи v1.2 та оновлені старі методи для сумісності.
    """

    def __init__(self):
        self.config = EasyWayConfig()
        # Старі налаштування (для сумісності)
        self.base_url = EASYWAY_API_URL
        self.login = EASYWAY_LOGIN
        self.password = EASYWAY_PASSWORD
        self.city = EASYWAY_CITY

        # [cite_start]Іконки для UI [cite: 1321-1326]
        self.transport_icons = {
            "bus": "🚌",
            "trol": "🚎",
            "tram": "🚊",
        }
        self.time_icons = TIME_SOURCE_ICONS

    # === МЕТОДИ, ЩО ЗАЛИШИЛИСЯ ДЛЯ СУМІСНОСТІ (ПЕРЕПИСАНІ) ===

    async def get_routes_list(self) -> dict:
        """
        (ОНОВЛЕНО З ВИПРАВЛЕННЯМ ТАЙМ-АУТУ)
        Використовується 'load_easyway_route_ids' при старті.
        """
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
                logger.info(f"EasyWay API Call (legacy): {url}")

                timeout = aiohttp.ClientTimeout(total=15) # Збільшено до 15 секунд
                async with session.get(url, timeout=timeout) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)  # Додано content_type=None
                        return data
                    else:
                        raise Exception(f"API returned {response.status}")

        # === ПОТРІБНИЙ БЛОК ОБРОБКИ ТАЙМ-АУТУ ===
        except asyncio.TimeoutError:
            logger.error("GetRoutesList (legacy) error: Request timed out after 10 seconds")
            return {"error": "Сервер EasyWay не відповів вчасно (10 сек)."}
        # ========================================
        except Exception as e:
            logger.error(f"GetRoutesList (legacy) error: {e}")
            return {"error": str(e)}

    async def get_route_info(self, route_id: str) -> dict:
        """
        (ОНОВЛЕНО З ВИПРАВЛЕННЯМ ТАЙМ-АУТУ)
        Може знадобитись для інших модулів.
        """
        params = {
            "login": self.login,
            "password": self.password,
            "function": "routes.GetRouteInfo",
            "city": self.city,
            "id": route_id,
            "format": self.config.DEFAULT_FORMAT
        }

        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                url = self._build_url(params)
                logger.info(f"EasyWay API Call (legacy): {url}")

                timeout = aiohttp.ClientTimeout(total=15) # Збільшено до 15 секунд
                async with session.get(url, timeout=timeout) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)  # Додано content_type=None
                        return data
                    else:
                        raise Exception(f"API returned {response.status}")

        # === ПОТРІБНИЙ БЛОК ОБРОБКИ ТАЙМ-АУТУ ===
        except asyncio.TimeoutError:
            logger.error("GetRouteInfo (legacy) error: Request timed out after 10 seconds")
            return {"error": "Сервер EasyWay не відповів вчасно (10 сек)."}
        # ========================================
        except Exception as e:
            logger.error(f"GetRouteInfo (legacy) error: {e}")
            return {"error": str(e)}

    # === НОВІ ФУНКЦІЇ (з плану v1.2) ===

    async def get_places_by_name(self, search_term: str) -> dict:
        """
        [cite_start]Крок 1: Пошук зупинок за назвою. [cite: 1116-1120]
        """
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

                timeout = aiohttp.ClientTimeout(total=15) # Збільшено до 15 секунд
                async with session.get(url, timeout=timeout) as response:
                    if response.status == 200:
                        # API може повернути text/html, змушуємо парсити
                        data = await response.json(content_type=None)
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
        """
        [cite_start]Крок 2: Отримання інформації v1.2 про зупинку. [cite: 1150-1154]
        """
        params = {
            "login": self.config.LOGIN,
            "password": self.config.PASSWORD,
            "function": "stops.GetStopInfo",
            "city": self.config.DEFAULT_CITY,
            "id": stop_id,
            "v": self.config.STOP_INFO_VERSION,  # НОВА ВЕРСІЯ!
            "format": self.config.DEFAULT_FORMAT,
        }
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                url = self._build_url(params)
                logger.info(f"EasyWay API Call: {url}")

                timeout = aiohttp.ClientTimeout(total=15) # Збільшено до 15 секунд
                async with session.get(url, timeout=timeout) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)  # Додано content_type=None
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

    # === НОВІ ПРИВАТНІ МЕТОДИ (ПАРСЕРИ з плану v1.2) ===

    def _build_url(self, params: Dict) -> str:

        """Будує URL для АРІ запиту [cite: 1211-1215]"""
        # Використовуємо self.base_url замість self.config.BASE_URL для сумісності
        base = self.base_url
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{base}/?{query_string}"

    def _parse_places_response(self, data: dict, root_key: str = "item") -> dict:
        """
        [cite_start]Парсить відповідь cities.GetPlacesByName [cite: 1216-1217]
        (Виправлено: root_key="item" на основі логів)
        """
        try:
            items = data.get(root_key, [])
            if not isinstance(items, list):
                items = [items]

            parsed_stops = []
            for item in items:
                if item.get("type") == "stop":
                    parsed_stops.append({
                        "id": int(item.get("id", 0)),
                        "title": item.get("title", ""),
                        "lat": float(item.get("lat", 0)),
                        "lng": float(item.get("lng", 0)),
                    })
            logger.info(f"Parsed {len(parsed_stops)} stops from GetPlacesByName (out of {len(items)} items found)")
            return {"stops": parsed_stops}
        except Exception as e:
            logger.error(f"Error parsing places response: {e}")
            return {"error": f"Error parsing places response: {e}"}

        # services/easyway_service.py

    def _parse_stop_info_v12(self, data: Dict) -> Dict:
        """
        Парсить відповідь stops.GetStopInfo v1.2
        (Виправлено: API повертає 'routes' на кореневому рівні, а не 'stop.transports')
            """
        try:
            # === ВИПРАВЛЕННЯ (з логу 14:57:54) ===
            # 'data' - це і є об'єкт зупинки. Ключа "stop" не існує.
            stop = data

            parsed = {
                "id": stop.get("id"),
                "title": stop.get("title"),
                "lat": float(stop.get("lat", 0)),
                "lng": float(stop.get("lng", 0)),
                "routes": [],
            }

            # Ключ 'routes' знаходиться на тому ж рівні, що й 'id'
            # (НЕ 'transports' всередині 'stop')
            transports = stop.get("routes", [])
            if not isinstance(transports, list):
                transports = [transports]

            for route in transports:
                # Внутрішня структура маршруту, здається, правильна
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

            logger.info(f"Parsed {len(parsed['routes'])} routes from GetStopInfo v1.2")
            return parsed
        except Exception as e:
            logger.error(f"Error parsing stop info v1.2: {e}")
            return {"error": f"Error parsing stop info v1.2: {e}"}

    # === НОВА БІЗНЕС-ЛОГІКА (з плану v1.2) ===

    def filter_handicapped_routes(self, stop_info: dict) -> List[dict]:
        """
        Фільтрує тільки низькопідлоговий транспорт.
        [cite_start]Сортує за часом прибуття. [cite: 1306-1308]
        """
        handicapped_routes = []
        for route in stop_info.get("routes", []):
            if route.get("handicapped"):
                if route.get("transport_key") != "marshrutka":
                    handicapped_routes.append(route)

        handicapped_routes.sort(key=lambda r: r["time_left"])
        return handicapped_routes

    def get_transport_icon(self, transport_key: str) -> str:

        """ Отримує іконку для типу транспорту [cite: 1319-1320] """
        return self.transport_icons.get(transport_key, "❓")

    def get_time_source_icon(self, time_source: str) -> str:

        """ Отримує іконку для джерела часу [cite: 1327-1328] """
        return self.time_icons.get(time_source, "❓")


easyway_service = EasyWayService()
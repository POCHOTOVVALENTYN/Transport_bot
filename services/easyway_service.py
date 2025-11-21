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
# === 👇 ДОДАНО ІМПОРТ РЕЄСТРУ 👇 ===
from config.accessible_vehicles import ACCESSIBLE_TRAMS, ACCESSIBLE_TROLS

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

        # === ВИПРАВЛЕННЯ 1: Видалено self._lock ===
        # Кеш залишаємо, він thread-safe для читання/запису в Python (GIL)
        self.stop_cache = TTLCache(maxsize=1000, ttl=30)
        logger.info("✅ EasyWay Stop Cache initialized (TTL=30s)")

    async def get_routes_list(self) -> dict:
        """Отримує список маршрутів (з авто-повтором)"""
        params = {
            "login": self.login,
            "password": self.password,
            "function": "cities.GetRoutesList",
            "city": self.city,
            "format": self.config.DEFAULT_FORMAT
        }

        url = self._build_url(params)
        timeout = aiohttp.ClientTimeout(total=20)  # Збільшений таймаут для важкого запиту

        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                    logger.info(f"EasyWay API Call (RoutesList) Attempt {attempt + 1}/3: {url}")

                    async with session.get(url, timeout=timeout) as response:
                        if response.status == 200:
                            data = await response.json(content_type=None)
                            return data
                        else:
                            # Логуємо помилку, але не падаємо одразу
                            logger.warning(f"API returned status {response.status} for GetRoutesList")

            except (asyncio.TimeoutError, Exception) as e:
                logger.warning(f"GetRoutesList error (Attempt {attempt + 1}/3): {e}")

            # Чекаємо перед наступною спробою
            if attempt < 2:
                await asyncio.sleep(2)

        return {"error": "Не вдалося завантажити список маршрутів після 3 спроб."}

    async def get_places_by_name(self, search_term: str) -> dict:
        """Пошук зупинок за назвою (з авто-повтором)"""
        params = {
            "login": self.config.LOGIN,
            "password": self.config.PASSWORD,
            "function": "cities.GetPlacesByName",
            "city": self.config.DEFAULT_CITY,
            "term": search_term,
            "format": self.config.DEFAULT_FORMAT,
        }

        url = self._build_url(params)
        # Збільшуємо таймаут до 10 секунд
        timeout = aiohttp.ClientTimeout(total=10)

        # Робимо 3 спроби
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                    logger.info(f"EasyWay API Call (Attempt {attempt + 1}/3): {url}")

                    async with session.get(url, timeout=timeout) as response:
                        if response.status == 200:
                            data = await response.json(content_type=None)

                            # --- ДІАГНОСТИЧНИЙ ЛОГ (залишаємо, як було) ---
                            try:
                                import json
                                raw_json_data = json.dumps(data, indent=2, ensure_ascii=False)
                                logger.info(f"===== RAW API RESPONSE for term '{search_term}' =====")
                                logger.info(raw_json_data)
                                logger.info(f"=====================================================")
                            except Exception:
                                pass
                            # -----------------------------------------------

                            return self._parse_places_response(data, root_key="item")
                        else:
                            logger.warning(f"API returned status {response.status}, retrying...")

            except asyncio.TimeoutError:
                logger.warning(f"Request timed out (Attempt {attempt + 1}/3). Retrying...")
            except Exception as e:
                logger.error(f"Request error (Attempt {attempt + 1}/3): {e}")

            # Чекаємо 1 секунду перед наступною спробою (крім останньої)
            if attempt < 2:
                await asyncio.sleep(1)

        # Якщо всі спроби вичерпано
        return {"error": "Сервер не відповів вчасно. Спробуємо ще раз."}

    async def get_stop_info_v12(self, stop_id: int) -> dict:
        """Отримання інформації v1.2 про зупинку (з блокуванням)"""

        # 1. Швидка перевірка (без блокування)
        if stop_id in self.stop_cache:
            logger.info(f"💎 Cache HIT (Fast) for stop_id: {stop_id}")
            return self.stop_cache[stop_id]

        # 4. Якщо кешу все ще немає - робимо запит
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
                    logger.info(f"EasyWay API Call v1.2 (REAL REQUEST): {url}")  # Логуємо тільки реальні запити
                    async with session.get(url, timeout=timeout) as response:
                        if response.status == 200:
                            data = await response.json(content_type=None)
                            parsed_data = self._parse_stop_info_v12(data)

                            if not parsed_data.get("error"):
                                self.stop_cache[stop_id] = parsed_data
                                logger.info(f"💾 Saved to cache: stop_id {stop_id}")

                            return parsed_data
            except Exception as e:
                logger.warning(f"Error: {e}")
                if attempt < 2: await asyncio.sleep(0.5)

        return {"error": "Сервер не відповів."}

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
                # Шукаємо "type"
                item_type = attributes.get("type")

                # Якщо це зупинка (або вузол)
                if item_type == "stop":
                    trams = []
                    trols = []

                    # Парсинг маршрутів
                    routes_data = item.get("routes", {}).get("route", [])
                    if not isinstance(routes_data, list):
                        routes_data = [routes_data] if routes_data else []

                    for route in routes_data:
                        if not route: continue
                        title = route.get("title")

                        # Отримуємо тип маршруту
                        attrs = route.get("@attributes", {})
                        rtype = attrs.get("type") or route.get("type")

                        if not title: continue

                        if rtype == "tram":
                            trams.append(title)
                        elif rtype == "trol":
                            trols.append(title)
                        # Можна додати логування, якщо тип невідомий, для відладки
                        # else:
                        #    logger.info(f"Unknown route type: {rtype}")

                    # Формуємо рядок опису
                    summary_parts = []
                    if trams:
                        summary_parts.append(f"{self.transport_icons['tram']} {', '.join(trams)}")
                    if trols:
                        summary_parts.append(f"{self.transport_icons['trol']} {', '.join(trols)}")

                    routes_summary = " | ".join(summary_parts)

                    # === 👇 ЗМІНА ТУТ: Фільтруємо "пусті" зупинки 👇 ===
                    # Якщо на зупинці немає ні трамваїв, ні тролейбусів (рядок пустий) - пропускаємо її
                    if routes_summary:
                        parsed_stops.append({
                            "id": int(item.get("id", 0)),
                            "title": item.get("title", ""),
                            "lat": float(item.get("lat", 0)),
                            "lng": float(item.get("lng", 0)),
                            "routes_summary": routes_summary
                        })
                    # ===================================================

            logger.info(f"Parsed {len(parsed_stops)} stops")
            return {"stops": parsed_stops}

        except Exception as e:
            logger.error(f"Error parsing places response: {e}", exc_info=True)
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
                # === КРОК 2: ЛОГІКА ЗЛИТТЯ (MERGE) ===

                # Отримуємо бортовий номер та тип транспорту
                bort_number = str(route.get("bortNumber", "")).strip()
                transport_key = route.get("transportKey")  # 'tram', 'trol', 'bus' або 'marshrutka'


                # 1. Отримуємо статус з API
                is_api_handicapped = route.get("handicapped", False)



                # 2. Перевіряємо у локальному реєстрі
                is_local_handicapped = False
                if transport_key == 'tram' and bort_number in ACCESSIBLE_TRAMS:
                    is_local_handicapped = True
                    logger.info(f"✅ Tram {bort_number} found in LOCAL registry (ACCESSIBLE_TRAMS)")
                elif transport_key == 'trol' and bort_number in ACCESSIBLE_TROLS:
                    is_local_handicapped = True
                    logger.info(f"✅ Trolleybus {bort_number} found in LOCAL registry (ACCESSIBLE_TROLS)")

                # 3. Фінальне рішення: "АБО" логіка
                # Транспорт вважається інклюзивним, якщо він позначений як такий в API АБО у локальному реєстрі
                final_handicapped_status = is_api_handicapped or is_local_handicapped

                # --- РОЗШИРЕНЕ ЛОГУВАННЯ (ДЛЯ ВСІХ маршрутів) ---
                logger.info(
                    f"🚋 Route {route.get('title')} | Bort: {bort_number} | Type: {transport_key} | "
                    f"API: {is_api_handicapped} | Local: {is_local_handicapped} | FINAL: {final_handicapped_status}"
                )

                # Логування для діагностики
                if final_handicapped_status:
                    logger.info(
                        f"🚋 Route: {route.get('title')} (Bort: {bort_number}, Type: {transport_key}) "
                        f"-> API: {is_api_handicapped}, Local: {is_local_handicapped} -> FINAL: {final_handicapped_status}"
                    )

                # === КОНЕЦЬ ЛОГІКИ ЗЛИТТЯ ===

                parsed_route = {
                    "id": route.get("id"),
                    "title": route.get("title"),
                    "direction": route.get("directionTitle"),
                    "transport_name": route.get("transportName"),
                    "transport_key": route.get("transportKey"),
                    "handicapped": final_handicapped_status,  # Використовуємо результат злиття
                    "bort_number": route.get("bortNumber"),
                    "time_left": float(route.get("timeLeft", 9999)),
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

    async def get_vehicles_on_route(self, route_id: int) -> List[dict]:
        """
        Отримує список низькопідлогових вагонів на маршруті через EasyWay API.
        Використовується для Fallback-сценарію.
        """
        params = {
            "login": self.config.LOGIN,
            "password": self.config.PASSWORD,
            "function": "routes.GetRouteInfo",
            "city": self.config.DEFAULT_CITY,
            "id": route_id,
            "format": self.config.DEFAULT_FORMAT,
        }

        url = self._build_url(params)

        # Робимо один запит (без складних ретраїв, бо це fallback)
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                logger.info(f"EasyWay API Call (RouteInfo): {url}")
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        # Парсимо відповідь
                        return self._parse_route_vehicles(data)
                    else:
                        logger.warning(f"API returned status {response.status} for GetRouteInfo")
        except Exception as e:
            logger.error(f"Error getting route info: {e}")

        return []

    def _parse_route_vehicles(self, data: dict) -> List[dict]:
        """Парсить транспорт з відповіді routes.GetRouteInfo"""
        accessible_vehicles = []

        try:
            route_data = data.get("routes", {})
            if not route_data:
                return []

            # Отримуємо список транспорту
            vehicles = route_data.get("vehicles", {}).get("vehicle", [])
            if not isinstance(vehicles, list):
                vehicles = [vehicles]

            for v in vehicles:
                if not v: continue

                # Отримуємо дані
                bort_number = str(v.get("name", "")).strip()  # У цьому методі номер часто в полі name
                lat = float(v.get("lat", 0))
                lng = float(v.get("lng", 0))

                # === ПЕРЕВІРКА НА ІНКЛЮЗИВНІСТЬ ===
                # У цьому методі API іноді не повертає поле handicapped явно,
                # тому покладаємось на наші списки та логіку

                is_accessible = False

                # 1. Спробуємо знайти тип транспорту з контексту (але API тут його не дає чітко)
                # Тому перевіряємо по наших списках бортів
                if bort_number in ACCESSIBLE_TRAMS or bort_number in ACCESSIBLE_TROLS:
                    is_accessible = True

                # 2. Якщо API все ж повернуло атрибут (перевіряємо про всяк випадок)
                if v.get("handicapped"):
                    is_accessible = True

                if is_accessible:
                    accessible_vehicles.append({
                        "bort": bort_number,
                        "lat": lat,
                        "lng": lng
                    })

        except Exception as e:
            logger.error(f"Error parsing route vehicles: {e}")

        return accessible_vehicles


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
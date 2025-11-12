from utils.logger import logger
import aiohttp
import logging
from config.settings import (
    EASYWAY_API_URL, EASYWAY_LOGIN, EASYWAY_PASSWORD, EASYWAY_CITY
)


class EasyWayService:
    def __init__(self):
        self.base_url = EASYWAY_API_URL
        # Формуємо базові параметри для всіх запитів
        self.base_params = {
            "login": EASYWAY_LOGIN,
            "password": EASYWAY_PASSWORD,
            "city": EASYWAY_CITY
        }

    async def _get(self, params: dict) -> dict:
        """Приватний метод для виконання GET-запитів до API."""
        # Об'єднуємо базові параметри з параметрами функції
        full_params = self.base_params.copy()
        full_params.update(params)

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.base_url, params=full_params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("error"):
                            logger.error(f"EasyWay API Error: {data['error']}")
                            return {"error": data.get("errorText", "Unknown API error")}
                        return data
                    else:
                        logger.error(f"EasyWay HTTP Error: Status {response.status}")
                        return {"error": f"HTTP Error: {response.status}"}
            except Exception as e:
                logger.error(f"EasyWay aiohttp Error: {e}", exc_info=True)
                return {"error": f"Connection error: {e}"}

    async def get_routes_list(self) -> dict:
        """
        Отримує список всіх маршрутів міста.
        Ми будемо використовувати це для пошуку ID маршрутів за їх назвами.
        """
        params = {
            "function": "cities.GetRoutesList"
        }
        return await self._get(params)

    async def get_route_info(self, route_id: str) -> dict:
        """
        Отримує повну інформацію про маршрут (напрямки, зупинки).
        """
        params = {
            "function": "routes.GetRouteInfo",
            "id": route_id
        }
        return await self._get(params)

    async def get_stops_near_point(self, lat: float, lon: float, radius_m: int = 500) -> dict:
        """
        Знаходить зупинки в радіусі (за замовчуванням 500м) від точки.
        """
        params = {
            "function": "stops.GetStopsNearPoint",
            "lat": str(lat),
            "lon": str(lon),
            "radius": str(radius_m)
        }
        return await self._get(params)

    async def get_stop_arrivals(self, stop_id: str) -> dict:
        """
        Отримує прогноз прибуття на конкретну зупинку.
        Це наш ключовий метод.
        """
        params = {
            "function": "stops.GetStopInfo",
            "id": stop_id,
            "v": "1.2"  # Використовуємо версію 1.2, як вказано у вашій інструкції
        }
        return await self._get(params)

# Створюємо один екземпляр сервісу для всього бота
easyway_service = EasyWayService()
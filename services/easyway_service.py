# services/easyway_service.py
from utils.logger import logger
import aiohttp
import json
import logging
from config.settings import (
    EASYWAY_API_URL, EASYWAY_LOGIN, EASYWAY_PASSWORD, EASYWAY_CITY
)

# Використовуємо logger з utils
logger = logging.getLogger("transport_bot")


class EasyWayService:
    def __init__(self):
        self.base_url = EASYWAY_API_URL
        self.base_params = {
            "login": EASYWAY_LOGIN,
            "password": EASYWAY_PASSWORD,
            "city": EASYWAY_CITY
        }

    async def _get(self, params: dict) -> dict:
        full_params = self.base_params.copy()
        full_params.update(params)

        # (Залишаємо 'ssl=False' як тимчасове рішення для вашого Mac)
        connector = aiohttp.TCPConnector(ssl=False)

        async with aiohttp.ClientSession(connector=connector) as session:
            try:
                async with session.get(self.base_url, params=full_params) as response:
                    if response.status == 200:
                        raw_text = await response.text()
                        if not raw_text:
                            return {"error": "Empty response from API"}

                        logger.info(f"EasyWay API Raw Response (first 100 chars): {raw_text[:100]}")

                        json_part = raw_text
                        if "(" in raw_text and raw_text.endswith(")"):
                            start_brace = raw_text.find("(")
                            if start_brace != -1:
                                json_part = raw_text[start_brace + 1: -1]

                        try:
                            data = json.loads(json_part)
                        except json.JSONDecodeError as e:
                            return {"error": f"JSON Decode Error: {e}"}

                        # --- ВИПРАВЛЕННЯ AttributeError ---
                        if data.get("error"):
                            error_details = data['error']
                            error_message = "Unknown API error"

                            if isinstance(error_details, dict):
                                error_message = error_details.get("message", "Unknown API error")
                            elif isinstance(error_details, str):
                                error_message = error_details

                            logger.error(f"EasyWay API Error: {error_details}")
                            return {"error": error_message}
                        # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

                        return data
                    else:
                        return {"error": f"HTTP Error: {response.status}"}
            except Exception as e:
                logger.error(f"EasyWay aiohttp Error: {e}", exc_info=True)
                return {"error": f"Connection error: {e}"}

    async def get_routes_list(self) -> dict:
        """ (ЦЕ ВЖЕ ПРАЦЮЄ) """
        params = {"function": "cities.GetRoutesList"}
        return await self._get(params)

    async def get_route_info(self, route_id: str) -> dict:
        """
        (ВИПРАВЛЕНО) Отримує деталі маршруту (для 'shortDescription')
        """
        params = {
            "function": "routes.GetRouteInfo",
            "id": route_id
        }
        return await self._get(params)

    async def get_route_to_display(self, route_id: str, start_pos: str, stop_pos: str) -> dict:
        """
        (НОВА) Отримує повний шлях (точки) та зупинки маршруту
        """
        params = {
            "function": "routes.GetRouteToDisplay",
            "id": route_id,
            "start_position": start_pos,
            "stop_position": stop_pos
        }
        return await self._get(params)

    async def get_route_gps(self, route_id: str) -> dict:
        """
        (НОВА) Отримує GPS-дані транспорту на маршруті.
        """
        params = {
            "function": "routes.GetRouteGPS",
            "id": route_id
        }
        return await self._get(params)



easyway_service = EasyWayService()
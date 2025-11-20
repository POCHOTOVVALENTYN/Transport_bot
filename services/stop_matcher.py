import csv
import math
import io
import zipfile
import requests
import logging
from config.settings import EASYWAY_API_URL  # Або URL для static, якщо є окремий

logger = logging.getLogger("transport_bot")


class StopMatcher:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StopMatcher, cls).__new__(cls)
            cls._instance.stops = []  # Список словників {'lat', 'lon', 'name'}
        return cls._instance

    def load_stops_from_static(self, api_key: str):
        """Завантажує stops.txt з GTFS Static (один раз при старті)"""
        if self.stops:
            return  # Вже завантажено

        url = "https://gw.x24.digital/api/od/gtfs/v1/download/static"
        headers = {'ApiKey': api_key}

        # === ДОДАНО: Вимкнення попереджень SSL ===
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # =========================================

        logger.info("🗺️ Завантаження бази зупинок (Static GTFS)...")
        try:
            resp = requests.get(url, headers=headers, timeout=30, verify=False)
            if resp.status_code != 200:
                logger.error(f"Failed to download static GTFS: {resp.status_code}")
                return

            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                with z.open('stops.txt') as f:
                    reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'))
                    for row in reader:
                        try:
                            self.stops.append({
                                'name': row['stop_name'],
                                'lat': float(row['stop_lat']),
                                'lon': float(row['stop_lon'])
                            })
                        except (ValueError, KeyError):
                            continue
            logger.info(f"✅ База зупинок завантажена: {len(self.stops)} об'єктів.")

        except Exception as e:
            logger.error(f"Error loading stops: {e}")

    def find_nearest_stop_name(self, lat: float, lon: float) -> str:
        """Знаходить найближчу зупинку (Оптимізовано)"""
        if not self.stops:
            return "Невизначено"

        closest_name = "Невідомо"
        min_dist = float('inf')

        for stop in self.stops:
            # === ОПТИМІЗАЦІЯ: Груба фільтрація ===
            # Якщо зупинка далі ніж ~1км по широті/довготі, навіть не рахуємо точну відстань.
            # 0.01 градуса ~ 1.1 км
            if abs(stop['lat'] - lat) > 0.01 or abs(stop['lon'] - lon) > 0.01:
                continue
            # =====================================

            # Точний розрахунок тільки для кандидатів поруч
            dist = math.sqrt((stop['lat'] - lat) ** 2 + (stop['lon'] - lon) ** 2)
            if dist < min_dist:
                min_dist = dist
                closest_name = stop['name']

        return closest_name


stop_matcher = StopMatcher()
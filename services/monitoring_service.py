# services/monitoring_service.py
import asyncio
import aiohttp
import logging
import io
import csv
import zipfile
import requests
import html
import urllib3
from google.transit import gtfs_realtime_pb2
from services.stop_matcher import stop_matcher

logger = logging.getLogger("transport_bot")

# Налаштування
API_KEY = "a8c6d35e-f2c1-4f72-b902-831fa9215009"
REALTIME_URL = "https://gw.x24.digital/api/od/gtfs/v1/download/gtfs-rt-vehicles-pr.pb"
STATIC_URL = "https://gw.x24.digital/api/od/gtfs/v1/download/static"


class MonitoringService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MonitoringService, cls).__new__(cls)
            cls._instance.data = {}
            cls._instance.routes_map = {}  # RouteID -> RouteName (напр. "113" -> "5")
            cls._instance.trips_accessibility = {}  # TripID -> "1" або "2" або "0"
            cls._instance.running = False
        return cls._instance

    async def start(self):
        """Запускає фоновий цикл"""
        if self.running: return
        self.running = True
        logger.info("🚀 Monitoring Service started (Trip-based Logic).")

        import threading
        t = threading.Thread(target=self._load_static_data)
        t.start()

        while self.running:
            try:
                await self._update_data()
            except Exception as e:
                logger.error(f"Monitoring update failed: {e}")
            await asyncio.sleep(15)

    def _load_static_data(self):
        """Завантажує routes.txt та trips.txt"""
        logger.info("🔄 Loading GTFS Static data...")

        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        stop_matcher.load_stops_from_static(API_KEY)

        try:
            headers = {'ApiKey': API_KEY}
            resp = requests.get(STATIC_URL, headers=headers, timeout=60, verify=False)

            if resp.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:

                    # 1. Парсимо routes.txt (RouteID -> Human Name)
                    if 'routes.txt' in z.namelist():
                        with z.open('routes.txt') as f:
                            reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'))
                            for row in reader:
                                r_id = row.get('route_id')
                                r_name = row.get('route_short_name')
                                if r_id and r_name:
                                    self.routes_map[str(r_id)] = str(r_name).strip()
                        logger.info(f"✅ Routes map loaded: {len(self.routes_map)} routes.")

                    # 2. Парсимо trips.txt (Trip ID -> Accessibility)
                    if 'trips.txt' in z.namelist():
                        with z.open('trips.txt') as f:
                            reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'))

                            # Перевіряємо наявність колонки 'wheelchair_accessible'
                            fieldnames = reader.fieldnames if reader.fieldnames else []
                            has_accessibility_info = 'wheelchair_accessible' in fieldnames

                            if not has_accessibility_info:
                                logger.warning(
                                    "⚠️ 'wheelchair_accessible' column NOT FOUND in trips.txt! All trips will be treated as unknown.")

                            count_accessible = 0
                            for row in reader:
                                t_id = row.get('trip_id')
                                # Якщо колонки немає, get поверне None, і ми запишемо '0' (невідомо)
                                wheelchair = row.get('wheelchair_accessible', '0')

                                if t_id:
                                    self.trips_accessibility[str(t_id)] = str(wheelchair)
                                    if str(wheelchair) == '1':
                                        count_accessible += 1

                        logger.info(
                            f"✅ Trips map loaded: {len(self.trips_accessibility)} trips. (Accessible marked: {count_accessible})")
                    else:
                        logger.warning("⚠️ 'trips.txt' not found.")

            else:
                logger.warning(f"Failed to load Static GTFS: {resp.status_code}")

        except Exception as e:
            logger.error(f"Error loading static data: {e}", exc_info=True)

    async def _update_data(self):
        headers = {'ApiKey': API_KEY}
        connector = aiohttp.TCPConnector(ssl=False)

        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(REALTIME_URL, headers=headers) as resp:
                    if resp.status != 200:
                        return
                    content = await resp.read()

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(content)

            new_data = {}
            debug_log_counter = 0

            for entity in feed.entity:
                if not entity.HasField('vehicle'): continue

                veh = entity.vehicle

                # Отримуємо інформацію про маршрут
                raw_route_id = str(veh.trip.route_id).strip()
                # Перетворюємо ID маршруту в номер (напр. 113 -> 5)
                route_num = self.routes_map.get(raw_route_id, raw_route_id)

                # Отримуємо інформацію про рейс (Trip)
                trip_id = str(veh.trip.trip_id).strip()

                # Перевіряємо доступність через Trip
                # '1' = доступно, '2' = ні, '0' = невідомо
                accessibility_status = self.trips_accessibility.get(trip_id, '0')

                # === ЛОГІКА ВИЗНАЧЕННЯ ІНКЛЮЗИВНОСТІ ===
                # Якщо trips.txt містить '1', то це точно інклюзивний транспорт.
                # Якщо ми не знайшли інформації ('0'), ми поки що ІГНОРУЄМО такий транспорт,
                # щоб не показувати старі вагони як інклюзивні.
                is_accessible = (accessibility_status == '1')

                # Отримуємо назву для відображення (Бортовий номер)
                raw_id = str(veh.vehicle.id).strip()
                label = str(veh.vehicle.label).strip()
                plate = str(veh.vehicle.license_plate).strip()

                # Вибираємо найкращу назву для відображення
                bort_number = label if label else (plate if plate else raw_id)

                # ЛОГ ДІАГНОСТИКИ (Перші 5 елементів)
                if debug_log_counter < 5:
                    logger.info(
                        f"🔍 TRIP CHECK: Route {route_num} | TripID='{trip_id}' -> Acc='{accessibility_status}' -> IsAcc? {is_accessible}")
                    debug_log_counter += 1

                if is_accessible:
                    lat = veh.position.latitude
                    lon = veh.position.longitude
                    stop_name = stop_matcher.find_nearest_stop_name(lat, lon)

                    vehicle_data = {
                        "bort": html.escape(bort_number),
                        "stop_name": html.escape(stop_name)
                    }

                    if route_num not in new_data:
                        new_data[route_num] = []
                    new_data[route_num].append(vehicle_data)

            self.data = new_data

        except Exception as e:
            logger.error(f"Error in _update_data: {e}")

    def get_accessible_on_route(self, route_num: str) -> list:
        search_key = str(route_num).strip()
        return self.data.get(search_key, [])


monitoring_service = MonitoringService()
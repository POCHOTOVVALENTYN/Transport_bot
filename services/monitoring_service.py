# services/monitoring_service.py
import asyncio
import aiohttp
import logging
import io
import csv
import zipfile
import requests  # Використовуємо requests для синхронного завантаження static (в окремому потоці)
import html
from google.transit import gtfs_realtime_pb2
from config.accessible_vehicles import ACCESSIBLE_TRAMS, ACCESSIBLE_TROLS
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
            cls._instance.data = {}  # { "5": ["Вагон...", ...], "28": [...] }
            cls._instance.routes_map = {}  # { "113": "5", "204": "28" }
            # === ДОДАНО: Мапа вагонів ===
            cls._instance.vehicles_map = {}  # { "600780355": "4015", ... } (VehicleID -> Label)
            # ============================
            cls._instance.running = False
        return cls._instance

    async def start(self):
        """Запускає фоновий цикл"""
        if self.running: return
        self.running = True
        logger.info("🚀 Monitoring Service started.")

        # 1. Завантажуємо Static дані (Зупинки та Маршрути)
        # Робимо це в окремому потоці, щоб не блокувати бота при старті
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
        """Завантажує routes.txt та vehicles.txt (якщо є)"""
        logger.info("🔄 Loading GTFS Static data...")

        # Вимкнення попереджень SSL (важливо для цього сервера)
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Завантажуємо зупинки (це вже було)
        stop_matcher.load_stops_from_static(API_KEY)

        try:
            headers = {'ApiKey': API_KEY}
            # Збільшуємо таймаут до 60 сек, verify=False обов'язково
            resp = requests.get(STATIC_URL, headers=headers, timeout=60, verify=False)

            if resp.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:

                    # 1. Парсимо routes.txt (Route ID -> "5") - ЦЕ ВЖЕ БУЛО
                    if 'routes.txt' in z.namelist():
                        with z.open('routes.txt') as f:
                            reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'))
                            for row in reader:
                                r_id = row.get('route_id')
                                r_name = row.get('route_short_name')
                                if r_id and r_name:
                                    self.routes_map[str(r_id)] = str(r_name).strip()
                        logger.info(f"✅ Routes map loaded: {len(self.routes_map)} items.")

                    # 2. Парсимо vehicles.txt (Vehicle ID -> "4015") - === ЦЕ НОВЕ ===
                    if 'vehicles.txt' in z.namelist():
                        with z.open('vehicles.txt') as f:
                            reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'))
                            for row in reader:
                                # Нам потрібні vehicle_id (системний) і label (бортовий)
                                # Іноді поле називається 'vehicle_label'
                                v_id = row.get('vehicle_id')
                                label = row.get('label') or row.get('vehicle_label')

                                if v_id and label:
                                    # Зберігаємо у словник: "600780355" -> "4015"
                                    self.vehicles_map[str(v_id)] = str(label).strip()

                        logger.info(f"✅ Vehicles map loaded: {len(self.vehicles_map)} items.")
                    else:
                        logger.warning("⚠️ 'vehicles.txt' not found in GTFS Static archive.")
                    # ================================================================

            else:
                logger.warning(f"Failed to load Static GTFS: {resp.status_code}")

        except Exception as e:
            logger.error(f"Error loading static data: {e}")

    async def _update_data(self):
        """Оновлює дані про місцезнаходження транспорту"""
        headers = {'ApiKey': API_KEY}
        connector = aiohttp.TCPConnector(ssl=False)

        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(REALTIME_URL, headers=headers) as resp:
                    if resp.status != 200:
                        logger.warning(f"Realtime API error: {resp.status}")
                        return
                    content = await resp.read()

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(content)

            new_data = {}
            debug_log_counter = 0 # Лічильник для обмеження логів  # Для логування

            for entity in feed.entity:

                if not entity.HasField('vehicle'): continue

                veh = entity.vehicle
                # 1. Отримуємо ID (системний, напр. "600780355")
                raw_vehicle_id = str(veh.vehicle.id).strip()

                # 2. Пробуємо отримати Label (з фіда або з нашої мапи)
                feed_label = veh.vehicle.label  # Іноді тут пусто

                # === ГОЛОВНА ЗМІНА: Шукаємо в нашому новому словнику ===
                static_label = self.vehicles_map.get(raw_vehicle_id)

                # ПРІОРИТЕТ: Static Map > Feed Label > Feed ID
                # Якщо знайшли у Static Map (4015) - беремо його.
                # Якщо ні, пробуємо feed_label. Якщо і там пусто - беремо ID.
                bort_number = str(static_label or feed_label or raw_vehicle_id).strip()
                # =======================================================
                raw_route_id = str(veh.trip.route_id).strip()
                # === КРИТИЧНО ВАЖЛИВО: ПЕРЕТВОРЕННЯ ID ===
                # Якщо мапи немає, route_num залишиться як raw_route_id (напр. "113")
                route_num = self.routes_map.get(raw_route_id, raw_route_id)

                # --- ДЕБАГ (Оновлений) ---
                # Виводимо перші 5 вагонів, щоб переконатися, що мапінг спрацював
                if debug_log_counter < 5:
                    in_list = bort_number in ACCESSIBLE_TRAMS
                    # logger.info(f"🕵️ MAP CHECK: ID={raw_vehicle_id} -> BORT={bort_number} (In list? {in_list})")
                    debug_log_counter += 1
                # -------------------------

                # Перевірка на інклюзивність
                is_accessible = (bort_number in ACCESSIBLE_TRAMS) or (bort_number in ACCESSIBLE_TROLS)

                if is_accessible:
                    lat = veh.position.latitude
                    lon = veh.position.longitude
                    stop_name = stop_matcher.find_nearest_stop_name(lat, lon)

                    safe_stop_name = html.escape(stop_name)
                    safe_bort = html.escape(str(bort_number))

                    vehicle_data = {
                        "bort": safe_bort,
                        "stop_name": safe_stop_name
                    }

                    if route_num not in new_data:
                        new_data[route_num] = []
                    new_data[route_num].append(vehicle_data)

            self.data = new_data

            # === ДІАГНОСТИЧНИЙ ЛОГ ===
            # Виводимо це кожні 15 сек, щоб бачити стан
            map_status = "✅ LOADED" if self.routes_map else "❌ EMPTY"
            logger.info(f"--- MONITOR UPDATE ---")
            logger.info(f"Routes Map Status: {map_status} (Size: {len(self.routes_map)})")
            logger.info(f"Raw->Mapped samples: {list(debug_log_counter)[:5]}")
            logger.info(f"Data Keys (Available Routes): {list(self.data.keys())}")
            logger.info(f"----------------------")

        except Exception as e:
            logger.error(f"Error in _update_data: {e}", exc_info=True)

    def get_accessible_on_route(self, route_num: str) -> list:
        """
        Повертає список вагонів.
        route_num - це вже 'людський' номер (напр. '5').
        """
        # Нормалізація ключа: видаляємо пробіли, приводимо до рядка
        search_key = str(route_num).strip()

        # Спробуємо знайти прямий збіг
        result = self.data.get(search_key)

        if result:
            return result

        # Якщо не знайдено, спробуємо пошукати серед ключів, які можуть містити цей номер
        # (наприклад, якщо в базі '5а', а ми шукаємо '5')
        # Але для початку достатньо точного збігу після strip()
        return []


monitoring_service = MonitoringService()
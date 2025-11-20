# services/monitoring_service.py
import asyncio
import aiohttp
import logging
import io
import csv
import zipfile
import requests  # Використовуємо requests для синхронного завантаження static (в окремому потоці)
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
        """Завантажує routes.txt та stops.txt"""
        logger.info("🔄 Loading GTFS Static data...")

        # === ДОДАНО: Вимкнення попереджень SSL для requests ===
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # ======================================================

        # 1. Завантажуємо зупинки (через існуючий stop_matcher)
        # stop_matcher теж використовує requests, йому теж треба verify=False,
        # але поки виправимо тут завантаження маршрутів, яке є критичним для мапінгу.
        stop_matcher.load_stops_from_static(API_KEY)

        # 2. Завантажуємо мапу маршрутів (ID -> Назва)
        try:
            headers = {'ApiKey': API_KEY}
            # === ВИПРАВЛЕННЯ ТУТ: додано verify=False ===
            resp = requests.get(STATIC_URL, headers=headers, timeout=30, verify=False)

            if resp.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                    # Парсимо routes.txt
                    with z.open('routes.txt') as f:
                        reader = csv.DictReader(io.TextIOWrapper(f, encoding='utf-8'))
                        for row in reader:
                            r_id = row.get('route_id')
                            r_name = row.get('route_short_name')  # Це номер маршруту ("5", "10")
                            if r_id and r_name:
                                self.routes_map[str(r_id)] = str(r_name).strip()  # Гарантуємо рядки

                logger.info(f"✅ Routes map loaded: {len(self.routes_map)} routes mapped.")
                # Для налагодження можна розкоментувати:
                # logger.info(f"Sample mapping: {list(self.routes_map.items())[:5]}")
            else:
                logger.warning(f"Failed to load routes.txt: {resp.status_code}")
        except Exception as e:
            logger.error(f"Error loading routes map: {e}")

    async def _update_data(self):
        """Оновлює дані про місцезнаходження транспорту"""
        headers = {'ApiKey': API_KEY}
        # Використовуємо ігнорування SSL, бо сервер має проблеми з сертифікатом
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

            for entity in feed.entity:
                if not entity.HasField('vehicle'): continue

                veh = entity.vehicle
                # Отримуємо бортовий номер
                bort_number = str(veh.vehicle.label or veh.vehicle.id).strip()

                # Отримуємо ID маршруту (це "системний" ID, напр. 113)
                raw_route_id = str(veh.trip.route_id).strip()

                # === КРИТИЧНО ВАЖЛИВО: ПЕРЕТВОРЕННЯ ID ===
                # Ми намагаємося знайти "людський" номер ("5") у нашій мапі.
                # Якщо мапи немає або ID там немає - використовуємо сирий ID.
                route_num = self.routes_map.get(raw_route_id, raw_route_id)
                # =========================================

                # Перевірка: чи є цей вагон у нашому списку доступних?
                is_accessible = (bort_number in ACCESSIBLE_TRAMS) or (bort_number in ACCESSIBLE_TROLS)

                if is_accessible:
                    lat = veh.position.latitude
                    lon = veh.position.longitude

                    # Знаходимо назву найближчої зупинки
                    stop_name = stop_matcher.find_nearest_stop_name(lat, lon)

                    # Формуємо красивий рядок для виводу
                    info = (
                        f"🚋 <b>Борт №{bort_number}</b>\n"
                        f"📍 <i>Зараз біля: {stop_name}</i>"
                    )

                    # Зберігаємо під "людським" номером (напр. "5")
                    if route_num not in new_data:
                        new_data[route_num] = []
                    new_data[route_num].append(info)

            self.data = new_data
            # logger.info(f"Updated monitoring data. Routes found: {list(new_data.keys())}")

        except Exception as e:
            logger.error(f"Error in _update_data: {e}")

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
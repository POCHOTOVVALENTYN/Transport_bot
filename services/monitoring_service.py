import asyncio
import aiohttp
import logging
from google.transit import gtfs_realtime_pb2
from config.accessible_vehicles import ACCESSIBLE_TRAMS, ACCESSIBLE_TROLS
from services.stop_matcher import stop_matcher

logger = logging.getLogger("transport_bot")

# Налаштування (тимчасово хардкод, або винесіть в settings)
API_KEY = "a8c6d35e-f2c1-4f72-b902-831fa9215009"
REALTIME_URL = "https://gw.x24.digital/api/od/gtfs/v1/download/gtfs-rt-vehicles-pr.pb"


class MonitoringService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MonitoringService, cls).__new__(cls)
            cls._instance.data = {}  # {route_id: [InfoString, ...]}
            cls._instance.running = False
        return cls._instance

    async def start(self):
        """Запускає фоновий цикл"""
        if self.running: return
        self.running = True
        logger.info("🚀 Monitoring Service started.")

        # Завантажуємо базу зупинок (блокуючий виклик, але один раз)
        # Краще це робити в main.py, але можна і тут для простоти
        import threading
        t = threading.Thread(target=stop_matcher.load_stops_from_static, args=(API_KEY,))
        t.start()

        while self.running:
            try:
                await self._update_data()
            except Exception as e:
                logger.error(f"Monitoring update failed: {e}")

            await asyncio.sleep(15)  # Оновлення кожні 15 секунд

    async def _update_data(self):
        headers = {'ApiKey': API_KEY}
        # === ВИПРАВЛЕННЯ SSL ===
        # Створюємо конектор, який ігнорує помилки сертифікатів
        connector = aiohttp.TCPConnector(ssl=False)

        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(REALTIME_URL, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"Monitoring API returned status: {resp.status}")
                    return
                content = await resp.read()

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(content)

        new_data = {}  # Тимчасовий словник

        for entity in feed.entity:
            if not entity.HasField('vehicle'): continue

            veh = entity.vehicle
            bort_number = veh.vehicle.label  # або veh.vehicle.id, перевірте test_combined.py
            route_id = veh.trip.route_id

            # 1. Перевірка: чи є вагон у нашому Білому Списку?
            is_accessible = (bort_number in ACCESSIBLE_TRAMS) or (bort_number in ACCESSIBLE_TROLS)

            # (Опціонально) Можна довіряти і полю з API, якщо воно там є
            # if not is_accessible and ...check field...: is_accessible = True

            if is_accessible:
                # 2. Визначаємо місцезнаходження
                lat = veh.position.latitude
                lon = veh.position.longitude
                stop_name = stop_matcher.find_nearest_stop_name(lat, lon)

                info = f"🚋 <b>{bort_number}</b> (біля: <i>{stop_name}</i>)"

                if route_id not in new_data:
                    new_data[route_id] = []
                new_data[route_id].append(info)

        self.data = new_data  # Атомарне оновлення
        # logger.info(f"Updated accessible transport positions: {len(new_data)} routes found.")

    def get_accessible_on_route(self, route_id: str) -> list:
        """Повертає список рядків з інфо про вагони на маршруті"""
        # API EasyWay іноді має різні ID для маршрутів.
        # Тут треба бути уважним: route_id з GTFS може відрізнятися від EasyWay ID.
        # Але поки припустимо, що вони збігаються або ми їх знайдемо.
        return self.data.get(str(route_id), [])


monitoring_service = MonitoringService()
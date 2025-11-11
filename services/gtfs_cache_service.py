import requests
import zipfile
import io
import csv
import json
from utils.logger import logger
from config.settings import GTFS_API_KEY

# --- 1. Налаштування API ---
API_KEY = GTFS_API_KEY # <-- ВИПРАВЛЕНО
STATIC_URL = "https://gw.x24.digital/api/od/gtfs/v1/download/static"
headers = {'ApiKey': API_KEY}

# Файл для нашого внутрішнього реєстру
ACCESSIBILITY_FILE_PATH = "data/accessible_vehicles.json"

class GTFSCache:
    """
    Клас для завантаження та зберігання в пам'яті
    статичних даних GTFS та нашого реєстру доступності.

    ЦЯ ВЕРСІЯ НЕ ВИКОРИСТОВУЄ 'transitfeed'
    """
    def __init__(self):
        # Кеш для нашого JSON-файлу
        self.accessibility_map = {} # {vehicle_id: True/False}

        # Кеші для файлів з ZIP-архіву
        self.routes = {} # {route_id: route_name}
        self.stops = {} # {stop_id: {name, lat, lon}}
        self.trips = {} # {trip_id: {route_id, direction_id, service_id}}
        self.stop_times = {} # {trip_id: [stop_id_1, stop_id_2, ...]}

    def _read_csv_from_zip(self, zip_file, filename):
        """Допоміжна функція для читання CSV-файлу з ZIP-архіву."""
        with zip_file.open(filename, 'r') as f:
            csv_data = io.TextIOWrapper(f, encoding='utf-8')
            reader = csv.DictReader(csv_data) # Читаємо як dict
            return list(reader)

    def load_all_data(self):
        """
        Головний метод, який завантажує все при старті бота.
        """
        try:
            self._load_gtfs_static()
            logger.info(f"✅ GTFS Static завантажено. Маршрутів: {len(self.routes)}, Зупинок: {len(self.stops)}")
        except Exception as e:
            logger.error(f"❌ КРИТИЧНА ПОМИЛКА завантаження GTFS Static: {e}", exc_info=True)

        try:
            self._load_accessibility_registry()
            logger.info(f"✅ Внутрішній реєстр доступності завантажено. Відомо про {len(self.accessibility_map)} ТЗ.")
        except Exception as e:
            logger.error(f"❌ КРИТИЧНА ПОМИЛКА завантаження 'accessible_vehicles.json': {e}")
            logger.error("Функція пошуку інклюзивного транспорту не буде працювати.")

    def _load_gtfs_static(self):
        """Завантажує та парсить GTFS Static ZIP-архів вручну."""
        logger.info(f"Завантажую GTFS Static ZIP з {STATIC_URL}...")
        response = requests.get(STATIC_URL, headers=headers)
        if response.status_code != 200:
            raise Exception(f"Не вдалося завантажити Static ZIP. Статус: {response.status_code}")

        logger.info("✅ Static ZIP завантажено. Парсинг 'в пам'яті'...")
        zip_file = zipfile.ZipFile(io.BytesIO(response.content))

        # 1. Завантажуємо Маршрути (routes.txt)
        for row in self._read_csv_from_zip(zip_file, 'routes.txt'):
            self.routes[row['route_id']] = {
                "name": row['route_long_name'] or row['route_short_name'],
                "type": row['route_type'] # '2' = Трамвай, '3' = Тролейбус
            }

        # 2. Завантажуємо Зупинки (stops.txt)
        for row in self._read_csv_from_zip(zip_file, 'stops.txt'):
            self.stops[row['stop_id']] = {
                "name": row['stop_name'],
                "lat": float(row['stop_lat']),
                "lon": float(row['stop_lon'])
            }

        # 3. Завантажуємо Поїздки (trips.txt)
        for row in self._read_csv_from_zip(zip_file, 'trips.txt'):
            self.trips[row['trip_id']] = {
                "route_id": row['route_id'],
                "direction_id": row['direction_id'],
                "headsign": row['trip_headsign'] # Назва напрямку, напр. "В бік Аркадії"
            }

        # 4. Завантажуємо Час Зупинок (stop_times.txt) - найважливіший
        stop_times_data = self._read_csv_from_zip(zip_file, 'stop_times.txt')
        # Сортуємо, щоб гарантувати правильний порядок
        stop_times_data.sort(key=lambda x: (x['trip_id'], int(x['stop_sequence'])))

        for row in stop_times_data:
            trip_id = row['trip_id']
            if trip_id not in self.stop_times:
                self.stop_times[trip_id] = [] # Створюємо список зупинок для цієї поїздки

            # Додаємо ID зупинки у список в правильному порядку
            self.stop_times[trip_id].append(row['stop_id'])

    def _load_accessibility_registry(self):
        """Завантажує наш JSON-файл з реєстром інклюзивних ТЗ."""
        with open(ACCESSIBILITY_FILE_PATH, 'r', encoding='utf-8') as f:
            self.accessibility_map = json.load(f)

# Створюємо один глобальний екземпляр кешу
gtfs_cache = GTFSCache()
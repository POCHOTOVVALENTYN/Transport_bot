import requests
import zipfile
import io
import csv
from google.transit import gtfs_realtime_pb2
import logging

# Налаштування логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. Налаштування API ---
API_KEY = "a8c6d35e-f2c1-4f72-b902-831fa9215009"
STATIC_URL = "https://gw.x24.digital/api/od/gtfs/v1/download/static"
REALTIME_URL = "https://gw.x24.digital/api/od/gtfs/v1/download/gtfs-rt-vehicles-pr.pb"
headers = {'ApiKey': API_KEY}


def get_vehicle_accessibility_map() -> dict:
    """
    Завантажує GTFS Static ZIP, шукає 'vehicles.txt' (ПЛАН C)
    та створює словник: {'vehicle_id': 'wheelchair_accessible_value'}
    """
    logger.info(f"Завантажую GTFS Static ZIP-архів з {STATIC_URL}...")
    accessibility_map = {}

    try:
        response = requests.get(STATIC_URL, headers=headers)
        if response.status_code != 200:
            logger.error(f"Не вдалося завантажити Static ZIP. Статус: {response.status_code}")
            return {}

        logger.info("✅ Static ZIP завантажено. Шукаю 'vehicles.txt'...")

        zip_file = zipfile.ZipFile(io.BytesIO(response.content))

        # --- Шукаємо та парсимо vehicles.txt ---
        # Це наша нова ціль
        with zip_file.open('vehicles.txt', 'r') as f:
            csv_data = io.TextIOWrapper(f, encoding='utf-8')
            reader = csv.reader(csv_data)

            header = next(reader)

            try:
                # Згідно стандарту, ми шукаємо 'vehicle_id'
                vehicle_id_index = header.index('vehicle_id')
                wheelchair_index = header.index('wheelchair_accessible')
            except ValueError as e:
                logger.error(f"❌ КРИТИЧНО: У файлі 'vehicles.txt' відсутній стовпець: {e}")
                logger.error(f"Знайдені заголовки: {header}")
                return {}

            logger.info(
                f"Знайдено 'vehicle_id' (індекс {vehicle_id_index}) та 'wheelchair_accessible' (індекс {wheelchair_index}).")

            # Наповнюємо наш словник
            for row in reader:
                try:
                    vehicle_id = row[vehicle_id_index]
                    is_accessible = row[wheelchair_index]
                    accessibility_map[vehicle_id] = is_accessible
                except IndexError:
                    pass

        logger.info(f"✅ Словник доступності (з vehicles.txt) створено. Знайдено {len(accessibility_map)} ТЗ.")
        return accessibility_map

    except KeyError:
        logger.error("❌ ПОМИЛКА: Файл 'vehicles.txt' не знайдено в ZIP-архіві.")
        logger.info("--- Вміст архіву: ---")
        zip_file.printdir()
        return {}
    except Exception as e:
        logger.error(f"❌ КРИТИЧНА ПОМИЛКА при парсингу 'vehicles.txt': {e}")
        return {}


def check_realtime_vehicles_by_vehicle_id(accessibility_map: dict):
    """
    Завантажує GTFS Realtime та перевіряє 'vehicle.id'
    по нашому новому словнику.
    """
    if not accessibility_map:
        logger.error("Словник доступності (з vehicles.txt) порожній. Перевірка Realtime скасована.")
        return

    logger.info(f"Завантажую GTFS Realtime .pb файл...")
    try:
        response = requests.get(REALTIME_URL, headers=headers)
        if response.status_code != 200:
            logger.error(f"Не вдалося завантажити Realtime .pb. Статус: {response.status_code}")
            return

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)

        logger.info(f"✅ Realtime .pb розпарсено. {len(feed.entity)} ТЗ на лінії.")
        logger.info("--- Аналіз перших 10 транспортних засобів (пошук за vehicle.id) ---")

        found_accessible = 0
        for i, entity in enumerate(feed.entity):
            if i >= 10:
                break

            if entity.HasField('vehicle'):
                vehicle = entity.vehicle

                # --- ОСЬ НАША НОВА ЛОГІКА ---
                # Ми беремо ID фізичного вагона
                vehicle_id = vehicle.vehicle.id

                # Шукаємо цей ID у нашому словнику
                accessibility_status = accessibility_map.get(vehicle_id)
                # ------------------------------

                print(f"\n--- ТЗ #{i + 1} (Фізичний ID: {vehicle_id}) ---")
                print(f"  Координати: {vehicle.position.latitude}, {vehicle.position.longitude}")

                if accessibility_status == '1':
                    print(f"  ✅ ♿ ДОСТУПНІСТЬ (з 'vehicles.txt'): 1 (Доступно)")
                    found_accessible += 1
                elif accessibility_status == '2':
                    print(f"  ❌ ♿ ДОСТУПНІСТЬ (з 'vehicles.txt'): 2 (Недоступно)")
                elif accessibility_status == '0':
                    print(f"  ❌ ♿ ДОСТУПНІСТЬ (з 'vehicles.txt'): 0 (Не вказано)")
                else:
                    # Це нормально, якщо ID з Realtime немає у Static (напр., нові вагони)
                    print(f"  ❓ ♿ ДОСТУПНІСТЬ (з 'vehicles.txt'): Не знайдено ID '{vehicle_id}'")

        logger.info(f"\n--- ЗАГАЛЬНИЙ РЕЗУЛЬТАТ (ПЛАН C) ---")
        if found_accessible > 0:
            logger.info("✅✅✅ ПЕРЕМОГА! Ми знайшли дані про інклюзивність у 'vehicles.txt'!")
        else:
            logger.warning(
                "⚠️ УВАГА: Схоже, 'vehicles.txt' завантажився, але або він порожній, або серед перших 10 ТЗ немає інклюзивних.")


    except Exception as e:
        logger.error(f"❌ КРИТИЧНА ПОМИЛКА парсингу .pb: {e}", exc_info=True)


# --- 3. Головний блок виконання ---
if __name__ == "__main__":
    # 1. Отримуємо словник доступності з 'vehicles.txt'
    static_accessibility_map = get_vehicle_accessibility_map()

    # 2. Передаємо цей словник для перевірки Realtime даних
    check_realtime_vehicles_by_vehicle_id(static_accessibility_map)
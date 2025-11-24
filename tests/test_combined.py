import requests
import zipfile
import io
import csv  # Для читання .txt файлів з архіву
from google.transit import gtfs_realtime_pb2
import logging

# Налаштування логування, щоб бачити помилки
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. Налаштування API ---
API_KEY = "a8c6d35e-f2c1-4f72-b902-831fa9215009"
STATIC_URL = "https://gw.x24.digital/api/od/gtfs/v1/download/static"
REALTIME_URL = "https://gw.x24.digital/api/od/gtfs/v1/download/gtfs-rt-vehicles-pr.pb"
headers = {'ApiKey': API_KEY}


def get_accessibility_map_from_static() -> dict:
    """
    Завантажує GTFS Static ZIP, знаходить 'trips.txt' і
    створює словник (map) виду: {'trip_id': 'wheelchair_accessible_value'}
    """
    logger.info(f"Завантажую GTFS Static ZIP-архів з {STATIC_URL}...")
    accessibility_map = {}

    try:
        response = requests.get(STATIC_URL, headers=headers)
        if response.status_code != 200:
            logger.error(f"Не вдалося завантажити Static ZIP. Статус: {response.status_code}")
            return {}

        logger.info("✅ Static ZIP завантажено. Розпаковую 'trips.txt'...")

        zip_file = zipfile.ZipFile(io.BytesIO(response.content))

        # --- Шукаємо та парсимо trips.txt ---
        with zip_file.open('trips.txt', 'r') as f:
            # Декодуємо бінарний файл у текст і розбиваємо на рядки
            csv_data = io.TextIOWrapper(f, encoding='utf-8')
            reader = csv.reader(csv_data)

            # Читаємо заголовки (перший рядок)
            header = next(reader)

            # 2. Знаходимо індекси потрібних нам стовпців
            # (Це робить код стійким, навіть якщо порядок стовпців зміниться)
            try:
                trip_id_index = header.index('trip_id')
                wheelchair_index = header.index('wheelchair_accessible')
            except ValueError as e:
                logger.error(f"❌ КРИТИЧНО: У файлі 'trips.txt' відсутній стовпець: {e}")
                logger.error(f"Знайдені заголовки: {header}")
                return {}

            logger.info(
                f"Знайдено 'trip_id' (індекс {trip_id_index}) та 'wheelchair_accessible' (індекс {wheelchair_index}).")

            # 3. Наповнюємо наш словник
            for row in reader:
                try:
                    trip_id = row[trip_id_index]
                    is_accessible = row[wheelchair_index]  # Це буде '0', '1' або '2'
                    accessibility_map[trip_id] = is_accessible
                except IndexError:
                    pass  # Пропускаємо пошкоджені рядки

        logger.info(f"✅ Словник доступності створено. Знайдено {len(accessibility_map)} поїздок.")
        return accessibility_map

    except KeyError:
        logger.error("❌ ПОМИЛКА: Файл 'trips.txt' не знайдено в ZIP-архіві.")
        zip_file.printdir()
        return {}
    except Exception as e:
        logger.error(f"❌ КРИТИЧНА ПОМИЛКА при парсингу 'trips.txt': {e}")
        return {}


def check_realtime_vehicles(accessibility_map: dict):
    """
    Завантажує GTFS Realtime, парсить його та перевіряє кожну
    поїздку (trip) по нашому словнику доступності.
    """
    if not accessibility_map:
        logger.error("Словник доступності порожній. Перевірка Realtime скасована.")
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
        logger.info("--- Аналіз перших 10 транспортних засобів ---")

        found_accessible = 0
        for i, entity in enumerate(feed.entity):
            if i >= 10:  # Обмежимо вивід першими 10
                break

            if entity.HasField('vehicle'):
                vehicle = entity.vehicle
                trip_id = vehicle.trip.trip_id

                # --- ОСЬ НАША НОВА ЛОГІКА ---
                # Шукаємо trip_id з Realtime у нашому словнику зі Static
                accessibility_status = accessibility_map.get(trip_id)
                # ------------------------------

                print(f"\n--- ТЗ #{i + 1} (Поїздка ID: {trip_id}) ---")
                print(f"  Координати: {vehicle.position.latitude}, {vehicle.position.longitude}")

                if accessibility_status == '1':
                    print(f"  ✅ ♿ ДОСТУПНІСТЬ (з 'trips.txt'): 1 (Доступно)")
                    found_accessible += 1
                elif accessibility_status == '2':
                    print(f"  ❌ ♿ ДОСТУПНІСТЬ (з 'trips.txt'): 2 (Недоступно)")
                elif accessibility_status == '0':
                    print(f"  ❌ ♿ ДОСТУПНІСТЬ (з 'trips.txt'): 0 (Не вказано)")
                else:
                    print(f"  ❓ ♿ ДОСТУПНІСТЬ (з 'trips.txt'): Не знайдено trip_id '{trip_id}'")

        logger.info(f"\n--- ЗАГАЛЬНИЙ РЕЗУЛЬТАТ ---")
        logger.info(f"З перших 10 ТЗ, знайдено доступних: {found_accessible}")
        if '1' in accessibility_map.values():
            logger.info("✅✅✅ ПЕРЕМОГА! Ми знайшли дані про інклюзивність у 'trips.txt'!")
        else:
            logger.warning("⚠️ УВАГА: Схоже, 'trips.txt' завантажився, але не містить жодного ТЗ з прапорцем '1'.")


    except Exception as e:
        logger.error(f"❌ КРИТИЧНА ПОМИЛКА парсингу .pb: {e}", exc_info=True)


# --- 3. Головний блок виконання ---
if __name__ == "__main__":
    # 1. Отримуємо словник доступності зі Static ZIP
    static_accessibility_map = get_accessibility_map_from_static()

    # 2. Передаємо цей словник для перевірки Realtime даних
    check_realtime_vehicles(static_accessibility_map)
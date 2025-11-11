import requests
from google.transit import gtfs_realtime_pb2

# 1. Дані для запиту (з вашого повідомлення)
API_KEY = "a8c6d35e-f2c1-4f72-b902-831fa9215009"
REALTIME_URL = "https://gw.x24.digital/api/od/gtfs/v1/download/gtfs-rt-vehicles-pr.pb"

headers = {
    'ApiKey': API_KEY
}

print(f"🚀 Завантажую GTFS Realtime .pb файл з {REALTIME_URL}...")

try:
    response = requests.get(REALTIME_URL, headers=headers)

    if response.status_code != 200:
        print(f"❌ ПОМИЛКА: Не вдалося завантажити. Статус: {response.status_code}")
        print(f"Тіло відповіді: {response.text}")
        exit()

    # 2. Створюємо об'єкт стрічки (feed)
    feed = gtfs_realtime_pb2.FeedMessage()

    # 3. Парсимо (читаємо) бінарний контент
    feed.ParseFromString(response.content)

    print(f"✅ Файл .pb успішно розпарсено.")
    print(f"🕐 Час оновлення даних: {feed.header.timestamp}")

    # 4. Друкуємо дані ПЕРШИХ 5 транспортних засобів
    print(f"\n--- Показано перші 5 з {len(feed.entity)} ТЗ на лінії ---")

    for i, entity in enumerate(feed.entity):
        if i >= 5:
            break

        if entity.HasField('vehicle'):
            vehicle = entity.vehicle
            print(f"\n--- Транспортний засіб #{i+1} ---")
            print(f"  ID Засобу: {vehicle.vehicle.id}")
            print(f"  Маршрут ID: {vehicle.trip.route_id}")
            print(f"  Поїздка ID: {vehicle.trip.trip_id}")
            print(f"  Координати: {vehicle.position.latitude}, {vehicle.position.longitude}")

            # --- ЦЕ НАШІ КРИТИЧНІ ПИТАННЯ ---
            print(f"  Порядковий номер зупинки (sequence): {vehicle.current_stop_sequence}")
            print(f"  Статус (enum): {vehicle.current_status}")

            # Нам потрібно з'ясувати, де тут прапорець інклюзивності.
            # Ми шукаємо його у кількох місцях:
            has_wheelchair_flag_in_trip = vehicle.trip.HasField('wheelchair_accessible')
            print(f"  Чи є прапорець 'wheelchair_accessible' у 'trip'?: {has_wheelchair_flag_in_trip}")

except Exception as e:
    print(f"❌ КРИТИЧНА ПОМИЛКА парсингу .pb: {e}")
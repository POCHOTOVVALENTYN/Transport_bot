import requests
import zipfile
import io

# 1. Дані для запиту (з вашого повідомлення)
# Зверніть увагу: я використовую URL з вашого JSON-блоку ("od"), а не "od-all"
API_KEY = "a8c6d35e-f2c1-4f72-b902-831fa9215009"
STATIC_URL = "https://gw.x24.digital/api/od/gtfs/v1/download/static"

headers = {
    'ApiKey': API_KEY
}

print(f"🚀 Завантажую GTFS Static ZIP-архів з {STATIC_URL}...")

try:
    # 2. Робимо запит із правильним заголовком
    response = requests.get(STATIC_URL, headers=headers)

    # 3. Перевіряємо, чи успішний запит (200 OK)
    if response.status_code == 200:
        print("✅ ZIP-архів успішно завантажено.")

        # 4. Розпаковуємо ZIP-архів "в пам'яті"
        zip_file = zipfile.ZipFile(io.BytesIO(response.content))

        # 5. Друкуємо список всіх файлів всередині
        print("\n--- Вміст архіву: ---")
        zip_file.printdir()

        # (Опціонально) Розпакувати на диск, щоб подивитись
        zip_file.extractall("gtfs_static_data")
        print(f"\n✅ Файли розпаковано у папку 'gtfs_static_data'.")

    else:
        print(f"❌ ПОМИЛКА: Не вдалося завантажити. Статус: {response.status_code}")
        print(f"Тіло відповіді: {response.text}")

except Exception as e:
    print(f"❌ КРИТИЧНА ПОМИЛКА: {e}")
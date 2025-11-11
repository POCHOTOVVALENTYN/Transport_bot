import re
from utils.logger import logger
from integrations.google_sheets.client import GoogleSheetsClient
from config.settings import GOOGLE_SHEETS_ID

# !!! ВАЖЛИВО: Вкажіть точну назву вашого аркуша (таблиці)
STOPS_SHEET_NAME = "StopsDB"  # <--- Або інша назва, яку ви дали аркушу
STOPS_SHEET_RANGE = f"{STOPS_SHEET_NAME}!A:G"  # 7 стовпців: A, B, C, D, E, F, G


def _generate_key(text: str) -> str:
    """
    Створює чистий ключ з назви, напр.
    "Трамвай №5" -> "tramvay_5"
    "В бік Автовокзалу" -> "v_bik_avtovokzalu"
    """
    # Проста транслітерація
    translit_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'ґ': 'g', 'д': 'd', 'е': 'e',
        'є': 'ie', 'ж': 'zh', 'з': 'z', 'и': 'y', 'і': 'i', 'ї': 'i', 'й': 'y',
        'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
        'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch',
        'ш': 'sh', 'щ': 'shch', 'ь': '', 'ю': 'iu', 'я': 'ia', ' ': '_'
    }

    # Видаляємо все, що не є літерою, цифрою або пробілом
    cleaned_text = re.sub(r"[^а-яєїіґ0-9 ]", "", text.lower())

    key = "".join(translit_map.get(char, char) for char in cleaned_text)
    # Замінюємо декілька підкреслень одним
    key = re.sub(r"_+", "_", key)
    return key.strip("_")


def load_stops_cache() -> dict:
    """
    Завантажує дані зупинок з Google Sheets та конвертує їх у
    структурований dict (кеш) для швидкого доступу.

    ОЧІКУЄ ПОРЯДОК СТОВПЦІВ:
    A (0): stop_name_ua
    B (1): stop_name_en
    C (2): lat
    D (3): lon
    E (4): route_name
    F (5): direction_name
    G (6): stop_order
    """
    logger.info(f"🔄 Завантаження кешу зупинок з Google Sheets (Аркуш: {STOPS_SHEET_NAME})...")

    cache = {
        "routes": {}
    }

    try:
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        values = sheets.read_range(sheet_range=STOPS_SHEET_RANGE)

        if not values or len(values) < 2:
            logger.error(
                f"❌ Помилка завантаження кешу: Аркуш '{STOPS_SHEET_NAME}' порожній або містить лише заголовок.")
            return cache

        # Пропускаємо перший рядок (заголовки)
        for i, row in enumerate(values[1:], start=2):  # start=2 для логування номера рядка

            if len(row) < 7:
                logger.warning(f"Пропущено неповний рядок #{i} у Google Sheets: {row}")
                continue

            try:
                # --- ВАШ НОВИЙ ПОРЯДОК СТОВПЦІВ ---
                stop_name_ua = row[0].strip()
                stop_name_en = row[1].strip()
                lat = float(row[2].replace(',', '.'))
                lon = float(row[3].replace(',', '.'))
                route_name = row[4].strip()
                direction_name = row[5].strip()
                stop_order = int(row[6])
                # -----------------------------------

                # 2. Генеруємо ключі для нашого dict
                route_key = _generate_key(route_name)
                direction_key = _generate_key(direction_name)

                route_type = "tram" if "трамвай" in route_name.lower() else "trolleybus"

                # 3. Будуємо вкладену структуру
                if route_key not in cache["routes"]:
                    cache["routes"][route_key] = {
                        "name": route_name,
                        "type": route_type,
                        "directions": {}
                    }

                if direction_key not in cache["routes"][route_key]["directions"]:
                    cache["routes"][route_key]["directions"][direction_key] = {
                        "name": direction_name,
                        "stops": []  # Це буде список зупинок
                    }

                # 4. Створюємо об'єкт зупинки
                stop_data = {
                    "order": stop_order,
                    "name_ua": stop_name_ua,
                    "name_en": stop_name_en,
                    "lat": lat,
                    "lon": lon
                }

                # 5. Додаємо зупинку в її напрямок
                # ВАЖЛИВО: Ваш Google Sheet має бути відсортований
                # за route_name, direction_name, а потім stop_order
                cache["routes"][route_key]["directions"][direction_key]["stops"].append(stop_data)

            except ValueError as e:
                logger.warning(f"Помилка конвертації даних у рядку #{i} (не число?): {row}. Помилка: {e}")
            except Exception as e:
                logger.warning(f"Невідома помилка обробки рядка #{i}: {row}. Помилка: {e}")

        logger.info(f"✅ Кеш зупинок успішно завантажено. Маршрути: {list(cache['routes'].keys())}")
        return cache

    except Exception as e:
        logger.error(f"❌ КРИТИЧНА ПОМИЛКА завантаження кешу зупинок: {e}")
        return cache  # Повертаємо порожній кеш, щоб бот не впав
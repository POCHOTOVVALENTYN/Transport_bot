# handlers/accessible_transport_handlers.py
import logging
import math
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, \
    ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from bot.states import States
from handlers.command_handlers import get_main_menu_keyboard
from handlers.menu_handlers import main_menu
from config.settings import ROUTES, GTFS_API_KEY
from telegram.constants import ChatAction
# --- НОВІ ІМПОРТИ ---
from services.gtfs_cache_service import gtfs_cache
from google.transit import gtfs_realtime_pb2

# ---

logger = logging.getLogger(__name__)

# --- URL-и та заголовки для API ---
REALTIME_URL = "https://gw.x24.digital/api/od/gtfs/v1/download/gtfs-rt-vehicles-pr.pb"
API_HEADERS = {'ApiKey': GTFS_API_KEY}


# === ДОПОМІЖНІ ФУНКЦІЇ ===

def haversine(lat1, lon1, lat2, lon2):
    """Розрахунок відстані між двома точками на сфері (в кілометрах)"""
    R = 6371.0  # Радіус Землі в км

    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def get_realtime_vehicles():
    """
    Робить запит до GTFS Realtime API та повертає дані.
    Повертає FeedMessage або None у разі помилки.
    """
    try:
        response = requests.get(REALTIME_URL, headers=API_HEADERS, timeout=5)
        if response.status_code != 200:
            logger.error(f"❌ Помилка API GTFS Realtime: Статус {response.status_code}")
            return None

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(response.content)
        return feed
    except Exception as e:
        logger.error(f"❌ Помилка парсингу GTFS Realtime: {e}", exc_info=True)
        return None


def get_accessible_vehicles_on_route(feed, route_id, direction_headsign):
    """
    Фільтрує потік Realtime, повертаючи СЛОВНИК доступних ТЗ на КОНКРЕТНОМУ маршруті.
    Повертає: {trip_id: (vehicle_id, current_stop_sequence)}
    """
    accessible_vehicles = {}
    accessible_map = gtfs_cache.accessibility_map  # Наш JSON {vehicle_id: true/false}

    if not feed:
        return {}

    for entity in feed.entity:
        if not entity.HasField('vehicle'):
            continue

        vehicle = entity.vehicle
        vehicle_id = vehicle.vehicle.id
        trip_id = vehicle.trip.trip_id

        # 1. Перевірка на інклюзивність (ПЛАН D)
        if not accessible_map.get(vehicle_id, False):
            continue  # Цей ТЗ не в нашому реєстрі

        # 2. Перевірка, чи цей ТЗ на нашому маршруті
        try:
            trip_info = gtfs_cache.trips.get(trip_id)
            if not trip_info:
                continue  # Немає інформації про цю поїздку в кеші

            # 3. Перевірка маршруту ТА напрямку
            if (trip_info['route_id'] == route_id and
                    trip_info['headsign'] == direction_headsign):
                accessible_vehicles[trip_id] = (vehicle_id, vehicle.current_stop_sequence)

        except Exception as e:
            logger.warning(f"Помилка обробки trip_id {trip_id} з Realtime: {e}")

    return accessible_vehicles


# === КРОК 1: Початок -> Вибір Типу ===

async def accessible_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок діалогу: просить обрати тип транспорту (Трамвай/Тролейбус)."""
    query = update.callback_query
    # await query.answer() # Прибрано, щоб уникнути подвійної відповіді

    keyboard = [
        [
            InlineKeyboardButton("🚊 Трамваї", callback_data="acc_type:TRAM"),
            InlineKeyboardButton("🚎 Тролейбус", callback_data="acc_type:TROLLEY")
        ],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text="♿ Пошук інклюзивного транспорту.\n\nБудь ласка, оберіть тип транспорту:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.ACCESSIBLE_CHOOSE_ROUTE


# === КРОК 2: Вибір Маршруту ===

async def accessible_show_routes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Крок 2: Показує список маршрутів для обраного типу."""
    query = update.callback_query
    # await query.answer() # Прибрано

    transport_type = query.data.split(":")[-1]  # "TRAM" або "TROLLEY"
    keyboard = []

    if transport_type == "TRAM":
        context.user_data['accessible_type_name'] = "Трамвай"
        gtfs_type = '2'  # GTFS route_type для трамваїв
        buttons = [InlineKeyboardButton(f"Трамвай {r}", callback_data=f"acc_route:{gtfs_type}:{r}") for r in
                   ROUTES["tram"]]
    else:
        context.user_data['accessible_type_name'] = "Тролейбус"
        gtfs_type = '3'  # GTFS route_type для тролейбусів
        buttons = [InlineKeyboardButton(f"Тролейбус {r}", callback_data=f"acc_route:{gtfs_type}:{r}") for r in
                   ROUTES["trolleybus"]]

    keyboard.extend([buttons[i:i + 3] for i in range(0, len(buttons), 3)])
    keyboard.append([InlineKeyboardButton("⬅️ Назад (до типів)", callback_data="accessible_start")])
    keyboard.append([InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")])

    await query.edit_message_text(
        text=f"Ви обрали: <b>{context.user_data['accessible_type_name']}</b>.\n\nТепер оберіть номер маршруту:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return States.ACCESSIBLE_CHOOSE_DIRECTION


# === КРОК 3: Вибір Напрямку (РЕАЛІЗОВАНО) ===

async def accessible_choose_direction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Крок 3: Просить обрати напрямок. (Бере дані з gtfs_cache)."""
    query = update.callback_query
    # await query.answer() # Прибрано

    gtfs_type, route_num = query.data.split(":")[1:]
    route_name = f"Трамвай {route_num}" if gtfs_type == '2' else f"Тролейбус {route_num}"

    context.user_data['accessible_route_name'] = route_name
    context.user_data['accessible_route_num'] = route_num

    # --- ЛОГІКА API ---
    # 1. Знайти route_id в кеші
    route_id = None
    for r_id, r_data in gtfs_cache.routes.items():
        if r_data['name'] == route_num and r_data['type'] == gtfs_type:
            route_id = r_id
            break

    if not route_id:
        await query.edit_message_text(
            f"❌ Вибачте, сталася помилка. Не можу знайти {route_name} в GTFS-кеші.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")]])
        )
        return States.ACCESSIBLE_CHOOSE_DIRECTION

    context.user_data['accessible_route_id'] = route_id

    # 2. Знайти всі унікальні напрямки (headsigns) для цього route_id
    directions = set()
    for trip_data in gtfs_cache.trips.values():
        if trip_data['route_id'] == route_id and trip_data['headsign']:
            directions.add(trip_data['headsign'])

    if not directions:
        await query.edit_message_text(
            f"❌ Вибачте, сталася помилка. Не можу знайти напрямки руху для {route_name}.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")]])
        )
        return States.ACCESSIBLE_CHOOSE_DIRECTION

    # 3. Створити кнопки
    keyboard = []
    for headsign in directions:
        keyboard.append([InlineKeyboardButton(f"➡️ {headsign}", callback_data=f"acc_dir:{headsign}")])

    type_callback = "acc_type:TRAM" if gtfs_type == '2' else "acc_type:TROLLEY"
    keyboard.append([InlineKeyboardButton("⬅️ Назад (до маршрутів)", callback_data=type_callback)])
    keyboard.append([InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")])

    await query.edit_message_text(
        text=f"Ви обрали: <b>{route_name}</b>.\n\nТепер оберіть напрямок руху:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return States.ACCESSIBLE_CHOOSE_STOP_METHOD


# === КРОК 4: Вибір Методу Пошуку Зупинки ===
# (Ця функція залишається без змін, вона коректна)
async def accessible_choose_stop_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # await query.answer() # Прибрано

    direction = query.data.split(":")[-1]
    context.user_data['accessible_direction'] = direction
    logger.info(f"User selected direction: {direction}")

    keyboard = [
        [InlineKeyboardButton("📍 Надати геолокацію (я на зупинці)", callback_data="acc_stop:geo")],
        [InlineKeyboardButton("🚏 Обрати зі списку (планую поїздку)", callback_data="acc_stop:list")],
    ]

    route_callback = f"acc_route:{gtfs_cache.routes[context.user_data['accessible_route_id']]['type']}:{context.user_data['accessible_route_num']}"

    keyboard.append([InlineKeyboardButton("⬅️ Назад (до напрямків)", callback_data=route_callback)])
    keyboard.append([InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")])

    await query.edit_message_text(
        text="Як знайти вашу зупинку?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.ACCESSIBLE_GET_LOCATION


# === КРОК 5 (Варіант А): Запит Геолокації ===
# (Ця функція залишається без змін, вона коректна)
async def accessible_request_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()

    location_keyboard = [[KeyboardButton("📍 Надати мою геолокацію", request_location=True)]]

    await query.message.reply_text(
        "Будь ласка, натисніть кнопку нижче (АЛЕ ПЕРЕД ЦИМ УВІМКНІТЬ БУДЬ ЛАСКА ФУНКЦІЮ (ОПЦІЮ) ГЕОЛОКАЦІЇ "
        "НА СМАРТФОНІ),\n щоб надати вашу геолокацію. Я знайду найближчу зупинку.",
        reply_markup=ReplyKeyboardMarkup(location_keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return States.ACCESSIBLE_GET_LOCATION


# === КРОК 5 (Варіант Б): Вибір зі Списку (РЕАЛІЗОВАНО) ===

async def accessible_choose_from_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Крок 5Б: Показує список зупинок з кешу (з пагінацією)."""
    query = update.callback_query
    # await query.answer() # Прибрано

    route_id = context.user_data['accessible_route_id']
    direction = context.user_data['accessible_direction']

    # 1. Знайти типову поїздку (trip_id) для цього маршруту і напрямку
    sample_trip_id = None
    for trip_id, trip_data in gtfs_cache.trips.items():
        if trip_data['route_id'] == route_id and trip_data['headsign'] == direction:
            sample_trip_id = trip_id
            break

    if not sample_trip_id:
        await query.edit_message_text(f"❌ Помилка: Не можу знайти поїздку для {direction}.")
        return States.ACCESSIBLE_CHOOSE_STOP_METHOD

    # 2. Отримати список ID зупинок для цієї поїздки
    stop_id_list = gtfs_cache.stop_times.get(sample_trip_id)
    if not stop_id_list:
        await query.edit_message_text(f"❌ Помилка: Не можу знайти зупинки для {direction}.")
        return States.ACCESSIBLE_CHOOSE_STOP_METHOD

    # 3. Перетворити ID на імена
    stops_data = []  # Список кортежів (stop_id, stop_name, stop_sequence)
    for i, stop_id in enumerate(stop_id_list):
        stop_name = gtfs_cache.stops.get(stop_id, {}).get('name', f"Невідома зупинка {stop_id}")
        stops_data.append((stop_id, stop_name, i + 1))  # Зберігаємо послідовність (індекс + 1)

    context.user_data['route_stops_data'] = stops_data  # Зберігаємо повний список

    # 4. Пагінація
    page = 0
    if ":" in query.data:
        try:
            page = int(query.data.split(":")[-1])
        except ValueError:
            page = 0
    context.user_data['accessible_list_page'] = page

    STOPS_PER_PAGE = 10
    start_index = page * STOPS_PER_PAGE
    end_index = start_index + STOPS_PER_PAGE

    stops_to_show = stops_data[start_index:end_index]

    keyboard = []
    for stop_id, stop_name, stop_sequence in stops_to_show:
        # Зберігаємо stop_id ТА stop_sequence у callback_data
        keyboard.append([InlineKeyboardButton(stop_name, callback_data=f"acc_stop_select:{stop_id}:{stop_sequence}")])

    # Кнопки пагінації
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Туди", callback_data=f"acc_stop:list:{page - 1}"))
    if end_index < len(stops_data):
        nav_buttons.append(InlineKeyboardButton("Сюди ➡️", callback_data=f"acc_stop:list:{page + 1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("⬅️ Назад (Гео/Список)",
                                          callback_data=f"acc_dir:{context.user_data['accessible_direction']}")])
    keyboard.append([InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")])

    await query.edit_message_text(
        text=f"🚏 Оберіть вашу зупинку (стор. {page + 1}):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.ACCESSIBLE_CHOOSE_FROM_LIST


# === КРОК 6: Обробка результату (РЕАЛІЗОВАНО) ===

async def accessible_process_stub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Крок 6: Знаходить найближчий транспорт.
    """
    target_stop_id = None
    target_stop_name = None
    target_stop_sequence = None

    route_id = context.user_data['accessible_route_id']
    direction = context.user_data['accessible_direction']
    route_name = context.user_data['accessible_route_name']

    if update.message and update.message.location:
        await update.message.reply_text(
            "Дякую! Оброблюю ваші геодані та шукаю найближчу зупинку...",
            reply_markup=ReplyKeyboardRemove()
        )
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.FIND_LOCATION)

        user_lat = update.message.location.latitude
        user_lon = update.message.location.longitude

        # 1. Отримати список зупинок (як у Кроці 5Б)
        if not context.user_data.get('route_stops_data'):
            # (Користувач ніколи не натискав "Список", тому кешу немає - створюємо його)
            sample_trip_id = None
            for trip_id, trip_data in gtfs_cache.trips.items():
                if trip_data['route_id'] == route_id and trip_data['headsign'] == direction:
                    sample_trip_id = trip_id
                    break
            if not sample_trip_id:
                await update.message.reply_text(f"❌ Помилка: Не можу знайти поїздку для {direction}.")
                return States.ACCESSIBLE_CHOOSE_STOP_METHOD

            stop_id_list = gtfs_cache.stop_times.get(sample_trip_id)
            stops_data = []
            for i, stop_id in enumerate(stop_id_list):
                stop_info = gtfs_cache.stops.get(stop_id)
                if stop_info:
                    stops_data.append((stop_id, stop_info['name'], i + 1, stop_info['lat'], stop_info['lon']))
            context.user_data['route_stops_data'] = stops_data

        # 2. Знайти найближчу зупинку
        min_dist = float('inf')
        closest_stop = None
        for stop_data in context.user_data['route_stops_data']:
            stop_id, stop_name, stop_seq, stop_lat, stop_lon = stop_data
            dist = haversine(user_lat, user_lon, stop_lat, stop_lon)
            if dist < min_dist:
                min_dist = dist
                closest_stop = (stop_id, stop_name, stop_seq)

        if not closest_stop or min_dist > 1.0:  # (1 км - максимальна відстань)
            await update.message.reply_text("❌ Вибачте, я не можу знайти зупинку вашого маршруту поруч з вами.")
            return States.ACCESSIBLE_CHOOSE_STOP_METHOD

        target_stop_id, target_stop_name, target_stop_sequence = closest_stop
        logger.info(f"Знайдено найближчу зупинку по гео: {target_stop_name} (dist: {min_dist} km)")

    elif update.callback_query:
        await update.callback_query.answer()
        try:
            target_stop_id, target_stop_sequence = update.callback_query.data.split(":")[1:]
            target_stop_sequence = int(target_stop_sequence)
        except ValueError:
            await update.callback_query.edit_message_text("❌ Помилка вибору зупинки. Спробуйте ще раз.")
            return States.ACCESSIBLE_CHOOSE_FROM_LIST

        target_stop_name = gtfs_cache.stops.get(target_stop_id, {}).get('name', target_stop_id)

        await update.callback_query.edit_message_text(
            text=f"Дякую! Шукаю інклюзивний транспорт до зупинки:\n<b>{target_stop_name}</b>..."
        )
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    else:
        # Невідомий випадок
        return ConversationHandler.END

    # --- ГОЛОВНА ЛОГІКА API ---

    # 1. Отримуємо Realtime дані
    feed = get_realtime_vehicles()
    if not feed:
        await context.bot.send_message(update.effective_chat.id,
                                       "❌ Не вдалося завантажити дані Realtime. Спробуйте пізніше.")
        return ConversationHandler.END

    # 2. Фільтруємо ТІЛЬКИ доступні ТЗ на НАШОМУ маршруті/напрямку
    accessible_vehicles_on_route = get_accessible_vehicles_on_route(feed, route_id, direction)

    if not accessible_vehicles_on_route:
        text = (f"😢 На жаль, зараз на маршруті <b>{route_name}</b> (напрямок: {direction}) "
                f"немає жодного інклюзивного транспорту на лінії.")
        await context.bot.send_message(update.effective_chat.id, text, parse_mode="HTML")
        return ConversationHandler.END

    # 3. Знаходимо найближчий (той, що ПЕРЕД нами)
    best_vehicle_id = None
    min_stop_diff = float('inf')  # Мінімальна різниця зупинок

    for trip_id, (vehicle_id, current_stop_seq) in accessible_vehicles_on_route.items():
        # current_stop_seq - це індекс *наступної* зупинки, до якої їде ТЗ

        # Нам потрібен ТЗ, який ще не проїхав нашу зупинку
        if current_stop_seq <= target_stop_sequence:
            stop_diff = target_stop_sequence - current_stop_seq
            if stop_diff < min_stop_diff:
                min_stop_diff = stop_diff
                best_vehicle_id = vehicle_id

    # 4. Формуємо відповідь
    if best_vehicle_id:
        text = (
            f"✅ <b>Запит виконано!</b>\n\n"
            f"<b>Маршрут:</b> {route_name}\n"
            f"<b>Зупинка:</b> {target_stop_name}\n\n"
            f"Найближчий низькопідлоговий транспорт (борт <b>№{best_vehicle_id}</b>) вже в дорозі до вас.\n"
            f"Йому залишилось приблизно <b>{min_stop_diff}</b> зуп."
        )
        # (Тут можна додати логіку Job Queue, але вона залежить від ETA,
        # якого ми поки не маємо, тому кнопку "Повідомити" тимчасово прибираємо)
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
    else:
        text = (
            f"✅ <b>Запит виконано!</b>\n\n"
            f"<b>Маршрут:</b> {route_name}\n"
            f"<b>Зупинка:</b> {target_stop_name}\n\n"
            f"На жаль, всі інклюзивні ТЗ (<b>{len(accessible_vehicles_on_route)} од.</b>) "
            f"на цьому маршруті вже проїхали вашу зупинку."
        )
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]

    await context.bot.send_message(
        update.effective_chat.id,
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

    context.user_data.clear()
    return ConversationHandler.END


# === КРОК 7: "Повідомити" (ВИДАЛЕНО) ===
# Ми прибрали кнопку "Повідомити", оскільки без ETA (яке API не надає)
# ця функція не може працювати коректно.
# Функції accessible_notify_me_stub та стан ACCESSIBLE_AWAIT_NOTIFY
# більше не використовуються і будуть видалені з ConversationHandler.


# === Скасування діалогу ===
# (Залишається без змін, коректний)
async def accessible_text_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Діалог пошуку скасовано.", reply_markup=ReplyKeyboardRemove())
    keyboard = await get_main_menu_keyboard(update.effective_user.id)
    await update.message.reply_text(
        "🚊 Оберіть потрібну опцію:",
        reply_markup=keyboard
    )
    context.user_data.clear()
    return ConversationHandler.END
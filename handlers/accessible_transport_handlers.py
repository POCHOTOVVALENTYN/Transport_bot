from utils.logger import logger
import re  # <--- ДОДАЙТЕ ЦЕЙ РЯДОК
import math # <--- ДОДАЙТЕ ЦЕЙ РЯДОК
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, \
    ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, Application
from bot.states import States
from handlers.command_handlers import get_main_menu_keyboard
from handlers.menu_handlers import main_menu
#from config.settings import ROUTES  # Використовуємо ваші маршрути
from telegram.constants import ChatAction
# --- НАШІ НОВІ ІМПОРТИ ---
from services.easyway_service import easyway_service
import asyncio  # Для Job Queue



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


# --- КІНЕЦЬ ДОДАВАННЯ ---


# === КРОК 0: Завантаження та кешування ID маршрутів ===
# Ми зробимо це один раз при старті (в bot/bot.py),
# щоб зіставити "Трамвай 5" з його EasyWay ID
async def load_easyway_route_ids(application: Application):
    logger.info("Завантажую EasyWay Route ID...")
    data = await easyway_service.get_routes_list()
    if data.get("error"):
        logger.error(f"Не вдалося завантажити EasyWay Route IDs: {data['error']}")
        # 2. Використовуємо 'application.bot_data'
        application.bot_data['easyway_structured_map'] = {"tram": [], "trolley": []}
        return False
    # --- 1. ВИПРАВЛЕННЯ КЛЮЧА СПИСКУ ---
    # API повертає {"routesList": {"route": [...]}}
    route_list_from_api = data.get("routesList", {}).get("route", [])
    # --- КІНЕЦЬ 1 ---

    if not route_list_from_api:
        logger.warning("EasyWay API: Запит успішний, але 'routesList'/'route' (список маршрутів) порожній.")
        application.bot_data['easyway_structured_map'] = {"tram": [], "trolley": []}  # Додано
        return False
    else:
        # Логуємо КЛЮЧІ, щоб побачити, чи є 'transportKey'
        logger.info(f"EasyWay API: Отримано {len(route_list_from_api)} маршрутів. Ключі першого маршруту:")
        try:
            logger.info(f"[Маршрут 1 Kлючі]: {route_list_from_api[0].keys()}")
        except Exception as e:
            logger.warning(f"Не вдалося залогувати ключі: {e}")

    structured_route_map = {"tram": [], "trolley": []}

    # Використовуємо нову змінну
    for route in route_list_from_api:
        route_key = route.get("transport")
        route_id = route.get("id")
        # --- 2. ВИПРАВЛЕННЯ КЛЮЧА НАЗВИ ---
        # API повертає "title", а не "name"
        route_name = route.get("title")
        # --- КІНЕЦЬ 2 ---

        if route_name and "Фунікулер" in route_name:
            logger.info(f"Пропускаємо маршрут 'Фунікулер': {route}")
            continue  # Не додаємо його до списку
        # --- КІНЕЦЬ ВИДАЛЕННЯ ФУНІКУЛЕРА ---

        if not route_id or not route_name or not route_key:
            # --- ПОКРАЩЕННЯ (ЛОГУВАННЯ) ---
            logger.warning(f"Пропускаємо маршрут з неповними даними (id, title або transportKey): {route}")
            # --- КІНЕЦЬ ПОКРАЩЕННЯ ---
            continue
        # --- 3. ПОКРАЩЕННЯ: Очищуємо назву ---
        # "1(\u042e\u0436\u043d\u0435)" (1(Южне)) -> "1"
        if "(" in route_name:
            route_name = route_name.split("(")[0].strip()
        # --- КІНЕЦЬ 3 ---

        if route_key == "tram":
            structured_route_map["tram"].append({"id": route_id, "name": route_name})
        elif route_key == "trol":
            structured_route_map["trolley"].append({"id": route_id, "name": route_name})

    try:
        structured_route_map["tram"].sort(key=lambda x: int(re.sub(r'\D', '', x['name']) or '0'))
        structured_route_map["trolley"].sort(key=lambda x: int(re.sub(r'\D', '', x['name']) or '0'))
    except Exception as e:
        logger.warning(f"Не вдалося відсортувати списки маршрутів: {e}")
        pass

        # --- ПОЧАТОК ПОКРАЩЕННЯ (ЛОГУВАННЯ) ---
        if not structured_route_map["tram"] and not structured_route_map["trolley"]:
            logger.warning("Парсинг EasyWay: Не знайдено ЖОДНОГО маршруту 'tram' або 'trol'.")
            logger.warning("Перевірте, чи ключ 'transportKey' та значення 'trol' актуальні.")
        # --- КІНЕЦЬ ПОКРАЩЕННЯ ---

    # 3. Використовуємо 'application.bot_data'
    application.bot_data['easyway_structured_map'] = structured_route_map
    logger.info(f"✅ EasyWay Route ID завантажено. {len(structured_route_map['tram'])} трамваїв, {len(structured_route_map['trolley'])} тролейбусів.")
# --- КІНЕЦЬ ВИПРАВЛЕННЯ ---


# === КРОК 1: Початок -> Вибір Типу (Без змін) ===
async def accessible_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок діалогу: просить обрати тип транспорту (Трамвай/Тролейбус)."""
    query = update.callback_query
    await query.answer()

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
    keyboard = [
        [
            InlineKeyboardButton("🚊 Трамваї", callback_data="acc_type:tram"),
            # Використовуємо ключ "trolley"
            InlineKeyboardButton("🚎 Тролейбус", callback_data="acc_type:trolley")
        ],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")]
    ]
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    await query.edit_message_text(
        text="♿ Пошук інклюзивного транспорту.\n\nБудь ласка, оберіть тип транспорту:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.ACCESSIBLE_CHOOSE_ROUTE


# === КРОК 2: Вибір Маршруту (Майже без змін) ===
# handlers/accessible_transport_handlers.py

async def accessible_show_routes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Крок 2: Показує список маршрутів для обраного типу."""
    query = update.callback_query
    await query.answer()

    transport_type = query.data.split(":")[-1]  # "tram" або "trolley"
    context.user_data['accessible_type'] = transport_type

    keyboard = []

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
    # 1. Отримуємо карту з правильним default
    structured_map = context.bot_data.get('easyway_structured_map', {"tram": [], "trolley": []})

    if transport_type == "tram":
        context.user_data['accessible_type_name'] = "Трамвай"
        route_list = structured_map.get("tram", [])
        buttons = [InlineKeyboardButton(f"Трамвай {r['name']}", callback_data=f"acc_route:{r['id']}:{r['name']}") for r
                   in route_list]
    # 2. Чітко перевіряємо "trolley"
    elif transport_type == "trolley":
        context.user_data['accessible_type_name'] = "Тролейбус"
        route_list = structured_map.get("trolley", [])  # <-- Отримуємо список "trolley"
        buttons = [InlineKeyboardButton(f"Тролейбус {r['name']}", callback_data=f"acc_route:{r['id']}:{r['name']}") for
                   r
                   in route_list]
    else:
        # Аварійний випадок
        route_list = []
        buttons = []

    if not route_list:
        # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---
        # (Цей блок тепер коректно спрацює, якщо API дійсно не повернуло дані)
        await query.edit_message_text(
            "❌ Помилка: не вдалося завантажити список маршрутів з EasyWay. Спробуйте пізніше.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")]])
        )
        return States.ACCESSIBLE_CHOOSE_ROUTE

    # Розбиваємо на рядки по 3-4 кнопки для зручності
    keyboard.extend([buttons[i:i + 3] for i in range(0, len(buttons), 3)])
    keyboard.append([InlineKeyboardButton("⬅️ Назад (до типів)", callback_data="accessible_start")])
    keyboard.append([InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")])

    await query.edit_message_text(
        text=f"Ви обрали: <b>{context.user_data['accessible_type_name']}</b>.\n\nТепер оберіть номер маршруту:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return States.ACCESSIBLE_CHOOSE_DIRECTION


# === КРОК 3: Вибір Напрямку (Повністю нове, з API) ===
async def accessible_choose_direction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
    # query.data тепер "acc_route:EASYWAY_ID:NUMBER" (напр. "acc_route:123:5")
    try:
        _, easyway_route_id, route_num = query.data.split(":")
    except ValueError:
        logger.error(f"Неправильний callback_data у accessible_choose_direction: {query.data}")
        await query.edit_message_text("❌ Сталася внутрішня помилка. Спробуйте знову.")
        return States.ACCESSIBLE_CHOOSE_ROUTE

    transport_type = context.user_data['accessible_type']  # "tram"

    context.user_data['accessible_route_name'] = f"{context.user_data['accessible_type_name']} {route_num}"
    context.user_data['accessible_route_num'] = route_num  # "5"
    context.user_data['easyway_route_id'] = easyway_route_id  # <-- ЗБЕРІГАЄМО ID

    # --- ЛОГІКА API ---
    # 1. ID вже отримано!
    logger.info(f"User selected route_id: {easyway_route_id}, name: {route_num}")
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---


    # 2. Отримати інформацію про маршрут (напрямки та зупинки)
    route_info = await easyway_service.get_route_info(easyway_route_id)
    if route_info.get("error"):
        await query.edit_message_text(
            f"❌ Помилка API EasyWay: {route_info['error']}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")]])
        )
        return States.ACCESSIBLE_CHOOSE_DIRECTION

    # handlers/accessible_transport_handlers.py (НОВА ВЕРСІЯ)

    # 3. Отримати ГОЛОВНИЙ ОБ'ЄКТ 'route' з відповіді
    route_data = route_info.get("route")

    # 3a. Додамо перевірку, що об'єкт 'route' взагалі існує
    if not route_data:
        await query.edit_message_text(f"❌ Помилка API: відповідь не містить очікуваного об'єкту 'route'.",
                                       reply_markup=InlineKeyboardMarkup(
                                           [[InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")]]))
        return States.ACCESSIBLE_CHOOSE_DIRECTION

    # 3b. Зберігаємо в кеш ТІЛЬКИ 'route_data', а не всю відповідь
    context.user_data['easyway_route_info'] = route_data

    # 4. Створити кнопки напрямків (тепер шукаємо в 'route_data')
    keyboard = []
    directions = route_data.get("directions", [])  # <-- ВИПРАВЛЕНО
    if not directions:
        await query.edit_message_text(
            f"❌ Не знайдено напрямків для {context.user_data['accessible_route_name']}.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")]])
        )
        return States.ACCESSIBLE_CHOOSE_DIRECTION

    for direction in directions:
        # direction['id'] = "A", "B" (умовні)
        # direction['name'] = "В бік Аркадії"
        keyboard.append([InlineKeyboardButton(f"➡️ {direction['name']}", callback_data=f"acc_dir:{direction['id']}")])

    type_callback = f"acc_type:{transport_type}"
    keyboard.append([InlineKeyboardButton("⬅️ Назад (до маршрутів)", callback_data=type_callback)])
    keyboard.append([InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")])

    await query.edit_message_text(
        text=f"Ви обрали: <b>{context.user_data['accessible_route_name']}</b>.\n\nТепер оберіть напрямок руху:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return States.ACCESSIBLE_CHOOSE_STOP_METHOD


# === КРОК 4: Вибір Методу Пошуку Зупинки (Без змін) ===
async def accessible_choose_stop_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    direction_id = query.data.split(":")[-1]  # "A" або "B"
    context.user_data['accessible_direction_id'] = direction_id
    logger.info(f"User selected direction_id: {direction_id}")

    keyboard = [
        [InlineKeyboardButton("📍 Надати геолокацію (я на зупинці)", callback_data="acc_stop:geo")],
        [InlineKeyboardButton("🚏 Обрати зі списку (планую поїздку)", callback_data="acc_stop:list")],
    ]

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
    route_num = context.user_data['accessible_route_num']
    easyway_route_id = context.user_data['easyway_route_id']  # Отримуємо ID
    # Створюємо callback "acc_route:123:5"
    route_callback = f"acc_route:{easyway_route_id}:{route_num}"
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    keyboard.append([InlineKeyboardButton("⬅️ Назад (до напрямків)", callback_data=route_callback)])
    keyboard.append([InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")])

    await query.edit_message_text(
        text="Як знайти вашу зупинку?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.ACCESSIBLE_GET_LOCATION


# === КРОК 5 (Варіант А): Запит Геолокації (Без змін) ===
async def accessible_request_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    location_keyboard = [[KeyboardButton("📍 Надати мою геолокацію", request_location=True)]]
    await query.message.reply_text(
        "Будь ласка, натисніть кнопку нижче, щоб надати вашу геолокацію. Я знайду найближчу зупинку.",
        reply_markup=ReplyKeyboardMarkup(location_keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return States.ACCESSIBLE_GET_LOCATION


# === КРОК 5 (Варіант Б): Вибір зі Списку (Повністю нове, з API) ===
async def accessible_choose_from_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Крок 5Б: Показує список зупинок з API (з пагінацією)."""
    query = update.callback_query
    await query.answer()

    direction_id = context.user_data['accessible_direction_id']  # "A"
    route_info = context.user_data['easyway_route_info']  # {..., "directions": [...], "stops": [...]}

    # 1. Знайти наш напрямок в даних
    stops_for_direction = []
    for direction in route_info.get("directions", []):
        if direction['id'] == direction_id:
            stops_for_direction = direction.get("stops", [])  # [stop_id_1, stop_id_2, ...]
            break

    if not stops_for_direction:
        await query.edit_message_text(f"❌ Помилка: Не можу знайти зупинки для цього напрямку.")
        return States.ACCESSIBLE_CHOOSE_STOP_METHOD

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
    # 2. Перетворити ID на повні об'єкти (включно з lat/lon)
    all_stops_full_map = {stop['id']: stop for stop in route_info.get("stops", [])}

    stops_data = []  # Список (stop_id, stop_name, lat, lon)
    for stop_id in stops_for_direction:
        stop_obj = all_stops_full_map.get(stop_id)
        if stop_obj:
            stops_data.append((stop_obj['id'], stop_obj['name'], stop_obj['lat'], stop_obj['lon']))

    context.user_data['route_stops_data'] = stops_data  # Зберігаємо повний список
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    # 3. Пагінація
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

    # stops_to_show тепер (stop_id, stop_name, lat, lon)
    stops_to_show = stops_data[start_index:end_index]

    keyboard = []
    for stop_id, stop_name, _, _ in stops_to_show:  # Ігноруємо lat/lon при побудові кнопок
        keyboard.append([InlineKeyboardButton(stop_name, callback_data=f"acc_stop_select:{stop_id}")])

    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton("⬅️ Туди", callback_data=f"acc_stop:list:{page - 1}"))
    if end_index < len(stops_data): nav_buttons.append(
        InlineKeyboardButton("Сюди ➡️", callback_data=f"acc_stop:list:{page + 1}"))
    if nav_buttons: keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("⬅️ Назад (Гео/Список)", callback_data=f"acc_dir:{direction_id}")])
    keyboard.append([InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")])

    await query.edit_message_text(
        text=f"🚏 Оберіть вашу зупинку (стор. {page + 1}):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.ACCESSIBLE_CHOOSE_FROM_LIST

# === КРОК 6: Обробка результату (Повністю нове, з API) ===

async def accessible_process_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, stop_id: str, stop_name: str):
    """Загальна логіка обробки, викликається з Гео та Списку."""

    route_name = context.user_data['accessible_route_name']  # "Трамвай 5"
    chat_id = update.effective_chat.id

    # 1. Отримуємо дані про прибуття
    data = await easyway_service.get_stop_arrivals(stop_id)
    if data.get("error"):
        await context.bot.send_message(chat_id, f"❌ Помилка API EasyWay: {data['error']}")
        return ConversationHandler.END

    # 2. Фільтруємо транспорт
    accessible_arrivals = []
    route_num = context.user_data['accessible_route_num']  # "5"

    for transport in data.get("transport", []):
        # transport['route_name'] = "5"
        # transport['handicapped'] = true/false
        # transport['time'] = "5" (хвилини)
        # transport['timeSource'] = "gps"
        # transport['bort'] = "4015"

        if (str(transport.get("route_name")) == str(route_num) and
                transport.get("handicapped") is True):
            accessible_arrivals.append(transport)

    # 3. Формуємо відповідь
    if not accessible_arrivals:
        text = (f"😢 На жаль, на зупинці <b>{stop_name}</b>\n"
                f"для маршруту <b>{route_name}</b>\n"
                f"зараз <b>немає</b> інклюзивного транспорту на під'їзді.")
        keyboard = [[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
    else:
        text = (f"✅ <b>Запит виконано!</b>\n\n"
                f"<b>Маршрут:</b> {route_name}\n"
                f"<b>Зупинка:</b> {stop_name}\n\n"
                f"<b>Очікується інклюзивний транспорт:</b>\n")

        keyboard = []

        for i, transport in enumerate(accessible_arrivals):
            bort = transport.get('bort', 'Б/Н')
            time_min = transport.get('time', 0)
            time_source = transport.get('timeSource', 'N/A')

            source_emoji = "🛰️ (GPS)" if time_source == "gps" else "📅 (Розклад)"

            text += f"▪️ Борт <b>№{bort}</b> - через <b>~{time_min} хв.</b> {source_emoji}\n"

            # --- ПОВЕРТАЄМО ПОКРАЩЕННЯ №1 (Job Queue) ---
            # Додаємо кнопку сповіщення, ТІЛЬКИ якщо час > 4 хв і це GPS
            if time_min > 4 and time_source == "gps" and i == 0:  # Тільки для першого
                context.user_data['notify_transport'] = transport  # Зберігаємо дані
                context.user_data['notify_stop_name'] = stop_name
                keyboard.append([InlineKeyboardButton(
                    f"🔔 Повідомити за 3 хв (борт №{bort})",
                    callback_data="acc_notify_me"
                )])

        keyboard.append([InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")])

    await context.bot.send_message(
        chat_id, text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    # Очищуємо дані, ОКРІМ 'notify_transport'
    notify_data = context.user_data.get('notify_transport')
    notify_stop = context.user_data.get('notify_stop_name')  #
    context.user_data.clear()
    if notify_data:
        context.user_data['notify_transport'] = notify_data  # Зберігаємо для job
        context.user_data['notify_stop_name'] = notify_stop  #

    return States.ACCESSIBLE_AWAIT_NOTIFY  # Переходимо до стану очікування "Повідомити"


async def accessible_process_stub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Крок 6: Визначає stop_id (з Гео або Списку)
    та передає управління в accessible_process_logic.
    """
    target_stop_id = None
    target_stop_name = None

    if update.message and update.message.location:
        await update.message.reply_text(
            "Дякую! Оброблюю ваші геодані та шукаю найближчу зупинку...",
            reply_markup=ReplyKeyboardRemove()
        )
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.FIND_LOCATION)

        user_lat = update.message.location.latitude
        user_lon = update.message.location.longitude

        # 1. Знайти зупинки поруч
        nearby_data = await easyway_service.get_stops_near_point(user_lat, user_lon)
        if nearby_data.get("error"):
            await update.message.reply_text(f"❌ Помилка API EasyWay: {nearby_data['error']}")
            return ConversationHandler.END

        nearby_stops = nearby_data.get("list", [])
        if not nearby_stops:
            await update.message.reply_text("❌ Поруч (в радіусі 500м) не знайдено жодної зупинки.")
            return ConversationHandler.END

        # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
        # 2. Знайти *НАЙБЛИЖЧУ* зупинку з тих, що *належать нашому маршруту*

        # 2a. Отримуємо список ID зупинок *нашого* маршруту
        route_stops_data = context.user_data.get('route_stops_data')

        # 2b. Якщо користувач не натискав "Список", кешу 'route_stops_data' немає.
        #    Нам потрібно його створити вручну.
        if not route_stops_data:
            logger.info("GEO: 'route_stops_data' not in cache. Fetching from 'easyway_route_info'.")
            route_info = context.user_data.get('easyway_route_info')
            direction_id = context.user_data.get('accessible_direction_id')

            if not route_info or not direction_id:
                await update.message.reply_text(
                    "❌ Критична помилка: дані про маршрут втрачено. Будь ласка, почніть знову.")
                return ConversationHandler.END

            # Відтворюємо логіку з `accessible_choose_from_list`
            stops_for_direction = []
            for direction in route_info.get("directions", []):
                if direction['id'] == direction_id:
                    stops_for_direction = direction.get("stops", [])
                    break

            # Нам потрібні координати, тому беремо їх з `route_info.stops`
            all_stops_full_map = {stop['id']: stop for stop in route_info.get("stops", [])}
            stops_data = []  # Список (stop_id, stop_name, lat, lon)

            for stop_id in stops_for_direction:
                stop_obj = all_stops_full_map.get(stop_id)
                if stop_obj:
                    # Додаємо координати, яких не було в гілці "Список"
                    stops_data.append((stop_obj['id'], stop_obj['name'], stop_obj['lat'], stop_obj['lon']))

            context.user_data['route_stops_data'] = stops_data  # Зберігаємо повний список

        # 2c. Тепер `route_stops_data` гарантовано існує. Шукаємо найближчу.
        our_stops_with_coords = context.user_data['route_stops_data']
        our_stop_ids = {stop[0] for stop in our_stops_with_coords}  # {stop_id_1, stop_id_2, ...}

        closest_stop = None  # (stop_id, stop_name)
        min_dist = float('inf')

        for stop in nearby_stops:  # (Зупинки, які поруч з користувачем)
            if stop['id'] in our_stop_ids:  # Якщо ця зупинка є на нашому маршруті
                # Ми не можемо просто взяти першу, бо API `GetStopsNearPoint`
                # повертає ВСІ зупинки в радіусі, а не тільки нашого маршруту.
                # Нам треба знайти найближчу саме *з нашого маршруту*.

                # Шукаємо координати цієї зупинки в нашому списку
                current_stop_data = next((s for s in our_stops_with_coords if s[0] == stop['id']), None)
                if not current_stop_data: continue  # Такого не має бути, але про всяк випадок

                dist = haversine(user_lat, user_lon, float(current_stop_data[2]), float(current_stop_data[3]))

                if dist < min_dist:
                    min_dist = dist
                    closest_stop = (current_stop_data[0], current_stop_data[1])

        if not closest_stop or min_dist > 1.0:  # (1 км - максимальна відстань)
            await update.message.reply_text(
                "❌ Вибачте, я не можу знайти зупинку вашого маршруту (в радіусі 1 км) поруч з вами.")
            return States.ACCESSIBLE_CHOOSE_STOP_METHOD

        target_stop_id, target_stop_name = closest_stop
        logger.info(f"Знайдено найближчу зупинку по гео: {target_stop_name} (dist: {min_dist:.2f} km)")
        # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    elif update.callback_query:
        await update.callback_query.answer()
        target_stop_id = update.callback_query.data.split(":")[-1]

        # Знайти ім'я зупинки в кеші
        for stop_id, stop_name in context.user_data.get('route_stops_data', []):
            if stop_id == target_stop_id:
                target_stop_name = stop_name
                break
        if not target_stop_name: target_stop_name = f"ID {target_stop_id}"

        await update.callback_query.edit_message_text(
            text=f"Дякую! Шукаю інклюзивний транспорт до зупинки:\n<b>{target_stop_name}</b>...",
            parse_mode="HTML"
        )
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    else:
        return ConversationHandler.END

    # Викликаємо головну логіку
    return await accessible_process_logic(update, context, target_stop_id, target_stop_name)


# === КРОК 7: Повідомлення (Покращення №1 - ПОВЕРНУЛОСЯ!) ===

async def notify_user_callback(context: ContextTypes.DEFAULT_TYPE):
    """
    Ця функція буде викликана через N хвилин.
    Вона надсилає фінальне сповіщення.
    """
    job = context.job
    chat_id = job.chat_id
    bort = job.data.get('bort', 'Б/Н')
    stop_name = job.data.get('stop_name', 'вашу зупинку')

    text = f"🔔 <b>НАГАДУВАННЯ!</b>\n\nІнклюзивний транспорт (борт <b>№{bort}</b>) " \
           f"буде на зупинці <b>{stop_name}</b> приблизно через <b>3 хвилини</b>. " \
           f"Будь ласка, готуйтеся!"

    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    logger.info(f"Job Queue: Надіслано сповіщення користувачу {chat_id} про борт {bort}")


async def accessible_notify_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """(Крок 7) Встановлює Job Queue для сповіщення."""
    query = update.callback_query
    await query.answer()

    transport_data = context.user_data.get('notify_transport')
    stop_name = context.user_data.get('notify_stop_name', 'ваша зупинка')

    if not transport_data:
        await query.edit_message_text("❌ Помилка: дані про транспорт втрачено. Не можу встановити сповіщення.")
        return ConversationHandler.END

    time_min = transport_data.get('time', 0)
    bort = transport_data.get('bort', 'Б/Н')


    # Нам потрібно зберегти stop_name в `accessible_process_logic`
    # (Але зараз це не критично)

    notify_delay_seconds = (time_min - 3) * 60

    if notify_delay_seconds < 1:
        await query.edit_message_text("🔔 Вже майже час! Не можу встановити сповіщення, борт прибуває.")
        return ConversationHandler.END

    try:
        # Створюємо завдання
        context.job_queue.run_once(
            notify_user_callback,
            when=notify_delay_seconds,
            data={
                "bort": bort,
                "stop_name": stop_name
            },
            chat_id=query.effective_chat.id,
            name=f"notify_{query.effective_chat.id}_{bort}"
        )

        logger.info(f"Job Queue: Завдання створено на {notify_delay_seconds} сек. для борта {bort}")

        await query.edit_message_text(
            f"✅ Добре!\nЯ надішлю сповіщення за 3 хвилини до прибуття (борт <b>№{bort}</b>).\n\n"
            f"<i>(Приблизно через {int(notify_delay_seconds / 60)} хв.)</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]])
        )

    except Exception as e:
        logger.error(f"Job Queue: Помилка створення завдання: {e}")
        await query.edit_message_text(f"❌ Не вдалося створити сповіщення: {e}")

    context.user_data.clear()
    return ConversationHandler.END


# === Скасування діалогу (Без змін) ===
async def accessible_text_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Діалог пошуку скасовано.", reply_markup=ReplyKeyboardRemove())
    keyboard = await get_main_menu_keyboard(update.effective_user.id)
    await update.message.reply_text(
        "🚊 Оберіть потрібну опцію:",
        reply_markup=keyboard
    )
    context.user_data.clear()
    return ConversationHandler.END
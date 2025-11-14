from handlers.menu_handlers import main_menu
from utils.logger import logger
import re
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, \
    ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler, Application
from bot.states import States
from handlers.command_handlers import get_main_menu_keyboard
from telegram.constants import ChatAction
from services.easyway_service import easyway_service
import asyncio


# --- Haversine (без змін) ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# === КРОК 0: Завантаження маршрутів (ПЕРЕПИСАНО для ПЛАНУ Е) ===
async def load_easyway_route_ids(application: Application) -> bool:
    logger.info("Завантажую EasyWay Route ID...")
    data = await easyway_service.get_routes_list()

    if data.get("error"):
        logger.error(f"Не вдалося завантажити EasyWay Route IDs: {data['error']}")
        application.bot_data['easyway_structured_map'] = {"tram": [], "trolley": []}
        return False

    structured_route_map = {"tram": [], "trolley": []}
    route_list_from_api = data.get("routesList", {}).get("route", [])
    if not route_list_from_api:
        logger.warning("EasyWay API: 'routesList'/'route' порожній.")
        return False

    for route in route_list_from_api:
        route_key = route.get("transport")
        route_id = route.get("id")
        route_name = route.get("title")
        start_pos = route.get("start_position") # <-- НОВЕ
        stop_pos = route.get("stop_position")   # <-- НОВЕ

        if route_name and "Фунікулер" in route_name:
            logger.info(f"Пропускаємо маршрут 'Фунікулер': {route}")
            continue

        if not all([route_id, route_name, route_key, start_pos, stop_pos]):
            logger.warning(f"Пропускаємо маршрут з неповними даними: {route}")
            continue

        if "(" in route_name:
            route_name = route_name.split("(")[0].strip()

        # Зберігаємо повний об'єкт
        route_obj = {
            "id": route_id,
            "name": route_name,
            "start_pos": start_pos,
            "stop_pos": stop_pos
        }

        if route_key == "tram":
            structured_route_map["tram"].append(route_obj)
        elif route_key == "trol":
            structured_route_map["trolley"].append(route_obj)

    try:
        structured_route_map["tram"].sort(key=lambda x: int(re.sub(r'\D', '', x['name']) or '0'))
        structured_route_map["trolley"].sort(key=lambda x: int(re.sub(r'\D', '', x['name']) or '0'))
    except Exception as e:
        logger.warning(f"Не вдалося відсортувати списки маршрутів: {e}")

    application.bot_data['easyway_structured_map'] = structured_route_map
    logger.info(
        f"✅ EasyWay Route ID завантажено. {len(structured_route_map['tram'])} трамваїв, {len(structured_route_map['trolley'])} тролейбусів.")
    return True


# === КРОК 1: Вибір Типу (Без змін) ===
async def accessible_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [
            InlineKeyboardButton("🚊 Трамваї", callback_data="acc_type:tram"),
            InlineKeyboardButton("🚎 Тролейбус", callback_data="acc_type:trolley")
        ],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")]
    ]
    await query.edit_message_text(
        text="♿ Пошук інклюзивного транспорту.\n\nОберіть тип транспорту:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.ACCESSIBLE_CHOOSE_ROUTE


# === КРОК 2: Вибір Маршруту (ПЕРЕПИСАНО) ===
async def accessible_show_routes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    transport_type = query.data.split(":")[-1]  # "tram" або "trolley"
    context.user_data['accessible_type'] = transport_type

    structured_map = context.bot_data.get('easyway_structured_map', {"tram": [], "trolley": []})

    if transport_type == "tram":
        context.user_data['accessible_type_name'] = "Трамвай"
        route_list = structured_map.get("tram", [])
        buttons = [InlineKeyboardButton(
            f"Трамвай {r['name']}",
            # Зберігаємо всю інфо про маршрут в callback
            callback_data=f"acc_route:{r['id']}:{r['name']}:{r['start_pos']}:{r['stop_pos']}"
        ) for r in route_list]

    elif transport_type == "trolley":
        context.user_data['accessible_type_name'] = "Тролейбус"
        route_list = structured_map.get("trolley", [])
        buttons = [InlineKeyboardButton(
            f"Тролейбус {r['name']}",
            callback_data=f"acc_route:{r['id']}:{r['name']}:{r['start_pos']}:{r['stop_pos']}"
        ) for r in route_list]
    else:
        route_list = []
        buttons = []

    if not route_list:
        await query.edit_message_text(
            "❌ Помилка: не вдалося завантажити список маршрутів. Спробуйте пізніше.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")]])
        )
        return States.ACCESSIBLE_CHOOSE_ROUTE

    keyboard = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    keyboard.append([InlineKeyboardButton("⬅️ Назад (до типів)", callback_data="accessible_start")])
    keyboard.append([InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")])

    await query.edit_message_text(
        text=f"Ви обрали: <b>{context.user_data['accessible_type_name']}</b>.\n\nТепер оберіть номер маршруту:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return States.ACCESSIBLE_CHOOSE_DIRECTION # <-- НОВИЙ СТАН


# === КРОК 3: Вибір Напрямку (НОВА ФУНКЦІЯ) ===
async def accessible_show_directions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # "acc_route:113:5:0:300" -> [id, name, start, stop]
    try:
        _, route_id, route_name, start_pos, stop_pos = query.data.split(":")
    except ValueError:
        await query.edit_message_text("❌ Помилка: Некоректні дані маршруту.")
        return ConversationHandler.END

    # Зберігаємо дані маршруту в context
    context.user_data['route_id'] = route_id
    context.user_data['route_name'] = f"{context.user_data['accessible_type_name']} {route_name}"
    context.user_data['route_start_pos'] = start_pos
    context.user_data['route_stop_pos'] = stop_pos

    await query.edit_message_text(f"🔄 Отримую напрямки для <b>{context.user_data['route_name']}</b>...", parse_mode="HTML")

    # Отримуємо деталі маршруту, щоб знайти назви напрямків
    route_info = await easyway_service.get_route_info(route_id)

    if route_info.get("error") or not route_info.get("routeinfo"):
        await query.edit_message_text(f"❌ Помилка API (GetRouteInfo): {route_info.get('error', 'no data')}")
        return States.ACCESSIBLE_CHOOSE_ROUTE

    # 'description' має формат "Напрямок А - Напрямок Б"
    description = route_info.get("routeinfo", {}).get("shortDescription", "")
    directions = description.split(" - ")

    if len(directions) < 2:
        # Якщо API не повернуло напрямки, використовуємо стандартні
        directions = ["Прямий напрямок", "Зворотній напрямок"]

    context.user_data['dir_1_name'] = directions[0]
    context.user_data['dir_2_name'] = directions[1]

    keyboard = [
        # direction=1 (прямий) та direction=2 (зворотній) - це стандарт API
        [InlineKeyboardButton(f"➡️ {directions[0]}", callback_data="acc_dir:1")],
        [InlineKeyboardButton(f"⬅️ {directions[1]}", callback_data="acc_dir:2")],
        [InlineKeyboardButton("⬅️ Назад (до маршрутів)", callback_data=f"acc_type:{context.user_data['accessible_type']}")]
    ]

    await query.edit_message_text(
        f"Оберіть напрямок руху для <b>{context.user_data['route_name']}</b>:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return States.ACCESSIBLE_CHOOSE_STOP_METHOD # <-- НОВИЙ СТАН


# === КРОК 4: Вибір Зупинки (НОВА ФУНКЦІЯ) ===
async def accessible_show_stops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    direction_key = query.data.split(":")[-1] # "1" або "2"
    context.user_data['direction_key'] = direction_key

    route_id = context.user_data['route_id']

    # Визначаємо, який 'pos' використовувати
    if direction_key == "1":
        start_pos = context.user_data['route_start_pos']
        stop_pos = context.user_data['route_stop_pos']
        dir_name = context.user_data['dir_1_name']
    else:
        # Для зворотнього напрямку міняємо start/stop
        start_pos = context.user_data['route_stop_pos']
        stop_pos = context.user_data['route_start_pos']
        dir_name = context.user_data['dir_2_name']

    await query.edit_message_text(f"🔄 Завантажую зупинки для напрямку '{dir_name}'...", parse_mode="HTML")

    # Отримуємо ВЕСЬ шлях (з усіма точками)
    path_data = await easyway_service.get_route_to_display(route_id, start_pos, stop_pos)

    if path_data.get("error") or not path_data.get("route", {}).get("points"):
        await query.edit_message_text(f"❌ Помилка API (GetRouteToDisplay): {path_data.get('error', 'no data')}")
        return States.ACCESSIBLE_CHOOSE_DIRECTION

    all_points = path_data.get("route", {}).get("points", {}).get("point", [])
    if not all_points:
        await query.edit_message_text("❌ Помилка: API не повернуло точки маршруту.")
        return States.ACCESSIBLE_CHOOSE_DIRECTION

    # Зберігаємо ВЕСЬ шлях (для розрахунків)
    context.user_data['route_path_points'] = all_points

    # Фільтруємо лише зупинки
    stop_points = []
    for i, point in enumerate(all_points):
        if point.get("is_stop") == "true":
            point['index_in_path'] = i # Зберігаємо індекс точки в масиві
            stop_points.append(point)

    if not stop_points:
        await query.edit_message_text("❌ Помилка: API не повернуло зупинки для цього напрямку.")
        return States.ACCESSIBLE_CHOOSE_DIRECTION

    context.user_data['route_stops'] = stop_points # Зберігаємо список зупинок

    buttons = [
        InlineKeyboardButton(
            stop.get("title"),
            # Зберігаємо індекс зупинки у списку all_points
            callback_data=f"acc_stop:{stop.get('index_in_path')}"
        ) for stop in stop_points
    ]

    keyboard = [buttons[i:i + 1] for i in range(0, len(buttons), 1)] # По одній кнопці в ряд
    keyboard.append([InlineKeyboardButton("⬅️ Назад (до напрямків)", callback_data=f"acc_route:{route_id}:{context.user_data['route_name'].split(' ')[-1]}:{context.user_data['route_start_pos']}:{context.user_data['route_stop_pos']}")])

    # TODO: Додати пагінацію, якщо зупинок > 15
    await query.edit_message_text(
        f"Оберіть вашу зупинку (напрямок: <b>{dir_name}</b>):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return States.ACCESSIBLE_GET_LOCATION # <-- ФІНАЛЬНИЙ СТАН


# === КРОК 5: Розрахунок та Показ (НОВА ФУНКЦІЯ) ===
async def accessible_calculate_and_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    stop_index_in_path = int(query.data.split(":")[-1])

    # Дістаємо всі дані, збережені раніше
    route_id = context.user_data['route_id']
    route_name = context.user_data['route_name']
    direction_key = int(context.user_data['direction_key'])
    all_points = context.user_data['route_path_points']

    try:
        user_stop_point = all_points[stop_index_in_path]
        user_stop_name = user_stop_point.get("title")
        user_stop_lat = float(user_stop_point.get("lat"))
        user_stop_lng = float(user_stop_point.get("lng"))
    except (IndexError, TypeError, ValueError):
        await query.edit_message_text("❌ Помилка: Не вдалося знайти обрану зупинку. Спробуйте знову.")
        return ConversationHandler.END

    await query.edit_message_text(f"🔄 Шукаю інклюзивні вагони для <b>{route_name}</b>...\n"
                                  f"Розраховую час до зупинки <b>{user_stop_name}</b>...", parse_mode="HTML")

    # 1. Отримуємо GPS-дані ВСІХ вагонів на маршруті
    gps_data = await easyway_service.get_route_gps(route_id)
    if gps_data.get("error"):
        await query.edit_message_text(f"❌ Помилка API (GetRouteGPS): {gps_data.get('error')}")
        return ConversationHandler.END

    vehicles = gps_data.get("vehicle", [])
    if not isinstance(vehicles, list):
        vehicles = [vehicles]

    # 2. Фільтруємо інклюзивні, що їдуть у НАШОМУ напрямку
    accessible_vehicles = [
        v for v in vehicles
        if (v.get("handicapped") == 1 or v.get("handicapped") is True) and v.get("direction") == direction_key
    ]

    if not accessible_vehicles:
        await query.edit_message_text(
            f"😢 На жаль, на маршруті <b>{route_name}</b> у вашому напрямку "
            f"зараз <b>немає</b> інклюзивних вагонів на лінії.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    # 3. --- Функція Розрахунку ---
    # Обираємо НАЙБЛИЖЧИЙ вагон, який ЩЕ НЕ ПРОЇХАВ нашу зупинку

    closest_tram = None
    min_distance_km = float('inf')

    for tram in accessible_vehicles:
        try:
            tram_lat = float(tram.get("lat"))
            tram_lng = float(tram.get("lng"))

            # a. Знаходимо найближчу точку шляху до трамвая
            tram_path_index = -1
            min_tram_dist = float('inf')

            for i, point in enumerate(all_points):
                dist = haversine(tram_lat, tram_lng, float(point.get("lat")), float(point.get("lng")))
                if dist < min_tram_dist:
                    min_tram_dist = dist
                    tram_path_index = i

            # b. Перевіряємо, чи трамвай не проїхав зупинку
            if 0 <= tram_path_index < stop_index_in_path:
                # c. Рахуємо відстань по шляху
                distance_km = 0
                for i in range(tram_path_index, stop_index_in_path):
                    p1 = all_points[i]
                    p2 = all_points[i+1]
                    distance_km += haversine(float(p1.get("lat")), float(p1.get("lng")), float(p2.get("lat")), float(p2.get("lng")))

                if distance_km < min_distance_km:
                    min_distance_km = distance_km
                    closest_tram = tram

        except (TypeError, ValueError, AttributeError):
            continue # Помилка у даних GPS, пропускаємо вагон

    # 4. Формуємо відповідь
    if not closest_tram:
        await query.edit_message_text(
            f"😢 На жаль, усі інклюзивні вагони маршруту <b>{route_name}</b> "
            f"вже проїхали зупинку <b>{user_stop_name}</b>.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    # --- Розрахунок часу ---
    # Припустимо, середня швидкість трамвая з урахуванням зупинок - 15 км/год
    AVG_SPEED_KMH = 15.0
    time_hours = min_distance_km / AVG_SPEED_KMH
    time_minutes = int(time_hours * 60)

    # Додамо 1 хвилину, щоб уникнути "0 хв"
    time_minutes = max(1, time_minutes)

    bort = closest_tram.get('id', 'Б/Н') # У Тесті 4 'id' - це бортовий номер

    text = (f"✅ <b>Найближчий інклюзивний вагон!</b>\n\n"
            f"<b>Маршрут:</b> {route_name}\n"
            f"<b>Зупинка:</b> {user_stop_name}\n\n"
            f"⏱ Очікується приблизно через: <b>~{time_minutes} хв.</b>\n"
            f"<i>(Борт №{bort}, відстань ~{min_distance_km:.1f} км)</i>")

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]),
        parse_mode="HTML"
    )
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
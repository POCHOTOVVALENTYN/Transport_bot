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


# === КРОК 0: Завантаження маршрутів (Майже без змін) ===
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

        if route_name and "Фунікулер" in route_name:
            logger.info(f"Пропускаємо маршрут 'Фунікулер': {route}")
            continue

        if not route_id or not route_name or not route_key:
            logger.warning(f"Пропускаємо маршрут з неповними даними (id, title або transport): {route}")
            continue

        if "(" in route_name:
            route_name = route_name.split("(")[0].strip()

        # (Зберігаємо лише ім'я та тип, ID маршруту нам більше не потрібен)
        if route_key == "tram":
            structured_route_map["tram"].append(route_name)  # Зберігаємо "5"
        elif route_key == "trol":
            structured_route_map["trolley"].append(route_name)  # Зберігаємо "7"

    try:
        structured_route_map["tram"].sort(key=lambda x: int(re.sub(r'\D', '', x) or '0'))
        structured_route_map["trolley"].sort(key=lambda x: int(re.sub(r'\D', '', x) or '0'))
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
        text="♿ Пошук інклюзивного транспорту.\n\nБудь ласка, оберіть тип транспорту:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return States.ACCESSIBLE_CHOOSE_ROUTE


# === КРОК 2: Вибір Маршруту (Змінено) ===
async def accessible_show_routes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    transport_type = query.data.split(":")[-1]  # "tram" або "trolley"
    context.user_data['accessible_type'] = transport_type

    structured_map = context.bot_data.get('easyway_structured_map', {"tram": [], "trolley": []})

    if transport_type == "tram":
        context.user_data['accessible_type_name'] = "Трамвай"
        route_list = structured_map.get("tram", [])
        buttons = [InlineKeyboardButton(f"Трамвай {name}", callback_data=f"acc_route:{name}") for name in route_list]
    elif transport_type == "trolley":
        context.user_data['accessible_type_name'] = "Тролейбус"
        route_list = structured_map.get("trolley", [])
        buttons = [InlineKeyboardButton(f"Тролейбус {name}", callback_data=f"acc_route:{name}") for name in route_list]
    else:
        route_list = []
        buttons = []

    if not route_list:
        await query.edit_message_text(
            "❌ Помилка: не вдалося завантажити список маршрутів з EasyWay. Спробуйте пізніше.",
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
    # --- ЗМІНЕНО: Переходимо до запиту геолокації ---
    return States.ACCESSIBLE_GET_LOCATION


# === КРОК 3: Запит Геолокації (Нова логіка) ===
async def accessible_request_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    (ПЕРЕПИСАНО)
    Крок 3: Зберігає обраний маршрут ("5") і одразу просить геолокацію.
    """
    query = update.callback_query
    await query.answer()

    route_num = query.data.split(":")[-1]  # "5"
    context.user_data['accessible_route_num'] = route_num
    context.user_data['accessible_route_name'] = f"{context.user_data['accessible_type_name']} {route_num}"

    logger.info(f"User selected route_name: {route_num}")

    await query.message.delete()
    location_keyboard = [[KeyboardButton("📍 Надати мою геолокацію", request_location=True)]]

    # Зберігаємо ID цього повідомлення, щоб видалити його
    sent_message = await query.message.reply_text(
        "Будь ласка, натисніть кнопку нижче, щоб надати вашу геолокацію. "
        "Я знайду найближчу зупинку для маршруту "
        f"<b>{context.user_data['accessible_route_name']}</b>.",
        reply_markup=ReplyKeyboardMarkup(location_keyboard, resize_keyboard=True, one_time_keyboard=True),
        parse_mode="HTML"
    )
    context.user_data['dialog_message_id'] = sent_message.message_id

    return States.ACCESSIBLE_GET_LOCATION


# === КРОК 4: Обробка Геолокації (ПЕРЕПИСАНО) ===
async def accessible_process_stub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    (ПЕРЕПИСАНО)
    Крок 4: Отримує геолокацію, знаходить найближчу зупинку
    з потрібним маршрутом, викликає accessible_process_logic.
    """
    if not (update.message and update.message.location):
        await update.message.reply_text("❌ Будь ласка, надішліть саме геолокацію, натиснувши кнопку.")
        return States.ACCESSIBLE_GET_LOCATION

    # Видаляємо кнопку "Надати геолокацію"
    try:
        if 'dialog_message_id' in context.user_data:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['dialog_message_id']
            )
    except Exception:
        pass  # Помилка не критична

    await update.message.reply_text(
        "Дякую! Оброблюю ваші геодані та шукаю найближчу зупинку...",
        reply_markup=ReplyKeyboardRemove()
    )
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.FIND_LOCATION)

    user_lat = update.message.location.latitude
    user_lon = update.message.location.longitude

    # 1. Отримуємо дані з context
    target_route_name = context.user_data.get('accessible_route_num')  # "5"
    target_route_type_key = context.user_data.get('accessible_type')  # "tram" або "trolley"

    # API EasyWay використовує 'trol' для тролейбусів
    api_route_type = "trol" if target_route_type_key == "trolley" else target_route_type_key

    if not target_route_name or not api_route_type:
        await update.message.reply_text("❌ Критична помилка: дані про маршрут втрачено. Будь ласка, почніть знову.")
        await main_menu(update, context)  # Повертаємо в головне меню
        return ConversationHandler.END

    # 2. Викликаємо API GetStopsNearPoint (НОВА ФУНКЦІЯ)
    nearby_data = await easyway_service.get_stops_near_point(user_lat, user_lon)

    if nearby_data.get("error"):
        await update.message.reply_text(f"❌ Помилка API EasyWay (GetStopsNearPoint): {nearby_data['error']}")
        await main_menu(update, context)
        return ConversationHandler.END

    nearby_stops = nearby_data.get("stop", [])
    if not nearby_stops:
        await update.message.reply_text("❌ Поруч (в радіусі 500м) не знайдено жодної зупинки.")
        await main_menu(update, context)
        return ConversationHandler.END

    if not isinstance(nearby_stops, list):
        nearby_stops = [nearby_stops]  # Робимо списком, якщо це один об'єкт

    logger.info(f"Знайдено {len(nearby_stops)} зупинок поруч. Починаю перевірку маршрутів...")

    # 3. Шукаємо збіг (НОВА ЛОГІКА ЦИКЛУ)
    found_stop_id = None
    found_stop_name = None
    found_arrivals_data = None  # Тут збережемо дані, щоб не робити зайвий запит

    for stop in nearby_stops:
        stop_id = stop.get("id")
        stop_name = stop.get("title")
        if not stop_id:
            continue

        # 3.1. Викликаємо GetStopInfo для КОЖНОЇ зупинки
        arrivals_data = await easyway_service.get_stop_arrivals(stop_id)
        if arrivals_data.get("error"):
            logger.warning(f"Не вдалося отримати інфо для зупинки {stop_id}: {arrivals_data['error']}")
            continue  # Переходимо до наступної зупинки

        transports_data = arrivals_data.get("transports", {}).get("transport", [])
        if not isinstance(transports_data, list):
            transports_data = [transports_data]

        # 3.2. Перевіряємо маршрути на цій зупинці
        for transport_type in transports_data:
            routes_data = transport_type.get("route", [])
            if not isinstance(routes_data, list):
                routes_data = [routes_data]

            for route in routes_data:
                # Застосовуємо ту саму логіку очищення, що й при завантаженні
                if "(" in api_route_title:
                    api_route_title = api_route_title.split("(")[0].strip()
                api_transport_key = transport_type.get("key")  # 'bus', 'tram', 'trol'

                # 3.3. Перевіряємо збіг
                if api_route_title == target_route_name and api_transport_key == api_route_type:
                    found_stop_id = stop_id
                    found_stop_name = stop_name
                    found_arrivals_data = arrivals_data
                    logger.info(
                        f"✅ Знайдено збіг! Зупинка: {found_stop_name} (ID: {found_stop_id}) має маршрут {api_transport_key} {api_route_title}")
                    break
            if found_stop_id:
                break
        if found_stop_id:
            break

    if not found_stop_id:
        await update.message.reply_text(
            f"❌ Вибачте, я не можу знайти зупинку маршруту "
            f"<b>{context.user_data['accessible_route_name']}</b> поруч з вами.",
            parse_mode="HTML"
        )
        await main_menu(update, context)
        return ConversationHandler.END

    # 4. Викликаємо фінальну логіку, ПЕРЕДАЮЧИ ЇЙ ВЖЕ ОТРИМАНІ ДАНІ
    return await accessible_process_logic(update, context, found_stop_id, found_stop_name, found_arrivals_data)


# === КРОК 5: Показ результатів (ЗМІНЕНО) ===
async def accessible_process_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, stop_id: str, stop_name: str,
                                   arrivals_data: dict):
    """
    (Крок 5) Загальна логіка обробки.
    Тепер приймає 'arrivals_data' як аргумент.
    """

    route_name = context.user_data['accessible_route_name']
    route_num = context.user_data['accessible_route_num']  # "5"
    chat_id = update.effective_chat.id

    # 1. БІЛЬШЕ НЕ РОБИМО ЗАПИТ. Використовуємо 'arrivals_data'
    data = arrivals_data

    accessible_arrivals = []

    # (data['transports']['transport'] може бути або списком, або одним об'єктом)
    transports_data = data.get("transports", {}).get("transport", [])
    if not isinstance(transports_data, list):
        transports_data = [transports_data]  # Робимо списком

    for transport_type in transports_data:
        routes_data = transport_type.get("route", [])
        if not isinstance(routes_data, list):
            routes_data = [routes_data]  # Робимо списком

        for route in routes_data:
            # route['title'] = "5"
            # route['handicapped'] = true/false (з v1.2)
            # route['time'] = "5" (хвилини)

            # Перевіряємо, чи це наш маршрут І чи він інклюзивний
            if (str(route.get("title")).strip() == str(route_num) and
                    route.get("handicapped") is True):
                accessible_arrivals.append(route)

    # 3. Формуємо відповідь (ЦЯ ЧАСТИНА БЕЗ ЗМІН)
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
            bort = transport.get('bortNumber', 'Б/Н')
            time_min = transport.get('timeLeft', 0)
            time_source = transport.get('timeSource', 'N/A')

            source_emoji = "🛰️ (GPS)" if time_source == "gps" else "📅 (Розклад)"
            text += f"▪️ Борт <b>№{bort}</b> - через <b>~{time_min} хв.</b> {source_emoji}\n"

            if int(time_min) > 4 and time_source == "gps" and i == 0:
                context.user_data['notify_transport'] = transport
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

    notify_data = context.user_data.get('notify_transport')
    notify_stop = context.user_data.get('notify_stop_name')
    context.user_data.clear()
    if notify_data:
        context.user_data['notify_transport'] = notify_data
        context.user_data['notify_stop_name'] = notify_stop

    return States.ACCESSIBLE_AWAIT_NOTIFY


# === КРОК 6: Сповіщення (Без змін) ===
async def notify_user_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    bort = job.data.get('bort', 'Б/Н')
    stop_name = job.data.get('stop_name', 'вашу зупинку')

    text = f"🔔 <b>НАГАДУВАННЯ!</b>\n\nІнклюзивний транспорт (борт <b>№{bort}</b>) " \
           f"буде на зупинці <b>{stop_name}</b> приблизно через <b>3 хвилини</b>. " \
           f"Будь ласка, готуйтеся!"
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")


async def accessible_notify_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    transport_data = context.user_data.get('notify_transport')
    stop_name = context.user_data.get('notify_stop_name', 'ваша зупинка')

    if not transport_data:
        await query.edit_message_text("❌ Помилка: дані про транспорт втрачено.")
        return ConversationHandler.END

    time_min = int(transport_data.get('timeLeft', 0))
    bort = transport_data.get('bortNumber', 'Б/Н')
    notify_delay_seconds = (time_min - 3) * 60

    if notify_delay_seconds < 1:
        await query.edit_message_text("🔔 Вже майже час! Не можу встановити сповіщення, борт прибуває.")
        return ConversationHandler.END

    context.job_queue.run_once(
        notify_user_callback,
        when=notify_delay_seconds,
        data={"bort": bort, "stop_name": stop_name},
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
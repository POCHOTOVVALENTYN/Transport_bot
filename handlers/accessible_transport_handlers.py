# handlers/accessible_transport_handlers.py
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, \
    ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from bot.states import States
from handlers.command_handlers import get_main_menu_keyboard
from handlers.menu_handlers import main_menu
from config.settings import ROUTES  # Використовуємо ваші маршрути

logger = logging.getLogger(__name__)


# === КРОК 1: Початок -> Вибір Типу (ВАША ІДЕЯ) ===

async def accessible_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок діалогу: просить обрати тип транспорту (Трамвай/Тролейбус)."""
    query = update.callback_query
    #await query.answer()

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
    #await query.answer()

    transport_type = query.data.split(":")[-1]  # "TRAM" або "TROLLEY"

    keyboard = []

    if transport_type == "TRAM":
        context.user_data['accessible_type_name'] = "Трамвай"
        route_list = ROUTES["tram"]
        buttons = [InlineKeyboardButton(f"Трамвай {r}", callback_data=f"acc_route:T:{r}") for r in route_list]
    else:
        context.user_data['accessible_type_name'] = "Тролейбус"
        route_list = ROUTES["trolleybus"]
        buttons = [InlineKeyboardButton(f"Тролейбус {r}", callback_data=f"acc_route:TB:{r}") for r in route_list]

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


# === КРОК 3: Вибір Напрямку (Заглушка) ===

async def accessible_choose_direction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Крок 3: Просить обрати напрямок. Використовуємо ЗАГЛУШКИ."""
    query = update.callback_query
    #await query.answer()

    # 'acc_route:T:5' або 'acc_route:TB:7'
    route_type, route_num = query.data.split(":")[1:]

    # Зберігаємо повну назву
    type_name = "Трамвай" if route_type == "T" else "Тролейбус"
    context.user_data['accessible_route'] = f"{type_name} {route_num}"
    logger.info(f"User selected accessible route: {type_name} {route_num}")

    keyboard = []

    # --- ЛОГІКА ЗАГЛУШКИ (як ви просили) ---
    if route_num == "5":
        keyboard = [
            [InlineKeyboardButton("➡️ В бік Аркадії", callback_data="acc_dir:arcadia")],
            [InlineKeyboardButton("⬅️ В бік Автовокзалу", callback_data="acc_dir:autovokzal")]
        ]
    elif route_num == "7":
        keyboard = [
            [InlineKeyboardButton("➡️ В бік вул. Паустовського", callback_data="acc_dir:paust")],
            [InlineKeyboardButton("⬅️ В бік 11-ї ст. Люстдорфської дороги", callback_data="acc_dir:lustdorf")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("➡️ Напрямок 1 (Заглушка)", callback_data="acc_dir:dir1")],
            [InlineKeyboardButton("⬅️ Напрямок 2 (Заглушка)", callback_data="acc_dir:dir2")]
        ]
    # --- КІНЕЦЬ ЗАГЛУШКИ ---

    # Кнопка "Назад" тепер веде до списку маршрутів (Крок 2)
    # Ми "обманюємо" систему, викликаючи той самий callback, що й на Кроці 1
    # Це змусить `accessible_show_routes` відпрацювати знову
    type_callback = "acc_type:TRAM" if route_type == "T" else "acc_type:TROLLEY"
    keyboard.append([InlineKeyboardButton("⬅️ Назад (до маршрутів)", callback_data=type_callback)])
    keyboard.append([InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")])

    await query.edit_message_text(
        text=f"Ви обрали: <b>{context.user_data['accessible_route']}</b>.\n\nТепер оберіть напрямок руху:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return States.ACCESSIBLE_CHOOSE_STOP_METHOD


# === КРОК 4: Вибір Методу Пошуку Зупинки (Покращення №2) ===

async def accessible_choose_stop_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Крок 4: Реалізація Покращення №2. Даємо вибір: Гео чи Список."""
    query = update.callback_query
    #await query.answer()

    direction = query.data.split(":")[-1]
    context.user_data['accessible_direction'] = direction
    logger.info(f"User selected direction: {direction}")

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---

    # 1. Створюємо базовий список кнопок
    keyboard = [
        [InlineKeyboardButton("📍 Надати геолокацію (я на зупинці)", callback_data="acc_stop:geo")],
        [InlineKeyboardButton("🚏 Обрати зі списку (планую поїздку)", callback_data="acc_stop:list")],
    ]

    # 2. Визначаємо callback для кнопки "Назад"
    route_callback = f"acc_route:{context.user_data['accessible_route'].replace('рамвай', 'T').replace('ролейбус', 'TB').replace(' ', ':')}"

    # 3. Додаємо кнопки "Назад" та "Скасувати" ОКРЕМО
    keyboard.append([InlineKeyboardButton("⬅️ Назад (до напрямків)", callback_data=route_callback)])
    keyboard.append([InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")])

    # 4. Передаємо готову клавіатуру в InlineKeyboardMarkup
    await query.edit_message_text(
        text="Як знайти вашу зупинку?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    return States.ACCESSIBLE_GET_LOCATION


# === КРОК 5 (Варіант А): Запит Геолокації (Reply-кнопка) ===

async def accessible_request_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Крок 5А: Надсилає кнопку ReplyKeyboardMarkup для запиту локації."""
    query = update.callback_query
    await query.answer()
    await query.message.delete()

    location_keyboard = [[KeyboardButton("📍 Надати мою геолокацію", request_location=True)]]

    await query.message.reply_text(
        "Будь ласка, натисніть кнопку нижче (АЛЕ ПЕРЕД ЦИМ УВІМКНІТЬ БУДЬ ЛАСКА ФУНКЦІЮ (ОПЦІЮ) ГЕОЛОКАЦІЇ "
        "НА СМАРТФОНІ),\n щоб надати вашу геолокацію. Я знайду найближчу зупинку.",
        reply_markup=ReplyKeyboardMarkup(location_keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return States.ACCESSIBLE_GET_LOCATION  # Залишаємось у тому ж стані, чекаючи на локацію


# === КРОК 5 (Варіант Б): Вибір зі Списку (Заглушка) ===

async def accessible_choose_from_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Крок 5Б: Повинен показати список зупинок. Використовуємо ЗАГЛУШКУ."""
    query = update.callback_query
    #await query.answer()

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---

    # 1. Створюємо базовий список кнопок
    keyboard = [
        [InlineKeyboardButton("Зупинка 'А' (Заглушка)", callback_data="acc_stop_select:stop_A")],
        [InlineKeyboardButton("Зупинка 'Б' (Заглушка)", callback_data="acc_stop_select:stop_B")],
        [InlineKeyboardButton("Зупинка 'В' (Заглушка)", callback_data="acc_stop_select:stop_V")],
        [InlineKeyboardButton("... (тут буде пагінація) ...", callback_data="dummy")],
    ]

    # 2. Додаємо кнопки "Назад" та "Скасувати" ОКРЕМО
    keyboard.append([InlineKeyboardButton("⬅️ Назад (Гео/Список)",
                                          callback_data=f"acc_dir:{context.user_data['accessible_direction']}")])
    keyboard.append([InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")])

    # 3. Передаємо готову клавіатуру в InlineKeyboardMarkup
    await query.edit_message_text(
        text="🚏 Оберіть вашу зупинку зі списку:\n\n<b>[ЗАГЛУШКА]</b>\n<i>(Цей список буде завантажено з API)</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    return States.ACCESSIBLE_CHOOSE_FROM_LIST


# === КРОК 6: Обробка результату (Головна Заглушка + Покращення №1) ===

async def accessible_process_stub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Крок 6: ГОЛОВНА ЗАГЛУШКА.
    Сюди ми потрапляємо або з геолокацією, або з вибором зупинки.
    """

    if update.message and update.message.location:
        await update.message.reply_text("Дякую! Оброблюю вашу геолокацію...", reply_markup=ReplyKeyboardRemove())
        user_location = update.message.location
        logger.info(f"User location received: {user_location.latitude}, {user_location.longitude}")
        context.user_data['stop_name'] = "ТОСТОВЕ ПОВІДОМЛЕННЯ!!!\n\nЗупинка 'Проспект Шевченка' (знайдено по гео)"

    elif update.callback_query:
        await update.callback_query.answer()
        stop_id = update.callback_query.data.split(":")[-1]
        logger.info(f"User selected stop from list: {stop_id}")
        context.user_data['stop_name'] = f"Зупинка '{stop_id}' (обрано зі списку)"
        await update.callback_query.message.delete()
    else:
        await update.message.reply_text("Сталася помилка, скасовую діалог.", reply_markup=ReplyKeyboardRemove())
        return await main_menu(update, context)

        # --- ГОЛОВНА ЗАГЛУШКА API (Пошук транспорту) ---
    stop_name = context.user_data['stop_name']
    arrival_time_min = 25
    board_num = "4015"

    context.user_data['arrival_time_min'] = arrival_time_min

    text = (
        f"✅ <b>Запит виконано!</b>\n\n"
        f"<b>Маршрут:</b> {context.user_data['accessible_route']}\n"
        f"<b>Зупинка:</b> {stop_name}\n\n"
        f"Наступний низькопідлоговий транспорт (борт <b>№{board_num}</b>) очікується приблизно через <b>{arrival_time_min} хвилин</b>."
    )

    keyboard = [
        [InlineKeyboardButton("🔔 Повідомити за 5 хв до прибуття", callback_data="acc_notify_me")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    else:
        await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard),
                                                       parse_mode="HTML")

    return States.ACCESSIBLE_AWAIT_NOTIFY


# === КРОК 7: Заглушка для "Повідомити" (Покращення №1) ===

async def accessible_notify_me_stub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Крок 7: ЗАГЛУШКА для Job Queue."""
    query = update.callback_query
    #await query.answer()

    arrival_time_min = context.user_data.get('arrival_time_min', 25)
    notify_time_min = arrival_time_min - 5

    text = (
        f"Добре! Я надішлю вам сповіщення.\n\n"
        f"<b>[ЗАГЛУШКА Job Queue]</b>\n"
        f"<i>(Бот мав би 'прокинутись' через {notify_time_min} хв і надіслати сповіщення. "
        f"Зараз я просто завершую діалог.)</i>"
    )

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]),
        parse_mode="HTML"
    )

    context.user_data.clear()
    return ConversationHandler.END


# === Скасування діалогу ===

async def accessible_text_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування, якщо користувач надіслав текст замість кнопки/гео."""
    await update.message.reply_text("Діалог пошуку скасовано.", reply_markup=ReplyKeyboardRemove())
    # Повертаємо головне меню
    keyboard = await get_main_menu_keyboard(update.effective_user.id)
    await update.message.reply_text(
        "🚊 Оберіть потрібну опцію:",
        reply_markup=keyboard
    )
    context.user_data.clear()
    return ConversationHandler.END

# Примітка: main_menu імпортується і використовується як fallback,
# тому окрема функція "accessible_cancel" через кнопку не потрібна.
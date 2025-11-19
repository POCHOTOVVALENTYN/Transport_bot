from handlers.menu_handlers import main_menu
from utils.logger import logger
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler, Application
from bot.states import States
from handlers.command_handlers import get_main_menu_keyboard
from services.easyway_service import easyway_service
import asyncio
import telegram.error
import html
from rapidfuzz import fuzz


# Словник "синонімів" для виправлення поширених помилок пошуку
# Ключ (в нижньому регістрі) = що вводить користувач
# Значення = що ми насправді шукаємо в API EasyWay
SEARCH_SYNONYMS = {
    "музкомедія": "Театр Музкомедії",
    "вокзал": "Залізничний вокзал",
    "привоз": "Привоз", # Це виправить і текстовий пошук, а не лише кнопку
    "новий ринок": "Новий ринок",
    "парк горького": "вул. Героїв Крут",
    "південний": "Ринок Південний",
    "тираспольська": "пл. Тираспільська",
    "дерев'янка": "пл. Бориса Дерев'янка",
    "площа дерев'янка": "пл. Бориса Дерев'янка",
    "обласна лікарня": "вул. Заболотного", # Тут пошук по вулиці виправданий
    "заболотного": "вул. Заболотного",
    "паустовського": "вул. 28-ї Бригади",
    "політех": "Політехнічний інститут",
    "філатова": "Інститут Філатова",
    "парк шевченка": "Парк ім. Тараса Шевченка",
    "парк победы": "Парк Перемоги",
    "Старосіна": "пл. Старосінна",
    "пл. 10 апреля": "пл. 10 квітня",
     "Алексеевская": "пл. Олексіївська"

}

# Мінімальний відсоток схожості для нечіткого пошуку (0-100)
FUZZY_SEARCH_THRESHOLD = 80



# === ФУНКЦІЯ, ЩО ЗАЛИШАЄТЬСЯ (для main.py та thanks_handler) ===
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
        logger.info(f"[DEBUG load_easyway_route_ids] Отримано маршрут: {route}")
        route_key = route.get("transport")
        route_id = route.get("id")
        route_name = route.get("title")
        start_pos = route.get("start_position")
        stop_pos = route.get("stop_position")

        if route_name and "Фунікулер" in route_name:
            logger.info(f"Пропускаємо маршрут 'Фунікулер': {route}")
            continue

        if not all([route_id, route_name, route_key, start_pos is not None, stop_pos is not None]):
            logger.warning(f"Пропускаємо маршрут з неповними даними: {route}")
            continue

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



# === НОВІ ОБРОБНИКИ (План v1.2) ===

async def accessible_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Крок 1: Користувач запускає пошук. Одразу просимо ввести назву зупинки.
    """
    query = update.callback_query
    await query.answer()

    # Виконайте пошук "Ринок"
    #data = await easyway_service.get_places_by_name(search_term="Ринок Привоз")
    #stops = data.get("stops", [])

    # 🔍 ЛОГУВАННЯ ДЛЯ ДІАГНОСТИКИ
    #logger.info(f"===== DIAGNOSTIC: Пошук =====")
    #for stop in stops:
    #    logger.info(f"ID: {stop['id']}, Назва: {stop['title']}, Lat: {stop['lat']}, Lng: {stop['lng']}")
    #logger.info(f"=====================================")


    logger.info(f"User {update.effective_user.id} started v1.2 accessible transport search")

    # Ініціалізуємо/очищуємо дані
    context.user_data.clear()

    # Клавіатура з популярними зупинками
    keyboard = [
        [
            InlineKeyboardButton("🚉 Залізничний вокзал", callback_data="stop_search_Залізничний вокзал"),
            InlineKeyboardButton("📍 Ринок Привоз", callback_data="stop_search_Привоз")
        ],
        [
            InlineKeyboardButton("🏛️ вул. Грецька", callback_data="stop_search_вул. Грецька"),
            InlineKeyboardButton("🌊 Аркадія", callback_data="stop_search_Аркадія")
        ],
        [
            InlineKeyboardButton("🏞️ Старосінна площа", callback_data="stop_search_пл. Старосінна"),
            InlineKeyboardButton("🛍️ Ринок 'Південний'", callback_data='stop_search_Ринок "Південний"')
        ],
        [
            InlineKeyboardButton("🌳 Парк ім. Тараса Шевченка", callback_data="stop_search_Парк ім. Тараса Шевченка"),
            InlineKeyboardButton("🏁 вул. 28-ї бригади", callback_data="stop_search_вул. 28-ї Бригади")
        ],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = (
        "♿️ <b>Пошук Низькопідлогового Транспорту</b> 🔎\n\n"
        "📝 Будь ласка, <b>напишіть назву зупинки</b> (обов'язково <b>державною мовою</b> 🇺🇦).\n\n"
        "💡 <b>Підказка:</b> Можна вводити <b>не повну назву</b>.\n"
        "<i>(Наприклад, достатньо написати «Привоз» або «Шевченка» замість повної офіційної назви).</i>\n\n"
        "👇 ...або оберіть варіант з популярних нижче:"
    )

    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="HTML")
    return States.ACCESSIBLE_SEARCH_STOP


async def accessible_search_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Крок 2: Користувач вводить текст для пошуку зупинки.
    """
    # 1. СПЕРШУ отримуємо дані від користувача
    user_id = update.effective_user.id
    original_input = update.message.text.strip()  # <--- Оголошуємо змінну тут

    # 2. ТЕПЕР можемо її використовувати
    context.user_data['last_search_term'] = original_input  # <--- Тепер помилки не буде

    normalized_input = original_input.lower()

    search_term = None  # Поки що не визначено

    # --- ПОЧАТОК РЕФАКТОРИНГУ: Нечіткий (Fuzzy) пошук ---

    # 1. Спершу шукаємо точний збіг у синонімах (найшвидший варіант)
    if normalized_input in SEARCH_SYNONYMS:
        search_term = SEARCH_SYNONYMS[normalized_input]
        logger.info(f"User {user_id} search (Synonym): '{original_input}' -> '{search_term}'")

    # 2. Якщо точного збігу немає, пробуємо нечіткий пошук по ключах словника
    if not search_term:
        # Шукаємо найкращий збіг серед наших ключів ("музкомедія", "вокзал", "привоз")
        best_match_key = None
        best_score = 0

        for key in SEARCH_SYNONYMS.keys():
            score = fuzz.ratio(normalized_input, key)  # Розрахунок схожості
            if score > best_score:
                best_score = score
                best_match_key = key

        # Якщо найкращий збіг достатньо схожий
        if best_score >= FUZZY_SEARCH_THRESHOLD:
            search_term = SEARCH_SYNONYMS[best_match_key]  # Беремо ПРАВИЛЬНИЙ термін
            logger.info(
                f"User {user_id} search (Fuzzy): '{original_input}' -> '{search_term}' (Match: '{best_match_key}', Score: {best_score}%)")

    # 3. Якщо нічого не допомогло (ні точний, ні нечіткий пошук),
    #    беремо те, що користувач ввів "як є".
    if not search_term:
        search_term = original_input
        logger.info(f"User {user_id} searching for stop: {search_term}")

    # --- КІНЕЦЬ РЕФАКТОРИНГУ ---

    await update.message.chat.send_action("typing")

    try:
        # API CALL #1: cities.GetPlacesByName
        data = await easyway_service.get_places_by_name(search_term=search_term)

        if data.get("error"):
            error_text = (
                "❌ <b>Помилка API-даних</b>\n\n"
                "Сервер не відповів вчасно. Спробуємо ще раз."
            )

            # Збережемо запит, щоб використати його у спеціальному Retry
            context.user_data['failed_search_query'] = original_input

            await update.message.reply_text(
                text=error_text,
                reply_markup=_get_error_keyboard(retry_callback_data="accessible_retry_manual"),
                parse_mode=ParseMode.HTML
            )
            return States.ACCESSIBLE_SEARCH_STOP

        # 3. ВИЗНАЧАЄМО змінну places, витягуючи її з data
        places = data.get("stops", [])  # <--- ВИПРАВЛЕНО: Створення змінної places

        # Важлива перевірка: чи знайшлися взагалі зупинки?
        if not places:
            await update.message.reply_text(
                f"❌ Зупинок не знайдено за запитом <b>'{search_term}'</b>.\n\n"
                f"Спробуйте іншу назву.",
                parse_mode="HTML"
            )
            return States.ACCESSIBLE_SEARCH_STOP

        # Зберігаємо результати в контекст
        context.user_data["search_results"] = places  # <--- Тепер змінна існує, помилки не буде

        # Показуємо кнопки зі знайденими зупинками
        await _show_stops_keyboard(update, places)  # <--- Тепер змінна існує
        return States.ACCESSIBLE_SELECT_STOP

    except Exception as e:
        logger.error(f"Error searching stops: {e}")
        await update.message.reply_text(f"❌ Помилка при пошуку: {str(e)}")
        return States.ACCESSIBLE_SEARCH_STOP


async def accessible_stop_quick_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Крок 2 (альтернативний): Користувач натискає кнопку популярної зупинки.
    """
    query = update.callback_query
    await query.answer()

    search_term = query.data.split("stop_search_")[-1]
    logger.info(f"User {query.from_user.id} quick searching for: {search_term}")

    # Повідомляємо про пошук
    await query.edit_message_text(
        f"🔄 Пошук зупинок за терміном: <b>'{search_term}'</b>...",
        parse_mode="HTML"
    )

    try:
        # Виконуємо пошук
        data = await easyway_service.get_places_by_name(search_term=search_term)

        if data.get("error"):
            # Тут ваш код обробки помилок (з кнопкою "Повторити")
            error_text = "❌ <b>Помилка API-даних</b>\n\nСервер не відповів вчасно. Спробуємо ще раз."
            await query.edit_message_text(
                text=error_text,
                reply_markup=_get_error_keyboard(retry_callback_data=query.data),
                parse_mode=ParseMode.HTML
            )
            return States.ACCESSIBLE_SELECT_STOP

        places = data.get("stops", [])
        if not places:
            await query.edit_message_text(
                f"❌ Зупинок не знайдено за запитом <b>'{search_term}'</b>.",
                parse_mode="HTML"
            )
            return States.ACCESSIBLE_SEARCH_STOP

        context.user_data["search_results"] = places

        # === ОСЬ ЦЬОГО РЯДКА НЕ ВИСТАЧАЛО ===
        # Викликаємо нашу універсальну функцію для показу кнопок
        await _show_stops_keyboard(update, places)

        return States.ACCESSIBLE_SELECT_STOP

    except Exception as e:
        logger.error(f"Error in quick search: {e}")
        await query.edit_message_text(f"❌ Помилка: {str(e)}")
        return States.ACCESSIBLE_SEARCH_STOP


async def accessible_stop_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Крок 3: Користувач обрав зупинку. Робимо виклик.
    """
    query = update.callback_query
    await query.answer()

    try:
        # === ПОЧАТОК ВЕЛИКОГО TRY...EXCEPT БЛОКУ ===
        # (Захист від BadRequest на кожному кроці)

        try:
            stop_id = int(query.data.split("stop_")[-1])
        except (ValueError, IndexError):
            await query.edit_message_text("❌ Помилка: Некоректний ID зупинки.")
            return States.ACCESSIBLE_SEARCH_STOP

        user_id = query.from_user.id
        logger.info(f"User {user_id} selected stop_id: {stop_id}")

        await query.edit_message_text("🔄 Отримую інформацію про прибуття...")

        # API CALL #2: stops.GetStopInfo v1.2
        stop_info = await easyway_service.get_stop_info_v12(stop_id=stop_id)

        if stop_info.get("error"):
            # Це спрацює при тайм-ауті (з Кроку 2)
            await query.edit_message_text(f"❌ Помилка API-даних: {stop_info['error']}")
            return States.ACCESSIBLE_SEARCH_STOP

        stop_title = stop_info.get("title", f"Зупинка ID: {stop_id}")
        stop_title_safe = html.escape(stop_title)

        # ФІЛЬТРУЄМО ТІЛЬКИ НИЗЬКОПІДЛОГОВИЙ ТРАНСПОРТ
        handicapped_routes = easyway_service.filter_handicapped_routes(stop_info)

        # Показуємо результати
        await _show_accessible_transport_results(query, stop_title_safe, handicapped_routes)

        #context.user_data.clear()
        return States.ACCESSIBLE_SHOWING_RESULTS

    except telegram.error.BadRequest as br_error:
        # Користувач натиснув щось інше, поки бот "думав"
        logger.warning(f"BadRequest in accessible_stop_selected (stale query?): {br_error}")
        # Ми не можемо відповісти на query, бо він застарілий.
        # Просто виходимо зі сцени.
        return ConversationHandler.END

    except Exception as e:
        # Всі інші помилки (напр., помилки парсингу, якщо API змінилось)
        logger.error(f"Critical error in accessible_stop_selected: {e}", exc_info=True)
        try:
            # Спробуємо повідомити про помилку
            await query.edit_message_text(
                f"❌ Критична помилка: {str(e)}",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⬅️ Пошук іншої зупинки", callback_data="accessible_start")]]
                )
            )
        except telegram.error.BadRequest:
            # Якщо навіть це не вдалося, просто логуємо
            logger.warning("Stale query in accessible_stop_selected (Exception block)")

        return States.ACCESSIBLE_SEARCH_STOP
    # === КІНЕЦЬ ВЕЛИКОГО TRY...EXCEPT БЛОКУ ===


async def _show_stops_keyboard(update: Update, places: list):
    """
    УНІВЕРСАЛЬНА функція: показує список знайдених зупинок.
    Вміє і редагувати повідомлення (для кнопок), і надсилати нове (для тексту).
    """
    keyboard = []
    for place in places[:10]:  # Максимум 10 кнопок
        title = place['title']
        # Отримуємо рядок з маршрутами (якщо він є після вашого парсера)
        summary = place.get('routes_summary')

        # Формуємо текст кнопки
        button_text = f"📍 {title}"
        if summary:
            button_text += f"\n{summary}"  # Додаємо маршрути з нового рядка

        # Обрізаємо занадто довгий текст (обмеження Telegram - 64 байти для callback_data, але текст кнопки може бути довшим)
        # Проте краще тримати його в межах розумного
        if len(button_text) > 50:
            button_text = button_text[:47] + "..."

        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"stop_{place['id']}"
            )
        ])

    # Додаємо кнопку "Назад"
    keyboard.append([InlineKeyboardButton("⬅️ Назад до пошуку", callback_data="accessible_start")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Текст повідомлення
    message_text = (
        "✅ Знайдено!\nОберіть точну зупинку зі списку: \n"
        " <b>💡Підказка:</b> Щоб отримати інформацію про <b>\n\n🧭НАПРЯМОК  РУХУ🧭</b> \n"
        "(<i>напр., \"→ у бік пл. Тираспольська\"</i>) "
        "та час прибуття ⏱️ "
        " \n\n<b>👇НАТИСНІТЬ НА ЗУПИНКУ👇</b> "
    )

    # --- ГОЛОВНА ЛОГІКА ВІДОБРАЖЕННЯ ---
    if update.callback_query:
        # Якщо це натискання кнопки (напр., "Ринок Привоз") -> Редагуємо повідомлення "Пошук..."
        # Спочатку перевіряємо, чи повідомлення змінилось, щоб уникнути помилок
        try:
            await update.callback_query.edit_message_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            # Якщо редагування неможливе (наприклад, текст той самий), можна ігнорувати або надіслати нове
            logger.warning(f"Could not edit message: {e}")

    else:
        # Якщо це текстовий ввід (напр., "Аркадія") -> Надсилаємо нове повідомлення
        await update.message.reply_text(
            text=message_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )


async def _show_accessible_transport_results(query, stop_title: str, routes: list):
    """
    Показує фінальні результати (список інклюзивного транспорту).

    """
    if not routes:
        # Сценарій: Немає низькопідлогового транспорту
        message = (
            f"♿️ <b>На зупинці '{stop_title}'</b> 🚏\n"
            f"───────────────\n\n"
            f"🤔 <b>Зараз не видно низькопідлогового транспорту...</b>\n\n"
            f"Це може означати, що:\n"
            f"1️⃣ Вагон вже проїхав цю зупинку і рухається в іншому напрямку.\n"
            f"2️⃣ Вагон знаходиться на кінцевій зупинці (очікує часу відправлення).\n"
            f"3️⃣ Тимчасова відсутність GPS-сигналу.\n\n"
            f"📢 <b>Важливо!</b>\n"
            f"⚠️ Під час <b>повітряної тривоги</b> 🚨 дані про рух можуть відображатися некоректно.\n\n"
            f"🗺 <b>Порада:</b> Спробуйте будь ласка оновити запит через декілька хвилин або "
            f"перевірте загальний рух електротранспорту в застосунку Misto, щоб побачити де знаходяться вагони зараз."
        )
        keyboard = [
            # Додаємо кнопку на карту (використовуємо посилання на EasyWay або Misto)
            [InlineKeyboardButton("🗺️ Відкрити додаток Misto (Android)",
                                  url="https://play.google.com/store/apps/details?id=tech.misto.android.misto&hl=uk")],
            [InlineKeyboardButton("🗺️ Відкрити додаток Misto (Iphone)",
                                  url="https://apps.apple.com/ua/app/misto/id6738929703?l=ru")],
            # Або посилання на додаток
            [InlineKeyboardButton("⬅️ Назад до списку зупинок", callback_data="accessible_back_to_list")],
            [InlineKeyboardButton("🔄 Оновити пошук", callback_data="accessible_start")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
        ]
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    # Сценарій: Є низькопідлоговий транспорт
    header = (
        f"♿️ <b>Низькопідлоговий Транспорт</b>\n"
        f"📍 Зупинка: <b>{stop_title}</b>\n"
        f"🚊— ─ ─ ─ ─ ─ ─ ─ ─ 🚎\n"
        f"👋 Шановні пасажари!\n"
        f"⏱️ Інформація про час прибуття \n\n<b>⚠️дійсна на момент запиту⚠️</b>\n\n"
        f"📢 <b>Важливо!</b>\n"
        f"⚠️ Під час <b>повітряної тривоги</b> 🚨 дані про рух трамваїв та тролейбусів можуть відображатися "
        f"<b>некоректно</b> або із затримкою. 📡\n\n"
        f"🚊— ─ ─ ─ ─ ─ ─ ─ ─ 🚎\n\n"
    )

    routes_text = ""
    for i, route in enumerate(routes, 1):
        # Ігноруємо "marshrutka"
        if route.get("transport_key") == "marshrutka":
            continue

        transport_icon = easyway_service.get_transport_icon(route["transport_key"])
        time_icon = easyway_service.get_time_source_icon(route["time_source"])

        # Комфорт
        comfort_items = []
        if route.get("wifi"):
            comfort_items.append("📶 Wi-Fi")
        if route.get("aircond"):
            comfort_items.append("❄️ A/C")

        comfort_str = f"| {', '.join(comfort_items)}" if comfort_items else ""

        # --- Екранування HTML ---
        # Екрануємо ВСІ дані, що прийшли з API
        safe_transport_name = html.escape(route.get('transport_name', 'N/A'))
        safe_title = html.escape(route.get('title', 'N/A'))
        safe_direction = html.escape(route.get('direction', 'N/A'))
        safe_bort_number = html.escape(route.get('bort_number', '??'))
        safe_time_left = html.escape(route.get('time_left_formatted', 'N/A'))

        route_line = (
            f"<b>{i}. {transport_icon} {safe_transport_name} №{safe_title}</b>\n"
            f"   → <i>(напрямок: {safe_direction})</i>\n"
            f"   Борт: <b>{safe_bort_number}</b> {comfort_str}\n"
            f"   <b>Прибуття: {time_icon} {safe_time_left}</b>\n\n"
        )
        routes_text += route_line
        # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    # === ВИПРАВЛЕННЯ ТУТ ===
    footer = (
        f"<b>Умовні позначення:\n</b>"
        f"<i>{easyway_service.time_icons['gps']} = час за GPS</i>"
    )
    # =======================

    message = header + routes_text + footer
    keyboard = [[InlineKeyboardButton("⬅️ Пошук іншої зупинки", callback_data="accessible_start")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# handlers/accessible_transport_handlers.py

async def accessible_back_to_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Повертає користувача до списку знайдених зупинок
    (зі стану ACCESSIBLE_SHOWING_RESULTS).
    """
    query = update.callback_query
    await query.answer()

    # Дістаємо збережені результати пошуку
    places = context.user_data.get("search_results")

    if not places:
        # Якщо дані з якоїсь причини втрачено, просто повертаємось на старт
        logger.warning("No 'search_results' in user_data for accessible_back_to_list, returning to start.")

        # Викликаємо accessible_start, він сам впорається з редагуванням
        # і поверне правильний стан.
        return await accessible_start(update, context)

    # Використовуємо нашу універсальну функцію, щоб показати кнопки
    # (Ми оновимо _show_stops_keyboard у Кроці 6, щоб вона працювала з query)
    await _show_stops_keyboard(update, places)
    return States.ACCESSIBLE_SELECT_STOP


async def accessible_text_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    (НОВА ДОПОМІЖНА ФУНКЦІЯ)
    Скасування діалогу, якщо користувач просто пише текст, а не натискає кнопку.
    """
    await update.message.reply_text("❌ Пошук скасовано. Ви повернулись у головне меню.")
    await main_menu(update, context)  # Викликаємо головне меню
    return ConversationHandler.END


async def accessible_retry_manual_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повторює останній ручний пошук"""
    query = update.callback_query
    await query.answer()

    last_query = context.user_data.get('failed_search_query')
    if not last_query:
        await accessible_start(update, context)
        return States.ACCESSIBLE_SEARCH_STOP

    # Імітуємо повідомлення користувача
    # Ми викликаємо логіку пошуку, але передаємо текст вручну
    # Оскільки accessible_search_stop очікує message.text, нам простіше викликати сервіс напряму
    # і показати результат, використовуючи _show_stops_keyboard.

    await query.edit_message_text("🔄 Повторна спроба пошуку...")

    # ... ТУТ КОПІЯ ЛОГІКИ ПОШУКУ ...
    # Але щоб не дублювати код, найпростіше - попросити ввести ще раз або
    # використати існуючий accessible_stop_quick_search якщо ми сформуємо для нього callback

    # Найелегантніший варіант:
    # Викликаємо get_places_by_name напряму

    normalized_input = last_query.lower()
    # (Логіка синонімів та fuzzy search тут теж має бути,
    #  але можна взяти last_query як вже "сирий" ввід)

    # ... (Тут код fuzzy search з accessible_search_stop) ...
    # Для скорочення, припустимо ми беремо last_query як є, або додайте логіку fuzzy сюди.

    data = await easyway_service.get_places_by_name(search_term=last_query)

    if data.get("error"):
        # Знову помилка
        await query.edit_message_text(
            text="❌ Сервер все ще не відповідає. Спробуйте пізніше.",
            reply_markup=_get_error_keyboard("accessible_retry_manual"),
            parse_mode=ParseMode.HTML
        )
        return States.ACCESSIBLE_SEARCH_STOP

    places = data.get("stops", [])
    context.user_data["search_results"] = places

    # Використовуємо нашу універсальну функцію (вона працює з query)
    await _show_stops_keyboard(update, places)
    return States.ACCESSIBLE_SELECT_STOP


def _get_error_keyboard(retry_callback_data: str) -> InlineKeyboardMarkup:
    """Генерує клавіатуру для екрану помилки"""
    keyboard = [
        [InlineKeyboardButton("🔄 Повторити пошук зупинок", callback_data=retry_callback_data)],
        [InlineKeyboardButton("🚫 Скасувати пошук", callback_data="accessible_start")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)
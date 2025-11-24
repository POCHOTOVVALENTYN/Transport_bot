from handlers.menu_handlers import main_menu
from utils.logger import logger
import re
import asyncio
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler, Application
import telegram.error
from rapidfuzz import fuzz

# Імпорти сервісів
from bot.states import States
from services.easyway_service import easyway_service
from services.stop_matcher import stop_matcher

# === КОНФІГУРАЦІЯ ПОШУКУ ===

# Словник синонімів для покращення пошуку
SEARCH_SYNONYMS = {
    "музкомедія": "Театр Музкомедії",
    "вокзал": "Залізничний вокзал",
    "привоз": "Привоз",
    "новий ринок": "Новий ринок",
    "парк горького": "вул. Героїв Крут",
    "південний": "Ринок Південний",
    "тираспольська": "пл. Тираспільська",
    "дерев'янка": "пл. Бориса Дерев'янка",
    "площа дерев'янка": "пл. Бориса Дерев'янка",
    "обласна лікарня": "вул. Заболотного",
    "заболотного": "вул. Заболотного",
    "паустовського": "вул. 28-ї Бригади",
    "політех": "Політехнічний інститут",
    "філатова": "Інститут Філатова",
    "парк шевченка": "Парк ім. Тараса Шевченка",
    "парк победы": "Парк Перемоги",
    "старосіна": "пл. Старосінна",
    "пл. 10 апреля": "пл. 10 квітня",
    "алексеевская": "пл. Олексіївська"
}

FUZZY_SEARCH_THRESHOLD = 80


# === ФУНКЦІЯ ЗАВАНТАЖЕННЯ МАРШРУТІВ (Використовується в main.py) ===

async def load_easyway_route_ids(application: Application) -> bool:
    """Завантажує ID маршрутів при старті бота для подальшого mapping-у."""
    logger.info("Завантажую EasyWay Route ID...")
    data = await easyway_service.get_routes_list()

    if data.get("error"):
        logger.error(f"Не вдалося завантажити EasyWay Route IDs: {data['error']}")
        application.bot_data['easyway_structured_map'] = {"tram": [], "trolley": []}
        return False

    structured_route_map = {"tram": [], "trolley": []}
    route_list_from_api = data.get("routesList", {}).get("route", [])

    if not route_list_from_api:
        return False

    for route in route_list_from_api:
        route_key = route.get("transport")
        route_id = route.get("id")
        route_name = route.get("title")

        if not all([route_id, route_name, route_key]):
            continue

        route_obj = {"id": route_id, "name": route_name}

        if route_key == "tram":
            structured_route_map["tram"].append(route_obj)
        elif route_key == "trol":
            structured_route_map["trolley"].append(route_obj)

    application.bot_data['easyway_structured_map'] = structured_route_map
    logger.info(f"✅ EasyWay Route ID завантажено.")
    return True


# === ХЕНДЛЕРИ ПОШУКУ (Крок 1 і 2) ===

async def accessible_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Стартове меню пошуку низькопідлогового транспорту."""
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

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
    """Обробка текстового вводу назви зупинки."""
    user_id = update.effective_user.id
    original_input = update.message.text.strip()
    context.user_data['last_search_term'] = original_input

    # 1. Логіка синонімів та нечіткого пошуку
    normalized_input = original_input.lower()
    search_term = None

    if normalized_input in SEARCH_SYNONYMS:
        search_term = SEARCH_SYNONYMS[normalized_input]

    if not search_term:
        best_match_key = None
        best_score = 0
        for key in SEARCH_SYNONYMS.keys():
            score = fuzz.ratio(normalized_input, key)
            if score > best_score:
                best_score = score
                best_match_key = key

        if best_score >= FUZZY_SEARCH_THRESHOLD:
            search_term = SEARCH_SYNONYMS[best_match_key]

    if not search_term:
        search_term = original_input

    await update.message.chat.send_action("typing")

    try:
        data = await easyway_service.get_places_by_name(search_term=search_term)

        if data.get("error"):
            context.user_data['failed_search_query'] = original_input
            await update.message.reply_text(
                text="❌ <b>Помилка API-даних</b>\n\nСервер не відповів вчасно. Спробуємо ще раз.",
                reply_markup=_get_error_keyboard(retry_callback_data="accessible_retry_manual"),
                parse_mode=ParseMode.HTML
            )
            return States.ACCESSIBLE_SEARCH_STOP

        places = data.get("stops", [])
        if not places:
            await update.message.reply_text(
                f"❌ Зупинок не знайдено за запитом <b>'{search_term}'</b>.\nСпробуйте іншу назву.",
                parse_mode="HTML"
            )
            return States.ACCESSIBLE_SEARCH_STOP

        context.user_data["search_results"] = places
        await _show_stops_keyboard(update, places)
        return States.ACCESSIBLE_SELECT_STOP

    except Exception as e:
        logger.error(f"Error searching stops: {e}")
        await update.message.reply_text(f"❌ Помилка при пошуку: {str(e)}")
        return States.ACCESSIBLE_SEARCH_STOP


async def accessible_stop_quick_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пошук через кнопки популярних зупинок."""
    query = update.callback_query
    await query.answer()

    search_term = query.data.split("stop_search_")[-1]

    await query.edit_message_text(
        f"🔄 Пошук зупинок за терміном: <b>'{search_term}'</b>...",
        parse_mode="HTML"
    )

    try:
        data = await easyway_service.get_places_by_name(search_term=search_term)

        if data.get("error"):
            await query.edit_message_text(
                text="❌ <b>Помилка API-даних</b>",
                reply_markup=_get_error_keyboard(retry_callback_data=query.data),
                parse_mode=ParseMode.HTML
            )
            return States.ACCESSIBLE_SELECT_STOP

        places = data.get("stops", [])
        if not places:
            await query.edit_message_text(f"❌ Зупинок не знайдено.", parse_mode="HTML")
            return States.ACCESSIBLE_SEARCH_STOP

        context.user_data["search_results"] = places
        await _show_stops_keyboard(update, places)
        return States.ACCESSIBLE_SELECT_STOP

    except Exception as e:
        logger.error(f"Error in quick search: {e}")
        await query.edit_message_text(f"❌ Помилка: {str(e)}")
        return States.ACCESSIBLE_SEARCH_STOP


# === ЛОГІКА ВИБОРУ ЗУПИНКИ ТА ЗБОРУ ДАНИХ (Крок 3) ===

async def accessible_stop_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Основна логіка:
    1. Отримуємо StopInfo (Прибуття).
    2. Визначаємо маршрути.
    3. Паралельно скануємо кожен маршрут (RouteInfo) для отримання глобальної картини.
    """
    query = update.callback_query
    await query.answer()

    try:
        stop_id = int(query.data.split("stop_")[-1])
        user_id = query.from_user.id
        logger.info(f"User {user_id} selected stop_id: {stop_id} (Full Scan Mode)")

        await query.edit_message_text("🔄 Збираю інформацію про весь низькопідлоговий транспорт...")

        # --- ЕТАП 1: Отримуємо дані про зупинку та прибуття ---
        stop_info = await easyway_service.get_stop_info_v12(stop_id=stop_id)

        if stop_info.get("error"):
            await query.edit_message_text(f"❌ Помилка API-даних: {stop_info['error']}")
            return States.ACCESSIBLE_SEARCH_STOP

        stop_title = html.escape(stop_info.get("title", f"Зупинка {stop_id}"))

        # --- ЕТАП 2: Підготовка до глобального сканування ---
        # Отримуємо ID маршрутів з пам'яті бота для mapping (Назва -> ID)
        route_map = context.bot_data.get('easyway_structured_map', {})
        name_to_id = {}
        for kind in ['tram', 'trolley']:
            for r in route_map.get(kind, []):
                name_to_id[str(r['name'])] = r['id']

        # Визначаємо, які маршрути проходять через цю зупинку
        routes_to_scan = []  # Список кортежів (Назва, ID)

        for r in stop_info.get('routes', []):
            r_title = str(r.get('title', ''))
            # Шукаємо ID маршруту в нашій базі
            if r_title in name_to_id:
                r_id = name_to_id[r_title]
                # Уникаємо дублікатів
                if not any(x[1] == r_id for x in routes_to_scan):
                    routes_to_scan.append((r_title, r_id))

        # --- ЕТАП 3: Паралельне отримання даних по маршрутах ---
        # Створюємо список асинхронних завдань
        tasks = [easyway_service.get_vehicles_on_route(r_id) for _, r_id in routes_to_scan]

        # Виконуємо запити
        global_results = []
        if tasks:
            global_results = await asyncio.gather(*tasks)

        # Групуємо результати: { "5": [List of Vehicles], "28": [...] }
        global_route_data = {}
        for i, (r_name, _) in enumerate(routes_to_scan):
            # Якщо результат є, зберігаємо його
            vehicles = global_results[i] if i < len(global_results) else []
            global_route_data[r_name] = vehicles

        # --- ЕТАП 4: Передача на рендеринг ---
        await _render_accessible_response(query, stop_title, stop_info, global_route_data)

        return States.ACCESSIBLE_SHOWING_RESULTS

    except telegram.error.BadRequest as br_error:
        # Часто буває "Message is not modified", ігноруємо
        logger.warning(f"BadRequest in accessible_stop_selected: {br_error}")
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Critical error in accessible_stop_selected: {e}", exc_info=True)
        try:
            await query.edit_message_text(
                f"❌ Критична помилка: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]])
            )
        except:
            pass
        return States.ACCESSIBLE_SEARCH_STOP


# === ЛОГІКА ВІДОБРАЖЕННЯ (Крок 4) ===

async def _render_accessible_response(query, stop_title: str, stop_info: dict, global_route_data: dict):
    """
    Формує повідомлення згідно з шаблоном:
    Header -> Loop (Summary -> Nearest -> Others) -> Footer
    """

    # 1. HEADER (Шапка)
    message = (
        f"♿️ <b>Низькопідлоговий Транспорт</b>\n"
        f"📍 Зупинка: <b>{stop_title}</b>\n"
        f"🚊— ─ ─ ─ ─ ─ ─ ─ ─ 🚎\n"
        f"👋 Шановні пасажари!\n"
        f"⏱️ Інформація про час прибуття\n\n"
        f"⚠️дійсна на момент запиту⚠️\n\n"
        f"📢 <b>Важливо!</b>\n"
        f"⚠️ Під час <b>повітряної тривоги</b> 🚨 дані про рух трамваїв та тролейбусів можуть відображатися "
        f"некоректно або із затримкою. 📡\n\n"
        f"🚊— ─ ─ ─ ─ ─ ─ ─ ─ 🚎\n"
    )

    # 2. ПІДГОТОВКА ДАНИХ
    # Отримуємо тільки низькопідлогові прибуття (Arrivals)
    handicapped_arrivals = easyway_service.filter_handicapped_routes(stop_info)

    # Групуємо прибуття по маршруту: { "5": [ArrivalObj1, ...] }
    arrivals_by_route = {}
    for arr in handicapped_arrivals:
        r_title = str(arr.get('title'))
        if r_title not in arrivals_by_route:
            arrivals_by_route[r_title] = []
        arrivals_by_route[r_title].append(arr)

    # Створюємо спільний список маршрутів для сортування
    all_routes = set(global_route_data.keys()) | set(arrivals_by_route.keys())
    # Сортуємо: спочатку числа, потім літери (напр. 5, 10, 28, А)
    sorted_routes = sorted(list(all_routes), key=lambda x: int(re.sub(r'\D', '', x)) if re.sub(r'\D', '', x) else 999)

    has_any_data = False

    # 3. ЦИКЛ ПО МАРШРУТАХ
    for r_name in sorted_routes:
        # Дані
        global_vehicles = global_route_data.get(r_name, [])  # Всі вагони на лінії
        arrivals = arrivals_by_route.get(r_name, [])  # Ті, що прибувають

        # Рахуємо загальну кількість
        # (Оскільки global_vehicles відфільтровані сервісом як низькопідлогові)
        count = len(global_vehicles)

        # Якщо API прибуття каже щось є, а в глобальному 0 (лаг) - віримо прибуттю
        if count == 0 and len(arrivals) > 0:
            count = len(arrivals)

        if count == 0:
            continue  # Пропускаємо маршрути без низькопідлогових вагонів

        has_any_data = True

        # -- Рядок зведення --
        suffix = "ів"
        if count == 1:
            suffix = ""
        elif 2 <= count <= 4:
            suffix = "и"

        message += f"На маршруті №{r_name}: на лінії <b>{count}</b> низькопідлогов{html.escape('ий' if count == 1 else 'і')} вагон{suffix}.\n"

        # -- Блок "НАЙБЛИЖЧИЙ ДО ВАС" --
        nearest_bort = None

        if arrivals:
            nearest = arrivals[0]  # Найближчий за часом
            nearest_bort = str(nearest.get('bort_number'))

            icon = easyway_service.get_transport_icon(nearest.get("transport_key"))
            time_icon = easyway_service.get_time_source_icon(nearest.get("time_source"))

            message += "👇 НАЙБЛИЖЧИЙ ДО ВАС:\n"
            message += (
                f"   {icon} {html.escape(nearest.get('transport_name', 'Транспорт'))} №{r_name}\n"
                f"   → (напрямок: {html.escape(nearest.get('direction', 'Невідомо'))})\n"
                f"   Борт: <b>{html.escape(nearest_bort)}</b>\n"
                f"   Прибуття: {time_icon} <b>{html.escape(nearest.get('time_left_formatted', '??'))}</b>\n"
            )

        # -- Блок "ІНШІ НА ЛІНІЇ" --
        # Показуємо ті вагони з global_vehicles, які не є "найближчим"
        other_vehicles = []
        for v in global_vehicles:
            v_bort = str(v.get('bort', ''))
            # Якщо цей вагон вже показаний як найближчий - пропускаємо
            if nearest_bort and v_bort == nearest_bort:
                continue
            other_vehicles.append(v)

        if other_vehicles:
            if arrivals:
                message += "👇 ІНШІ НА ЛІНІЇ:\n"
            else:
                # Якщо прибуття немає, але вагони є
                message += "👇 НА ЛІНІЇ (далеко або інший напрямок):\n"

            for v in other_vehicles:
                v_bort = html.escape(str(v.get('bort', 'Б/н')))

                # Геокодування (Координати -> Назва зупинки)
                lat, lng = v.get('lat'), v.get('lng')
                loc_name = "Локація невідома"
                if lat and lng:
                    loc_name = stop_matcher.find_nearest_stop_name(lat, lng)

                message += f"   🚋 - № <b>{v_bort}</b> (біля: <i>{html.escape(loc_name)}</i>)\n"

        message += "\n"  # Відступ між маршрутами

    # 4. FOOTER (Підвал)
    if not has_any_data:
        message += "😕 На жаль, на маршрутах через цю зупинку наразі не виявлено низькопідлогових вагонів.\n\n"

    message += (
        "🚊— ─ ─ ─ ─ ─ ─ ─ ─ 🚎\n"
        "Умовні позначення:\n"
        f"{easyway_service.time_icons['gps']} = час за GPS\n"
    )

    # Обрізка повідомлення (ліміт Telegram 4096 символів)
    if len(message) > 4000:
        message = message[:3900] + "\n\n...(повідомлення скорочено)..."

    # Клавіатура
    keyboard = [
        [InlineKeyboardButton("🔄 Оновити дані", callback_data=f"stop_{query.data.split('_')[-1]}")],
        [InlineKeyboardButton("⬅️ До списку зупинок", callback_data="accessible_back_to_list")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text=message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


# === ДОПОМІЖНІ ХЕНДЛЕРИ ===

async def _show_stops_keyboard(update: Update, places: list):
    """Відображає список знайдених зупинок (для Кроку 2)."""
    keyboard = []
    for place in places[:10]:
        title = place['title']
        summary = place.get('routes_summary')
        button_text = f"📍 {title}"
        if summary:
            button_text += f"\n{summary}"

        if len(button_text) > 50:
            button_text = button_text[:47] + "..."

        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"stop_{place['id']}")])

    keyboard.append([InlineKeyboardButton("⬅️ Назад до пошуку", callback_data="accessible_start")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = (
        "✅ Знайдено!\nОберіть точну зупинку зі списку: \n"
        " <b>💡Підказка:</b> Щоб отримати інформацію про <b>\n\n🧭НАПРЯМОК  РУХУ🧭</b> \n"
        "(<i>напр., \"→ у бік пл. Тираспольська\"</i>) "
        "та час прибуття ⏱️ "
        " \n\n<b>👇НАТИСНІТЬ НА ЗУПИНКУ👇</b> "
    )

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text=message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
    else:
        await update.message.reply_text(
            text=message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
        )


async def accessible_back_to_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повернення до списку зупинок."""
    query = update.callback_query
    await query.answer()

    places = context.user_data.get("search_results")
    if not places:
        return await accessible_start(update, context)

    await _show_stops_keyboard(update, places)
    return States.ACCESSIBLE_SELECT_STOP


async def accessible_text_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування текстовим вводом."""
    await update.message.reply_text("❌ Пошук скасовано.")
    await main_menu(update, context)
    return ConversationHandler.END


async def accessible_retry_manual_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повторний пошук при помилці."""
    query = update.callback_query
    await query.answer()

    last_query = context.user_data.get('failed_search_query')
    if not last_query:
        await accessible_start(update, context)
        return States.ACCESSIBLE_SEARCH_STOP

    await query.edit_message_text("🔄 Повторна спроба пошуку...")

    data = await easyway_service.get_places_by_name(search_term=last_query)
    if data.get("error"):
        await query.edit_message_text(
            text="❌ Сервер все ще не відповідає.",
            reply_markup=_get_error_keyboard("accessible_retry_manual"),
            parse_mode=ParseMode.HTML
        )
        return States.ACCESSIBLE_SEARCH_STOP

    places = data.get("stops", [])
    context.user_data["search_results"] = places
    await _show_stops_keyboard(update, places)
    return States.ACCESSIBLE_SELECT_STOP


def _get_error_keyboard(retry_callback_data: str) -> InlineKeyboardMarkup:
    """Генерує клавіатуру для повідомлення про помилку."""
    keyboard = [
        [InlineKeyboardButton("🔄 Повторити пошук зупинок", callback_data=retry_callback_data)],
        [InlineKeyboardButton("🚫 Скасувати пошук", callback_data="accessible_start")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)
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

from bot.states import States
from services.easyway_service import easyway_service
from services.stop_matcher import stop_matcher

# === КОНФІГУРАЦІЯ ПОШУКУ ===

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


# === ЗАВАНТАЖЕННЯ ДАНИХ ===

async def load_easyway_route_ids(application: Application) -> bool:
    """Завантажує ID маршрутів та зберігає їх у bot_data."""
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
        route_name = str(route.get("title", "")).strip()

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


# === ХЕНДЛЕРИ ПОШУКУ ===

async def accessible_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "👇 ...або оберіть варіант з популярних нижче:"
    )
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="HTML")
    return States.ACCESSIBLE_SEARCH_STOP


async def accessible_search_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    original_input = update.message.text.strip()
    context.user_data['last_search_term'] = original_input

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
                text="❌ <b>Помилка API</b>\nСервер не відповів вчасно.",
                reply_markup=_get_error_keyboard(retry_callback_data="accessible_retry_manual"),
                parse_mode=ParseMode.HTML
            )
            return States.ACCESSIBLE_SEARCH_STOP

        places = data.get("stops", [])
        if not places:
            await update.message.reply_text(
                f"❌ Зупинок не знайдено за запитом <b>'{search_term}'</b>.",
                parse_mode="HTML"
            )
            return States.ACCESSIBLE_SEARCH_STOP

        context.user_data["search_results"] = places
        await _show_stops_keyboard(update, places)
        return States.ACCESSIBLE_SELECT_STOP

    except Exception as e:
        logger.error(f"Error searching stops: {e}")
        await update.message.reply_text(f"❌ Помилка: {str(e)}")
        return States.ACCESSIBLE_SEARCH_STOP


async def accessible_stop_quick_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    search_term = query.data.split("stop_search_")[-1]

    await query.edit_message_text(f"🔄 Пошук: <b>'{search_term}'</b>...", parse_mode="HTML")

    try:
        data = await easyway_service.get_places_by_name(search_term=search_term)

        if data.get("error"):
            await query.edit_message_text(
                text="❌ <b>Помилка API</b>",
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


# === ГОЛОВНА ЛОГІКА (Крок 3: Збір даних) ===

async def accessible_stop_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        stop_id = int(query.data.split("stop_")[-1])
        logger.info(f"User {query.from_user.id} selected stop_id: {stop_id}")

        await query.edit_message_text("🔄 Сканую маршрути на наявність низькопідлогових вагонів...")

        # 1. Отримуємо інфо про зупинку
        stop_info = await easyway_service.get_stop_info_v12(stop_id=stop_id)

        if stop_info.get("error"):
            await query.edit_message_text(f"❌ Помилка API: {stop_info['error']}")
            return States.ACCESSIBLE_SEARCH_STOP

        stop_title = html.escape(stop_info.get("title", f"Зупинка {stop_id}"))

        # 2. Визначаємо маршрути для сканування + ЇХ ТИП (Трам/Трол)
        route_map = context.bot_data.get('easyway_structured_map', {})
        name_to_id = {}
        # Зберігаємо також тип транспорту в мапу: "5" -> {"id": 113, "type": "tram"}
        name_meta = {}

        for kind in ['tram', 'trolley']:
            transport_type_code = 'tram' if kind == 'tram' else 'trol'
            for r in route_map.get(kind, []):
                clean_name = str(r['name']).strip()
                name_to_id[clean_name] = r['id']
                name_meta[clean_name] = transport_type_code

        routes_to_scan = []  # Список кортежів: (Назва, ID, Тип)

        # Проходимо по маршрутах зупинки
        for r in stop_info.get('routes', []):
            r_title = str(r.get('title', '')).strip()
            r_id = r.get('id')

            # Спроба знайти ID
            if not r_id or int(r_id) == 0:
                if r_title in name_to_id:
                    r_id = name_to_id[r_title]
                else:
                    continue

                    # Визначаємо тип транспорту (для іконки)
            transport_key = r.get('transportKey')  # API може дати 'tram', 'trol'

            # Якщо API не дало ключа (буває), беремо з нашої бази
            if not transport_key and r_title in name_meta:
                transport_key = name_meta[r_title]

            # Нормалізація типу для подальшого використання
            if transport_key == 'trolley': transport_key = 'trol'

            is_electric = (transport_key in ['tram', 'trol'])

            if is_electric:
                # Уникаємо дублікатів
                if not any(x[1] == r_id for x in routes_to_scan):
                    routes_to_scan.append((r_title, r_id, transport_key))

        # 3. Скануємо маршрути (Паралельно)
        tasks = [easyway_service.get_vehicles_on_route(r_id) for _, r_id, _ in routes_to_scan]

        global_results = []
        if tasks:
            global_results = await asyncio.gather(*tasks)

        # Групуємо результати
        global_route_data = {}
        # Зберігаємо метадані про типи маршрутів для рендерингу
        routes_meta_info = {}

        for i, (r_name, r_id, r_type) in enumerate(routes_to_scan):
            vehicles = global_results[i] if i < len(global_results) else []
            global_route_data[r_name] = vehicles
            routes_meta_info[r_name] = r_type

        # 4. Показуємо результат
        await _render_accessible_response(query, stop_title, stop_info, global_route_data, routes_meta_info)

        return States.ACCESSIBLE_SHOWING_RESULTS

    except telegram.error.BadRequest:
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in accessible_stop_selected: {e}", exc_info=True)
        try:
            await query.edit_message_text(f"❌ Помилка: {str(e)}")
        except:
            pass
        return States.ACCESSIBLE_SEARCH_STOP


# === ЛОГІКА ВІДОБРАЖЕННЯ (Крок 4) ===

async def _render_accessible_response(query, stop_title: str, stop_info: dict, global_route_data: dict,
                                      routes_meta: dict):
    """
    Формує повідомлення з "Розумною тишею" (No spam if success).
    """

    message = (
        f"♿️ <b>Низькопідлоговий Транспорт</b>\n"
        f"📍 Зупинка: <b>{stop_title}</b>\n"
        f"🚊— ─ ─ ─ ─ ─ ─ ─ ─ 🚎\n"
        f"👋 Шановні пасажари!\n"
        f"⏱️ Інформація про час прибуття\n\n"
        f"⚠️дійсна на момент запиту⚠️\n\n"
        f"📢 <b>Важливо!</b>\n"
        f"⚠️ Під час <b>повітряної тривоги</b> 🚨 дані можуть відображатися некоректно. 📡\n\n"
        f"🚊— ─ ─ ─ ─ ─ ─ ─ ─ 🚎\n"
    )

    # Групуємо прибуття
    handicapped_arrivals = easyway_service.filter_handicapped_routes(stop_info)
    arrivals_by_route = {}
    for arr in handicapped_arrivals:
        r_title = str(arr.get('title')).strip()
        if r_title not in arrivals_by_route:
            arrivals_by_route[r_title] = []
        arrivals_by_route[r_title].append(arr)

    # Сортуємо маршрути
    all_routes = set(global_route_data.keys()) | set(arrivals_by_route.keys())
    sorted_routes = sorted(list(all_routes), key=lambda x: int(re.sub(r'\D', '', x)) if re.sub(r'\D', '', x) else 999)

    has_data = False

    for r_name in sorted_routes:
        global_vehicles = global_route_data.get(r_name, [])
        arrivals = arrivals_by_route.get(r_name, [])

        # Визначаємо тип транспорту та іконку
        r_type = routes_meta.get(r_name, 'tram')  # Default to tram
        # Якщо в метаданих немає, пробуємо взяти з arrival
        if not r_type and arrivals:
            r_type = arrivals[0].get('transport_key', 'tram')

        icon = '🚎' if r_type == 'trol' else '🚋'
        transport_name = 'Тролейбус' if r_type == 'trol' else 'Трамвай'

        # Підрахунок для Fallback сценарію
        unique_borts = set()
        for arr in arrivals:
            if arr.get('bort_number'): unique_borts.add(str(arr.get('bort_number')))
        for gv in global_vehicles:
            if gv.get('bort'): unique_borts.add(str(gv.get('bort')))
        total_count = len(unique_borts)

        # Пропускаємо маршрути, де взагалі пусто
        if total_count == 0:
            # Вимога: Показати, що не виявлено
            message += f"❌ <b>Маршрут №{r_name}:</b> низькопідлогові на лінії не виявлені.\n\n"
            has_data = True  # Технічно ми показали дані (відсутність)
            continue

        has_data = True

        # === ЛОГІКА ВІДОБРАЖЕННЯ (BRANCHING) ===

        # СЦЕНАРІЙ А: Успішне прибуття
        if arrivals:
            # Тільки заголовок, без кількості на лінії
            message += f"✅ <b>Маршрут №{r_name}:</b>\n"

            # Блок "Найближчий"
            nearest = arrivals[0]
            nearest_bort = str(nearest.get('bort_number'))
            time_icon = easyway_service.get_time_source_icon(nearest.get("time_source"))

            message += "👇 НАЙБЛИЖЧИЙ ДО ВАС:\n"
            message += (
                f"   {icon} {transport_name} №{r_name}\n"
                f"   → (напрямок: {html.escape(nearest.get('direction', 'Невідомо'))})\n"
                f"   Борт: <b>{html.escape(nearest_bort)}</b>\n"
                f"   Прибуття: {time_icon} <b>{html.escape(nearest.get('time_left_formatted', '??'))}</b>\n"
            )

            # Блок "Інші" (якщо є)
            other_vehicles_to_show = []
            shown_borts = {nearest_bort}

            # Збираємо з Global
            for v in global_vehicles:
                v_bort = str(v.get('bort', ''))
                if v_bort and v_bort not in shown_borts:
                    other_vehicles_to_show.append(v)
                    shown_borts.add(v_bort)

            # Збираємо решту з Arrivals
            for arr in arrivals:
                v_bort = str(arr.get('bort_number', ''))
                if v_bort and v_bort not in shown_borts:
                    other_vehicles_to_show.append({
                        'bort': v_bort,
                        'is_arrival_fallback': True,
                        'direction': arr.get('direction')
                    })
                    shown_borts.add(v_bort)

            if other_vehicles_to_show:
                message += "👇 ІНШІ НА ЛІНІЇ:\n"
                for v in other_vehicles_to_show:
                    v_bort = html.escape(str(v.get('bort', 'Б/н')))

                    loc_str = ""
                    if v.get('is_arrival_fallback'):
                        direction = html.escape(v.get('direction', ''))
                        loc_str = f"(напрямок: {direction})"
                    else:
                        lat, lng = v.get('lat'), v.get('lng')
                        if lat and lng:
                            loc_name = stop_matcher.find_nearest_stop_name(lat, lng)
                            loc_str = f"(біля: <i>{html.escape(loc_name)}</i>)"
                        else:
                            loc_str = "(локація невідома)"

                    message += f"   {icon} - № <b>{v_bort}</b> {loc_str}\n"

        # СЦЕНАРІЙ Б: Прибуття немає, але вагони на лінії Є (Fallback)
        elif not arrivals and total_count > 0:

            suffix = "ів"
            if total_count == 1:
                suffix = ""
            elif 2 <= total_count <= 4:
                suffix = "и"

            # Тут ми ПОКАЗУЄМО кількість, бо це єдина надія користувача
            # "Зараз на маршруті 1 низькопідлоговий трамвай..."
            message += f"⚠️ <b>Маршрут №{r_name}:</b>\n"
            message += f"Зараз на маршруті <b>{total_count}</b> низькопідлогов{html.escape('ий' if total_count == 1 else 'і')} {transport_name.lower()}{suffix}:\n"

            for v in global_vehicles:
                v_bort = html.escape(str(v.get('bort', 'Б/н')))
                lat, lng = v.get('lat'), v.get('lng')

                loc_str = ""
                if lat and lng:
                    loc_name = stop_matcher.find_nearest_stop_name(lat, lng)
                    loc_str = f"(біля: <i>{html.escape(loc_name)}</i>)"
                else:
                    loc_str = "(локація невідома)"

                message += f"   {icon} - № <b>{v_bort}</b> {loc_str}\n"

        message += "\n"  # Відступ між маршрутами

    # Підвал
    if not has_data:
        message += "😕 Інформація про маршрути на цій зупинці тимчасово недоступна.\n\n"

    message += (
        "🚊— ─ ─ ─ ─ ─ ─ ─ ─ 🚎\n"
        "Умовні позначення:\n"
        f"{easyway_service.time_icons['gps']} = час за GPS\n"
    )

    if len(message) > 4000:
        message = message[:3900] + "\n\n...(повідомлення скорочено)..."

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


# === ДОПОМІЖНІ ФУНКЦІЇ ===

async def _show_stops_keyboard(update: Update, places: list):
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
    message_text = "✅ Знайдено!\nОберіть точну зупинку зі списку:"

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text=message_text, reply_markup=reply_markup,
                                                          parse_mode=ParseMode.HTML)
        except Exception:
            pass
    else:
        await update.message.reply_text(text=message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def accessible_back_to_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    places = context.user_data.get("search_results")
    if not places: return await accessible_start(update, context)
    await _show_stops_keyboard(update, places)
    return States.ACCESSIBLE_SELECT_STOP


async def accessible_text_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Пошук скасовано.")
    await main_menu(update, context)
    return ConversationHandler.END


async def accessible_retry_manual_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    last_query = context.user_data.get('failed_search_query')
    if not last_query:
        await accessible_start(update, context)
        return States.ACCESSIBLE_SEARCH_STOP

    await query.edit_message_text("🔄 Повторна спроба пошуку...")
    data = await easyway_service.get_places_by_name(search_term=last_query)
    if data.get("error"):
        await query.edit_message_text(text="❌ Сервер не відповідає.",
                                      reply_markup=_get_error_keyboard("accessible_retry_manual"),
                                      parse_mode=ParseMode.HTML)
        return States.ACCESSIBLE_SEARCH_STOP

    places = data.get("stops", [])
    context.user_data["search_results"] = places
    await _show_stops_keyboard(update, places)
    return States.ACCESSIBLE_SELECT_STOP


def _get_error_keyboard(retry_callback_data: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🔄 Повторити пошук", callback_data=retry_callback_data)],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="accessible_start")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)
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
from services.gtfs_service import gtfs_service


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
    """
    Крок 3: Отримання даних.
    ВИПРАВЛЕНО: Примусово використовуємо Головний ID маршруту для пошуку GPS.
    """
    query = update.callback_query
    await query.answer()

    try:
        stop_id = int(query.data.split("stop_")[-1])
        logger.info(f"User {query.from_user.id} selected stop_id: {stop_id}")

        await query.edit_message_text("🔄 Сканую маршрути та шукаю транспорт...")

        # 1. Отримуємо дані про зупинку
        stop_info = await easyway_service.get_stop_info_v12(stop_id=stop_id)

        if stop_info.get("error"):
            await query.edit_message_text(f"❌ Помилка API: {stop_info['error']}")
            return States.ACCESSIBLE_SEARCH_STOP

        stop_title = html.escape(stop_info.get("title", f"Зупинка {stop_id}"))

        # 2. Підготовка мапи Головних ID (з main.py)
        # Це наша база знань: "Маршрут 28" -> ID 123 (де є GPS)
        route_map = context.bot_data.get('easyway_structured_map', {})
        name_to_main_id = {}
        name_meta = {}

        # Створюємо словник: "28" -> 309 (головний ID)
        for kind in ['tram', 'trolley']:
            transport_type_code = 'tram' if kind == 'tram' else 'trol'
            for r in route_map.get(kind, []):
                clean_name = str(r['name']).strip()
                name_to_main_id[clean_name] = r['id']
                name_meta[clean_name] = transport_type_code

        routes_to_scan = []
        seen_route_names = set()

        # 3. Перебираємо маршрути, які проходять через цю зупинку
        found_routes = stop_info.get('routes', [])
        if not found_routes:
            logger.warning(f"Stop {stop_id} returned NO routes structure.")

        for r in found_routes:
            r_title = str(r.get('title', '')).strip()
            local_id = r.get('id')
            r_direction = r.get('direction')

            # --- ГОЛОВНА ЗМІНА ---
            # Ми шукаємо Головний ID для цієї назви маршруту.
            # Якщо він є в нашій базі - беремо його. Якщо ні - беремо той, що дала зупинка.
            target_id = name_to_main_id.get(r_title, local_id)

            # Визначаємо тип
            transport_key = r.get('transportKey')
            if not transport_key and r_title in name_meta:
                transport_key = name_meta[r_title]

            # Нормалізуємо 'trolley' -> 'trol'
            if transport_key == 'trolley': transport_key = 'trol'

            # Перевіряємо, чи це електротранспорт
            is_electric = (transport_key in ['tram', 'trol'])

            # Додаємо до сканування, якщо ще не додавали цю назву
            # (щоб не сканувати один маршрут двічі, якщо зупинка дає дублі)
            if is_electric and r_title not in seen_route_names:
                # Логуємо, щоб бачити в консолі, що відбувається
                logger.info(f"🔎 Scanning Route: {r_title} (Main ID: {target_id}, Local ID: {local_id})")

                routes_to_scan.append((r_title, target_id, transport_key, r_direction))
                seen_route_names.add(r_title)

        # 4. Скануємо GPS (паралельно)
        # Використовуємо target_id, який має бути Головним
        tasks = [easyway_service.get_vehicles_on_route(r_id) for _, r_id, _, _ in routes_to_scan]

        global_results = []
        if tasks:
            global_results = await asyncio.gather(*tasks)

        # 5. Групуємо результати
        global_route_data = {}
        routes_meta_info = {}

        for i, (r_name, r_id, r_type, target_dir) in enumerate(routes_to_scan):
            raw_vehicles = global_results[i] if i < len(global_results) else []

            # Лог кількості знайдених машин
            if len(raw_vehicles) > 0:
                logger.info(f"✅ Found {len(raw_vehicles)} vehicles on route {r_name}")

            global_route_data[r_name] = raw_vehicles
            routes_meta_info[r_name] = {'type': r_type, 'stop_direction': target_dir}

        # 6. Рендеримо відповідь
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
    Формує повідомлення. Тепер показує ВЕСЬ транспорт на лінії у "Сценарії Б".
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

    # 1. Обробляємо прибуття
    handicapped_arrivals = easyway_service.filter_handicapped_routes(stop_info)
    arrivals_by_route = {}
    for arr in handicapped_arrivals:
        r_title = str(arr.get('title')).strip()
        if r_title not in arrivals_by_route:
            arrivals_by_route[r_title] = []
        arrivals_by_route[r_title].append(arr)

    # 2. Складаємо повний список маршрутів
    all_routes = set(global_route_data.keys()) | set(arrivals_by_route.keys())
    sorted_routes = sorted(list(all_routes), key=lambda x: int(re.sub(r'\D', '', x)) if re.sub(r'\D', '', x) else 999)

    has_data = False

    for r_name in sorted_routes:
        global_vehicles = global_route_data.get(r_name, [])
        arrivals = arrivals_by_route.get(r_name, [])
        r_meta = routes_meta.get(r_name, {})

        # Наш напрямок (напрямок зупинки)
        target_dir = r_meta.get('stop_direction')

        r_type = r_meta.get('type', 'tram')
        if not r_type and arrivals: r_type = arrivals[0].get('transport_key', 'tram')

        icon = '🚎' if r_type == 'trol' else '🚋'
        transport_name = 'Тролейбус' if r_type == 'trol' else 'Трамвай'

        unique_borts = set()
        for arr in arrivals:
            if arr.get('bort_number'): unique_borts.add(str(arr.get('bort_number')))

        # Рахуємо всі машини з GPS, навіть якщо борт не розпізнано
        gps_count = 0
        for gv in global_vehicles:
            bort = str(gv.get('bort') or '').strip()
            if bort:
                unique_borts.add(bort)
            gps_count += 1

        # Якщо є хоч якісь дані (прогноз або GPS), то count > 0
        total_count = len(unique_borts)
        if total_count == 0 and gps_count > 0:
            total_count = gps_count  # Фоллбек, якщо бортів немає, але машини є

        has_data = True

        # === ЛОГІКА ВІДОБРАЖЕННЯ ===

        # Якщо ВЗАГАЛІ нікого немає
        if total_count == 0:
            message += (
                f"⚠️ <b>Маршрут №{r_name}:</b>\n"
                f"На жаль, інформація про найближчий низькопідлоговий транспорт наразі відсутня 🤷‍♂️\n\n"
                f"🔍 <b>Можливі причини:</b>\n"
                f"▫️ Транспорт вже проїхав Вашу зупинку 💨\n"
                f"▫️ Вагон/тролейбус знаходиться на кінцевій та ще не розпочав рух 🏁\n\n"
            )
            continue

        # СЦЕНАРІЙ А: Є ПРОГНОЗ ПРИБУТТЯ
        if arrivals:
            message += f"✅ <b>Маршрут №{r_name}:</b>\n"
            nearest = arrivals[0]
            nearest_bort = str(nearest.get('bort_number'))
            time_icon = easyway_service.get_time_source_icon(nearest.get("time_source"))
            direction_str = html.escape(nearest.get('direction_title') or nearest.get('direction', 'Невідомо'))

            message += "👇 НАЙБЛИЖЧИЙ ДО ВАС:\n"
            message += (
                f"   {icon} {transport_name} №{r_name}\n"
                f"   → (напрямок: {direction_str})\n"
                f"   Борт: <b>{html.escape(nearest_bort)}</b>\n"
                f"   Прибуття: {time_icon} <b>{html.escape(nearest.get('time_left_formatted', '??'))}</b>\n\n"
            )

        # СЦЕНАРІЙ Б: НЕМАЄ ПРОГНОЗУ, АЛЕ Є ТРАНСПОРТ (Включаючи зустрічний)
        elif not arrivals and total_count > 0:
            message += f"⚠️ <b>Маршрут №{r_name}:</b>\n"
            message += f"На маршруті працює <b>{total_count}</b> од. низькопідлогового транспорту:\n"

            for v in global_vehicles:
                v_bort = html.escape(str(v.get('bort', 'Б/н')))
                raw_id = str(v.get('raw_id', ''))

                # Якщо номер довгий (4+ цифри для Одеси це зазвичай ID) і не схожий на звичайний борт
                # І при цьому він співпадає з raw_id (тобто ми не зробили заміну по мапінгу)
                if len(v_bort) > 4 and v_bort == raw_id:
                    display_label = f"ID трекера: {v_bort}"
                else:
                    display_label = f"№ <b>{v_bort}</b>"

                lat, lng = v.get('lat'), v.get('lng')
                v_dir = v.get('direction')

                # === НОВА ЛОГІКА ЛОКАЦІЇ ===
                loc_str = "місцезнаходження невідоме"
                stop_name = None

                if lat and lng:
                    # Передаємо r_type!
                    stop_name = gtfs_service.get_closest_stop_name(r_name, r_type, v_dir, lat, lng)

                    if not stop_name:
                        stop_name = stop_matcher.find_nearest_stop_name(lat, lng)

                    if stop_name:
                        loc_str = f"біля: {html.escape(stop_name)}"
                # ============================
                # Напрямок
                dir_info = ""
                if target_dir is not None and v_dir is not None:
                    if v_dir == target_dir:
                        dir_info = " (✅ попутний)"
                    else:
                        dir_info = " (↩️ зустрічний)"
                else:
                    dir_icon = "▶️" if v_dir == 1 else "◀️"
                    dir_info = f" (напр. {dir_icon})"

                message += f"▫️ {display_label} - {loc_str}{dir_info}\n"

            message += "\n"

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
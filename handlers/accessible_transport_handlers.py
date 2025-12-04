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
    # 1. Зберігаємо ID поточного повідомлення перед очищенням (або відновлюємо після)
    msg_id = query.message.message_id
    context.user_data.clear()
    context.user_data['main_message_id'] = msg_id  # <--- ЗБЕРІГАЄМО ID

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
        "📝 Будь ласка, <b>напишіть назву зупинки</b> (<b>державною мовою</b> 🇺🇦).\n\n"
        "👇 ...або оберіть варіант з популярних нижче:"
    )
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="HTML")
    return States.ACCESSIBLE_SEARCH_STOP


async def accessible_search_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    original_input = update.message.text.strip()

    # --- ЛОГІКА "ЧИСТОГО ЧАТУ" ---
    # 1. Видаляємо повідомлення, яке написав користувач
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete user message: {e}")

    # 2. Отримуємо ID головного повідомлення бота, яке ми будемо редагувати
    main_msg_id = context.user_data.get('main_message_id')
    chat_id = update.effective_chat.id

    # Якщо ID втрачено (наприклад, перезапуск бота), шлемо нове і зберігаємо його
    if not main_msg_id:
        msg = await update.message.reply_text("🔄 Обробка запиту...")
        main_msg_id = msg.message_id
        context.user_data['main_message_id'] = main_msg_id

    # Допоміжна функція для редагування (щоб не дублювати код)
    async def edit_root_message(text, reply_markup=None):
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=main_msg_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except telegram.error.BadRequest as e:
            # Якщо повідомлення не знайдено або не змінилося - ігноруємо або шлемо нове
            logger.error(f"Failed to edit message: {e}")
            if "Message to edit not found" in str(e):
                msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup,
                                                     parse_mode=ParseMode.HTML)
                context.user_data['main_message_id'] = msg.message_id

    # --- КІНЕЦЬ ЛОГІКИ "ЧИСТОГО ЧАТУ" ---

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

    # Використовуємо send_chat_action, щоб показати "друкує..." без надсилання повідомлення
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        data = await easyway_service.get_places_by_name(search_term=search_term)

        if data.get("error"):
            context.user_data['failed_search_query'] = original_input

            # ЗАМІНА reply_text НА edit_root_message
            await edit_root_message(
                text="❌ <b>Помилка API</b>\nСервер не відповів вчасно.",
                reply_markup=_get_error_keyboard(retry_callback_data="accessible_retry_manual")
            )
            return States.ACCESSIBLE_SEARCH_STOP

        places = data.get("stops", [])
        if not places:
            # ЗАМІНА reply_text НА edit_root_message
            await edit_root_message(
                text=f"❌ Зупинок не знайдено за запитом <b>'{search_term}'</b>.\nСпробуйте ще раз або поверніться назад.",
                reply_markup=_get_error_keyboard(retry_callback_data="accessible_start")
                # Тут можна дати кнопку повернення
            )
            return States.ACCESSIBLE_SEARCH_STOP

        context.user_data["search_results"] = places

        # Оновлюємо виклик клавіатури, передаючи main_msg_id
        await _show_stops_keyboard(update, places, context)  # <-- Зверніть увагу, ми змінили сигнатуру функції
        return States.ACCESSIBLE_SELECT_STOP

    except Exception as e:
        logger.error(f"Error searching stops: {e}")
        await edit_root_message(text=f"❌ Помилка: {str(e)}")
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

        # 2. Підготовка мапи Головних ID
        name_to_main_id = {}
        route_map = context.bot_data.get('easyway_structured_map', {})

        for kind in ['tram', 'trolley']:
            transport_type_code = 'tram' if kind == 'tram' else 'trol'
            for r in route_map.get(kind, []):
                clean_name = str(r['name']).strip()
                name_to_main_id[(clean_name, transport_type_code)] = r['id']

        routes_to_scan = []
        seen_routes = set()

        # 3. Перебираємо маршрути зупинки
        found_routes = stop_info.get('routes', [])

        for r in found_routes:
            r_title = str(r.get('title', '')).strip()
            local_id = r.get('id')
            r_direction = r.get('direction')

            # --- ВИЗНАЧЕННЯ ТИПУ ТРАНСПОРТУ (STRICT MODE) ---
            api_transport_key = r.get('transportKey', '')
            transport_name = str(r.get('transport_name', '')).lower()

            # 1. Нормалізація ключа
            if api_transport_key == 'trolley':
                api_transport_key = 'trol'

            # 2. Якщо ключа немає, пробуємо знайти його в назві маршруту
            # (наприклад "Трамвай 7", "Trolleybus 10")
            if not api_transport_key:
                if 'трамвай' in transport_name or 'tram' in transport_name:
                    api_transport_key = 'tram'
                elif 'тролейбус' in transport_name or 'trol' in transport_name:
                    api_transport_key = 'trol'

            # 3. Останній шанс (Blind Guessing) - використовуємо обережно
            # Якщо API не надало transportKey і в назві немає слів "трамвай/тролейбус",
            # ми ігноруємо цей маршрут. Це відсіює автобуси "2", "7" тощо.

            is_electric = (api_transport_key in ['tram', 'trol'])

            if is_electric:
                unique_key = (r_title, api_transport_key)

                if unique_key not in seen_routes:
                    target_id = name_to_main_id.get(unique_key, local_id)

                    logger.info(f"🔎 Scanning {api_transport_key.upper()} {r_title} (ID: {target_id})")

                    routes_to_scan.append((r_title, target_id, api_transport_key, r_direction))
                    seen_routes.add(unique_key)

        # 4. Скануємо GPS (паралельно)
        tasks = [easyway_service.get_vehicles_on_route(r_id) for _, r_id, _, _ in routes_to_scan]

        global_results = []
        if tasks:
            global_results = await asyncio.gather(*tasks)

            global_route_data = {}
            routes_meta_info = {}

            for i, (r_name, r_id, r_type, target_dir) in enumerate(routes_to_scan):
                raw_vehicles = global_results[i] if i < len(global_results) else []

                logger.info(
                    f"[DEBUG] Route {r_name} ({r_type}): Service returned {len(raw_vehicles) if raw_vehicles else 0} items")

                unique_key = f"{r_name}_{r_type}"
                global_route_data[unique_key] = raw_vehicles
                routes_meta_info[unique_key] = {
                    'name': r_name,
                    'type': r_type,
                    'stop_direction': target_dir
                }

            # 6. Рендеримо
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


# === ЛОГІКА ВІДОБРАЖЕННЯ (ФІНАЛЬНА) ===

async def _render_accessible_response(query, stop_title: str, stop_info: dict, global_route_data: dict,
                                      routes_meta: dict):
    """
    Формує повідомлення.
    Показує всі машини та коректні типи транспорту.
    """

    message = (
        f"♿️ <b>Низькопідлоговий Транспорт</b>\n"
        f"📍 Зупинка: <b>{stop_title}</b>\n"
        f"🚊— ─ ─ ─ ─ ─ ─ ─ ─ 🚎\n"
        f"👋 Шановні пасажири!\n"
        f"⏱️ Інформація про рух електротранспорту\n\n"
        f"⚠️ актуальні на момент запиту⚠️\n"
        f"📢 <b>Увага!</b> На жаль під час <b>повітряної тривоги</b> 🚨 дані про рух електротранспорту "
        f"не можуть бути надані.\n"
        f"🚊— ─ ─ ─ ─ ─ ─ ─ ─ 🚎\n\n"
    )

    # 1. Обробляємо прибуття (Arrivals)
    handicapped_arrivals = easyway_service.filter_handicapped_routes(stop_info)
    arrivals_by_key = {}

    for arr in handicapped_arrivals:
        r_title = str(arr.get('title')).strip()
        r_key = arr.get('transport_key')
        if r_key == 'trolley': r_key = 'trol'
        unique_key = f"{r_title}_{r_key}"

        if unique_key not in arrivals_by_key:
            arrivals_by_key[unique_key] = []
        arrivals_by_key[unique_key].append(arr)

    # 2. Складаємо повний список маршрутів
    all_keys = set(global_route_data.keys()) | set(arrivals_by_key.keys())
    sorted_keys = sorted(list(all_keys), key=lambda x: int(re.sub(r'\D', '', x.split('_')[0])) if re.sub(r'\D', '',
                                                                                                         x.split('_')[
                                                                                                             0]) else 999)

    has_data = False

    for key in sorted_keys:
        r_meta = routes_meta.get(key, {})
        if not r_meta:
            parts = key.split('_')
            r_name = parts[0]
            r_type = parts[1] if len(parts) > 1 else 'tram'
        else:
            r_name = r_meta.get('name')
            r_type = r_meta.get('type')

        global_vehicles = global_route_data.get(key) or []
        arrivals = arrivals_by_key.get(key, [])

        icon = '🚎' if r_type == 'trol' else '🚋'
        transport_name = 'Тролейбус' if r_type == 'trol' else 'Трамвай'

        # === СЦЕНАРІЙ А: Є ПРОГНОЗ ПРИБУТТЯ ===
        if arrivals:
            has_data = True
            message += f"✅ <b>{icon} {transport_name} №{r_name}:</b>\n"

            nearest = arrivals[0]
            nearest_bort = str(nearest.get('bort_number'))
            time_icon = easyway_service.get_time_source_icon(nearest.get("time_source"))
            direction_str = html.escape(nearest.get('direction_title') or nearest.get('direction', 'Невідомо'))

            message += "👇 НАЙБЛИЖЧИЙ ДО ВАС:\n"
            message += (
                f"   {icon} {transport_name} №{r_name}\n"
                f"   → Напрямок: {direction_str}\n"
                f"   Борт: <b>{html.escape(nearest_bort)}</b>\n"
                f"   Прибуття: {time_icon} <b>{html.escape(nearest.get('time_left_formatted', '??'))}</b>\n\n"
            )
            continue


        # === СЦЕНАРІЙ Б: НЕМАЄ ПРОГНОЗУ, АЛЕ Є GPS (Тільки інклюзивний) ===
        elif global_vehicles:
        #Оскільки ми тепер фільтруємо в сервісі, сюди потраплять
        # ТІЛЬКИ низькопідлогові вагони.

            vehicles_count = len(global_vehicles)

            if vehicles_count > 0:
                has_data = True
                message += f"⚠️ <b>{icon} {transport_name} №{r_name}:</b>\n"

                message += f"⚡️ На маршруті працює <b>{vehicles_count}</b> од. низькопідлогового транспорту!\n"

                message += (
                    f""
                    f"\nℹ️ <i>На жаль, сервер ще не надав точного часу прибуття.\n\n</i>"
                    f"👀 <i>Можливі причини:\n</i>"
                    f"🛰️ <b>Збій GPS-даних</b> у провайдера (ми не бачимо, де транспорт)\n"
                    f"⚠️ Електротранспорт <b>знаходиться на кінцевій зупинці</b> та очікує руху за розкладом.\n"
                    f"😕Електротранспорт <b>або вже проїхав Вашу зупинку або рухається в іншому напрямку.</b>\n"
                    f"<i>Будь ласка, спробуйте повторити запит трохи пізніше.</i>\n\n"
                )
            # Якщо список порожній (0 машин), код піде в else нижче, якщо прибрати continue,
            # або можна явно обробити це тут. Але логічніше, щоб порожній global_vehicles йшов в else.
            else:
                # Цей блок спрацює, якщо список порожній (немає інклюзивних)
                # Ми передаємо керування в блок "немає даних"
                pass

        # === СЦЕНАРІЙ В: ДАНИХ НЕМАЄ (НОВЕ) ===
        # Якщо немає arrivals і немає (або 0) global_vehicles
        if not arrivals and not global_vehicles:
            # Тут ми ставимо has_data = True, тому що ми фактично "надали інформацію" про те, що маршрут не працює.
            # Це запобігає дублюванню повідомлення в самому кінці (у підвалі).
            has_data = True

            message += f"❓ <b>{icon} {transport_name} №{r_name}:</b>\n"
            message += (
                "😕 <b>Інформація наразі відсутня.</b>\n"
                "👀 <i>Можливі причини:</i>\n"
                "🚨 <b>Повітряна тривога</b> (безпека понад усе!)\n"
                "🛰️ <b>Збій GPS-даних</b> у провайдера\n"
                "🚧 <b>Аварія</b> або ускладнення руху\n"
                "🔌 <b>Технічні причини</b> <i>(напр. 'відсутність світла', тощо)</i>\n"
                "🚫 <b>Відсутність низькопідлогових вагонів</b> на лінії\n\n"
            )

    # Підвал
    if not has_data:
        message += (
            "😕 <b>Інформація наразі відсутня.</b>\n\n"
            "👀 <i>Можливі причини:</i>\n"
            "🚨 <b>Повітряна тривога</b> (безпека понад усе!)\n"
            "🛰️ <b>Збій GPS-даних</b> у провайдера (ми не бачимо, де транспорт)\n"
            "🚧 <b>Аварія</b> або ускладнення руху на лінії\n"
            "🔌 <b>Технічні причини</b> <i>(напр.'відсутність світла', тощо)</i>\n"
            "🚫 <b>Відсутність низькопідлогових вагонів</b> на лінії\n\n"
        )

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

async def _show_stops_keyboard(update: Update, places: list, context: ContextTypes.DEFAULT_TYPE = None):
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

    # Якщо функцію викликано через callback (кнопка)
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text=message_text, reply_markup=reply_markup,
                                                          parse_mode=ParseMode.HTML)
        except Exception:
            pass
    # Якщо функцію викликано після текстового вводу (ми передали context)
    elif context and 'main_message_id' in context.user_data:
        chat_id = update.effective_chat.id
        msg_id = context.user_data['main_message_id']
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=message_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Show stops edit error: {e}")
            # Fallback
            msg = await update.message.reply_text(text=message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            context.user_data['main_message_id'] = msg.message_id
    else:
        # Старий fallback (на всяк випадок)
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
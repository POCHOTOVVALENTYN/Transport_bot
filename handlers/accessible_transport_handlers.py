# handlers/accessible_transport_handlers.py

from handlers.menu_handlers import main_menu
from utils.logger import logger
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, Application
from bot.states import States
from handlers.command_handlers import get_main_menu_keyboard
from services.easyway_service import easyway_service
import asyncio
import telegram.error
from telegram.helpers import escape_html


# ❌ haversine(...) - ВИДАЛЕНО [cite: 1837-1839]

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
    [cite: 1356-1359]
    """
    query = update.callback_query
    await query.answer()

    # Виконайте пошук "Ринок"
    data = await easyway_service.get_places_by_name(search_term="Ринок Привоз")
    stops = data.get("stops", [])

    # 🔍 ЛОГУВАННЯ ДЛЯ ДІАГНОСТИКИ
    logger.info(f"===== DIAGNOSTIC: Пошук 'Ринок Привоз' =====")
    for stop in stops:
        logger.info(f"ID: {stop['id']}, Назва: {stop['title']}, Lat: {stop['lat']}, Lng: {stop['lng']}")
    logger.info(f"=====================================")


    logger.info(f"User {update.effective_user.id} started v1.2 accessible transport search")

    # Ініціалізуємо/очищуємо дані
    context.user_data.clear()

    # Клавіатура з популярними зупинками (з плану v1.2) [cite: 1373-1380]
    # ID зупинок (6026) взяті з прикладу в PDF [cite: 1655]
    keyboard = [
        [InlineKeyboardButton("📍 Ринок Привоз", callback_data="stop_search_Привоз")],
        [InlineKeyboardButton("🚉 Залізничний вокзал", callback_data="stop_search_Залізничний вокзал")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = (
        "♿️ <b>Пошук Низькопідлогового Транспорту</b>\n\n"
        "Місто: <b>Одеса</b>\n\n"
        "Будь ласка, <b>надішліть мені назву зупинки</b> (напр., <i>Привоз</i> або <i>Пантелеймонівська</i>) "
        "або виберіть з популярних варіантів нижче:"
    )

    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="HTML")
    return States.ACCESSIBLE_SEARCH_STOP


async def accessible_search_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Крок 2: Користувач вводить текст для пошуку зупинки. [cite: 1384-1386]
    """
    search_term = update.message.text
    user_id = update.effective_user.id
    logger.info(f"User {user_id} searching for stop: {search_term}")

    await update.message.chat.send_action("typing")

    try:
        # API CALL #1: cities.GetPlacesByName [cite: 1392]
        data = await easyway_service.get_places_by_name(search_term=search_term)

        if data.get("error"):
            await update.message.reply_text(f"❌ Помилка API: {data['error']}")
            return States.ACCESSIBLE_SEARCH_STOP

        places = data.get("stops", [])
        if not places:
            await update.message.reply_text(
                f"❌ Зупинок не знайдено за запитом <b>'{search_term}'</b>.\n\n"
                f"Спробуйте іншу назву (напр., <i>Парк Шевченка</i>).",
                parse_mode="HTML"
            )
            return States.ACCESSIBLE_SEARCH_STOP

        # Зберігаємо результати в контекст [cite: 1408]
        context.user_data["search_results"] = places

        # Показуємо кнопки зі знайденими зупинками
        await _show_stops_keyboard(update, context, places)
        return States.ACCESSIBLE_SELECT_STOP

    except Exception as e:
        logger.error(f"Error searching stops: {e}")
        await update.message.reply_text(f"❌ Помилка при пошуку: {str(e)}")
        return States.ACCESSIBLE_SEARCH_STOP


async def accessible_stop_quick_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Крок 2 (альтернативний): Користувач натискає кнопку популярної зупинки.
    [cite: 1421-1423]
    """
    query = update.callback_query
    await query.answer()

    search_term = query.data.split("stop_search_")[-1]  # "Центр", "Аеропорт" ...
    logger.info(f"User {query.from_user.id} quick searching for: {search_term}")

    await query.edit_message_text(
        f"🔄 Пошук зупинок за терміном: <b>'{search_term}'</b>...",
        parse_mode="HTML"
    )

    try:
        # API CALL #1: cities.GetPlacesByName [cite: 1442]
        data = await easyway_service.get_places_by_name(search_term=search_term)

        if data.get("error"):
            await query.edit_message_text(f"❌ Помилка API: {data['error']}")
            return States.ACCESSIBLE_SEARCH_STOP

        places = data.get("stops", [])
        if not places:
            await query.edit_message_text(
                f"❌ Зупинок не знайдено за запитом <b>'{search_term}'</b>.",
                parse_mode="HTML"
            )
            return States.ACCESSIBLE_SEARCH_STOP

        context.user_data["search_results"] = places

        # Показуємо кнопки [cite: 1453-1466]
        keyboard = []
        for place in places[:10]:  # Максимум 10
            # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
            title = place['title']
            summary = place.get('routes_summary')  # Отримуємо наш новий рядок

            button_text = f"📍 {title}"
            if summary:  # Додаємо, якщо він є
                button_text += f" ({summary})"

            # Обрізаємо текст кнопки, якщо він занадто довгий для Telegram (ліміт 64 байти)
            if len(button_text.encode('utf-8')) > 60:
                button_text = button_text[:25] + "..."  # Безпечне обрізання

            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"stop_{place['id']}"
                )
            ])
            # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---
        keyboard.append([InlineKeyboardButton("⬅️ Назад (до пошуку)", callback_data="accessible_start")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"Оберіть зупинку за терміном <b>'{search_term}'</b>:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return States.ACCESSIBLE_SELECT_STOP

    except Exception as e:
        logger.error(f"Error in quick search: {e}")
        await query.edit_message_text(f"❌ Помилка: {str(e)}")
        return States.ACCESSIBLE_SEARCH_STOP


# handlers/accessible_transport_handlers.py

async def accessible_stop_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Крок 3: Користувач обрав зупинку. Робимо магічний виклик v1.2.
    (ВЕРСІЯ З ПОВНИМ БЛОКОМ TRY...EXCEPT)
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

        await query.edit_message_text("🔄 Отримую інформацію про прибуття (v1.2)...")

        # API CALL #2: stops.GetStopInfo v1.2
        stop_info = await easyway_service.get_stop_info_v12(stop_id=stop_id)

        if stop_info.get("error"):
            # Це спрацює при тайм-ауті (з Кроку 2)
            await query.edit_message_text(f"❌ Помилка API v1.2: {stop_info['error']}")
            return States.ACCESSIBLE_SEARCH_STOP

        stop_title = stop_info.get("title", f"Зупинка ID: {stop_id}")
        stop_title_safe = escape_html(stop_title)

        # ФІЛЬТРУЄМО ТІЛЬКИ НИЗЬКОПІДЛОГОВИЙ ТРАНСПОРТ
        handicapped_routes = easyway_service.filter_handicapped_routes(stop_info)

        # Показуємо результати
        await _show_accessible_transport_results(query, stop_title_safe, handicapped_routes)

        context.user_data.clear()
        return ConversationHandler.END

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


async def _show_stops_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE, places: list):
    """
    Допоміжна функція для показу списку зупинок як кнопок.
    [cite: 1514-1520]
    """
    keyboard = []
    for place in places[:10]:  # Максимум 10 кнопок [cite: 1522]
        keyboard.append([
            InlineKeyboardButton(
                f"📍 {place['title']}",
                callback_data=f"stop_{place['id']}"  # [cite: 1525]
            )
        ])
    keyboard.append([InlineKeyboardButton("⬅️ Назад (до пошуку)", callback_data="accessible_start")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Оберіть точну зупинку зі списку:",
        reply_markup=reply_markup
    )


# handlers/accessible_transport_handlers.py

async def _show_accessible_transport_results(query, stop_title: str, routes: list):
    """
    Показує фінальні результати (список інклюзивного транспорту).
    [cite: 1533-1538]
    """
    if not routes:
        # Сценарій: Немає низькопідлогового транспорту [cite: 1540-1542]
        message = (
            f"♿️ <b>На зупинці '{stop_title}'</b>\n\n"
            f"❌ На жаль, найближчим часом <b>немає</b> низькопідлогового транспорту, "
            f"що прямує до цієї зупинки."
        )
        keyboard = [[InlineKeyboardButton("⬅️ Пошук іншої зупинки", callback_data="accessible_start")],
                    [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        return

    # Сценарій: Є низькопідлоговий транспорт
    header = (
        f"♿️ <b>Низькопідлоговий Транспорт</b>\n"
        f"Зупинка: <b>{stop_title}</b>\n"
        f"───────────────\n\n"
    )

    routes_text = ""
    for i, route in enumerate(routes, 1):
        # Ігноруємо "marshrutka" згідно вашого запиту
        if route.get("transport_key") == "marshrutka":
            continue

        transport_icon = easyway_service.get_transport_icon(route["transport_key"])
        time_icon = easyway_service.get_time_source_icon(route["time_source"])

        # Комфорт [cite: 1564-1572]
        comfort_items = []
        if route.get("wifi"):
            comfort_items.append("📶 Wi-Fi")
        if route.get("aircond"):
            comfort_items.append("❄️ A/C")

        comfort_str = f"| {', '.join(comfort_items)}" if comfort_items else ""

        # --- ПОЧАТОК ВИПРАВЛЕННЯ: Екранування HTML ---
        # Екрануємо ВСІ дані, що прийшли з API
        safe_transport_name = escape_html(route.get('transport_name', 'N/A'))
        safe_title = escape_html(route.get('title', 'N/A'))
        safe_direction = escape_html(route.get('direction', 'N/A'))
        safe_bort_number = escape_html(route.get('bort_number', '??'))
        safe_time_left = escape_html(route.get('time_left_formatted', 'N/A'))

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
        f"─────────────────\n"
        f"<i>{easyway_service.time_icons['gps']} = час за GPS, {easyway_service.time_icons['schedule']} = за розкладом</i>"
    )
    # =======================

    message = header + routes_text + footer
    keyboard = [[InlineKeyboardButton("⬅️ Пошук іншої зупинки", callback_data="accessible_start")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]]
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def accessible_text_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    (НОВА ДОПОМІЖНА ФУНКЦІЯ)
    Скасування діалогу, якщо користувач просто пише текст, а не натискає кнопку.
    """
    await update.message.reply_text("❌ Пошук скасовано. Ви повернулись у головне меню.")
    await main_menu(update, context)  # Викликаємо головне меню
    return ConversationHandler.END
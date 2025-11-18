import asyncio
import logging
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, \
    filters
from config.settings import MUSEUM_ADMIN_ID, GOOGLE_SHEETS_ID, GENERAL_ADMIN_IDS
from integrations.google_sheets.client import GoogleSheetsClient
from utils.logger import logger
from bot.states import States
from handlers.command_handlers import get_admin_main_menu_keyboard

from services.user_service import UserService
from services.tickets_service import TicketsService
from config.settings import MUSEUM_ADMIN_ID

user_service = UserService()
tickets_service = TicketsService()

# Стани для розсилки
ADMIN_BROADCAST_TEXT = 50

# Стани для адміна
(ADMIN_STATE_ADD_DATE, ADMIN_STATE_DEL_DATE_CONFIRM) = range(16, 18)  # Використовуємо нові стани


# --- НОВА ФУНКЦІЯ: Меню Загального Адміна (Валентин і Тетяна) ---
async def show_general_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Головне меню для новин та керування ботом"""
    query = update.callback_query
    if query: await query.answer()

    user_id = update.effective_user.id
    if user_id not in GENERAL_ADMIN_IDS:
        return

    # Отримуємо статистику
    stats = await user_service.get_stats()

    text = (
        f"⚙️ <b>Панель Керування (Новини та Статистика)</b>\n\n"
        f"👥 Всього користувачів у базі: <b>{stats['total_users']}</b>\n"
        f"👋 Вітаю, {update.effective_user.first_name}!"
    )

    keyboard = [
        [InlineKeyboardButton("📢 Зробити розсилку (Новини)", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton("🔄 Синхронізувати БД -> Sheets", callback_data="admin_sync_db")],
        [InlineKeyboardButton("🏠 В режим користувача", callback_data="main_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


# --- ФУНКЦІЇ ЗАГАЛЬНИХ АДМІНІВ (Розсилка і Sync) ---

async def admin_sync_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручний запуск синхронізації"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏳ Синхронізація даних... Зачекайте.")

    try:
        count = await tickets_service.sync_new_feedbacks_to_sheets()
        # Кнопка "Назад" має вести в General Menu
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В адмінку", callback_data="general_admin_menu")]])

        await query.edit_message_text(
            f"✅ Успішно!\nВивантажено нових записів: <b>{count}</b>",
            reply_markup=back_btn,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await query.edit_message_text(f"❌ Помилка: {e}")


async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Кнопка "Скасувати" веде в General Menu
    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Скасувати", callback_data="general_admin_menu")]])

    await query.edit_message_text(
        "📢 <b>Режим розсилки новин</b>\n\n"
        "Надішліть повідомлення (текст, фото або відео), яке отримають <b>ВСІ</b> користувачі бота.",
        reply_markup=back_btn,
        parse_mode=ParseMode.HTML
    )
    return ADMIN_BROADCAST_TEXT


async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Відправка повідомлення всім юзерам"""
    users = await user_service.get_all_users_ids()
    count = 0
    blocked = 0

    msg = update.message
    status_msg = await update.message.reply_text(f"🚀 Починаю розсилку на {len(users)} користувачів...")

    for user_id in users:
        try:
            await msg.copy(chat_id=user_id)
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            blocked += 1

    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В адмінку", callback_data="general_admin_menu")]])

    await status_msg.edit_text(
        f"✅ Розсилка завершена!\n\n"
        f"📨 Отримали: {count}\n"
        f"🚫 Заблокували бота: {blocked}",
        reply_markup=back_btn
    )
    return ConversationHandler.END





# --- ІСНУЮЧА ФУНКЦІЯ: Меню Музею (Максим) ---
async def admin_menu_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню тільки для Музею"""
    keyboard = await get_admin_main_menu_keyboard() # Ця клавіатура вже налаштована для музею
    text = "👋 Вітаю, Максиме! Ви в адмін-панелі Музею."

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=text, reply_markup=keyboard)
    else:
        await update.effective_chat.send_message(text=text, reply_markup=keyboard)
    return ConversationHandler.END





# Перевірка, чи є користувач адміном
async def is_admin(update: Update) -> bool:
    is_admin_user = update.effective_user.id == MUSEUM_ADMIN_ID
    if not is_admin_user:
        logger.warning(f"Non-admin user {update.effective_user.id} tried to access admin functions.")
        await update.message.reply_text("❌ У вас немає прав доступу до цієї команди.")
    return is_admin_user


# Головне меню адміна
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Вхідна точка для команди /admin_museum.
    Перевіряє права та перенаправляє на показ повного меню.
    """
    if not await is_admin(update):
        return ConversationHandler.END

    # Просто викликаємо нашу "правильну" функцію показу меню
    # Вона покаже 4 кнопки і завершить будь-який діалог
    return await admin_menu_show(update, context)


# --- Потік додавання дати ---
async def admin_add_date_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != MUSEUM_ADMIN_ID: return ConversationHandler.END  # Додаткова перевірка

    # Клавіатура для скасування
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu_show")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        "Будь ласка, введіть дату та час екскурсії у чіткому форматі:\n\n"
        "<code>ДД.ММ.РРРР ГГ:ХХ</code>\n\n"
        "Наприклад: <code>25.11.2025 11:00</code>"
    )

    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML # Використовуємо HTML для <code>
    )
    return States.ADMIN_STATE_ADD_DATE


async def admin_add_date_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MUSEUM_ADMIN_ID: return ConversationHandler.END

    date_text = update.message.text.strip()

    # --- ПОЧАТОК ВАЛІДАЦІЇ ---
    try:
        # 1. Перевірка формату (ДД.ММ.РРРР ГГ:ХХ)
        if not re.match(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$", date_text):
            raise ValueError("Невірний формат. Очікується <code>ДД.ММ.РРРР ГГ:ХХ</code>.")

        # 2. Перевірка коректності дати (напр., не 30.02.2025)
        try:
            parsed_date = datetime.strptime(date_text, '%d.%m.%Y %H:%M')
        except ValueError:
            raise ValueError("Некоректна дата. Можливо, неіснуючий день або місяць?")

        # 3. Перевірка, чи дата не в минулому
        if parsed_date < datetime.now():
            raise ValueError("Дата не може бути у минулому.")

        # --- ВАЛІДАЦІЯ ПРОЙДЕНА ---
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        sheets.append_row(sheet_name="MuseumDates", values=[date_text])

        logger.info(f"✅ Admin added new date: {date_text}")
        await update.message.reply_text(f"✅ Дату '<b>{date_text}</b>' успішно додано.", parse_mode=ParseMode.HTML)

        # Повертаємося до головного адмін-меню
        await admin_menu_show(update, context) # Показуємо повне меню
        return ConversationHandler.END # Завершуємо діалог

    except ValueError as e:
        # --- ВАЛІДАЦІЯ НЕ ПРОЙДЕНА ---
        logger.warning(f"Admin date validation failed: {e}")
        await update.message.reply_text(
            f"❌ <b>Помилка:</b> {e}\n\n"
            f"Будь ласка, спробуйте ще раз або натисніть 'Назад'.",
            parse_mode=ParseMode.HTML
        )
        # Повертаємося до ЦЬОГО Ж стану, змушуючи адміна ввести дату знову
        return States.ADMIN_STATE_ADD_DATE

    except Exception as e:
        # --- Інша помилка (напр. Google Sheets) ---
        logger.error(f"Failed to add date by admin: {e}")
        await update.message.reply_text(f"❌ Сталася системна помилка при додаванні дати: {e}")

        await admin_menu_show(update, context) # Показуємо ПОВНЕ меню
        return ConversationHandler.END


# --- Потік видалення дати ---
async def admin_del_date_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != MUSEUM_ADMIN_ID: return ConversationHandler.END

    try:
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        dates_data = sheets.read_range(sheet_range="MuseumDates!A1:A100")  # Читаємо 100 рядків

        if not dates_data:
            await query.edit_message_text("Немає дат для видалення.", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu_show")]]))
            return ConversationHandler.END

        keyboard = []
        for i, row in enumerate(dates_data):
            if row:  # Переконуємося, що рядок не пустий
                date_str = row[0]
                cell_ref = f"A{i + 1}"  # A1, A2, ...
                keyboard.append([InlineKeyboardButton(f"❌ {date_str}", callback_data=f"admin_del_confirm:{cell_ref}")])

        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu_show")])
        await query.edit_message_text("Оберіть дату, яку потрібно видалити:",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Failed to show dates for deletion: {e}")
        await query.edit_message_text(f"❌ Помилка: {e}")

    return States.ADMIN_STATE_DEL_DATE_CONFIRM


async def admin_del_date_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != MUSEUM_ADMIN_ID: return ConversationHandler.END

    cell_to_delete = query.data.split(":")[1] # "A5"

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---

    # 1. Створюємо клавіатуру "Назад" ЗАЗДАЛЕГІДЬ
    keyboard_back = [
        [InlineKeyboardButton("⬅️ Назад до адмін-панелі", callback_data="admin_menu_show")]
    ]
    reply_markup_back = InlineKeyboardMarkup(keyboard_back)

    # 2. (Покращення) Отримуємо текст кнопки, яку натиснули
    #    (Ваш старий код [0][0] працював би, лише якщо натиснути першу кнопку)
    date_str = ""
    for row in query.message.reply_markup.inline_keyboard:
        if row[0].callback_data == query.data:
            date_str = row[0].text.replace("❌ ", "")
            break
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    try:
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        sheets.clear_cell(sheet_name="MuseumDates", cell=cell_to_delete)

        # --- ПОЧАТОК ВИПРАВЛЕННЯ 2 ---
        # Додаємо reply_markup до повідомлення
        await query.edit_message_text(
            text=f"✅ Дату '{date_str}' (комірка {cell_to_delete}) видалено.",
            reply_markup=reply_markup_back
        )
        # --- КІНЕЦЬ ВИПРАВЛЕННЯ 2 ---

    except Exception as e:
        logger.error(f"Failed to delete date: {e}")

        # --- ПОЧАТОК ВИПРАВЛЕННЯ 3 ---
        # Додаємо reply_markup до повідомлення про помилку
        await query.edit_message_text(
            text=f"❌ Помилка при видаленні: {e}",
            reply_markup=reply_markup_back
        )
        # --- КІНЕЦЬ ВИПРАВЛЕННЯ 3 ---

    return ConversationHandler.END


async def admin_show_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує список останніх бронювань з 'MuseumBookings'."""
    query = update.callback_query
    await query.answer()
    if query.from_user.id != MUSEUM_ADMIN_ID: return

    try:
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        # Читаємо останні 50 бронювань (включно з заголовком)
        bookings_data = sheets.read_range(sheet_range="MuseumBookings!A1:E51")

        if not bookings_data or len(bookings_data) < 2: # Якщо є тільки заголовок
            await query.edit_message_text(
                "📋 Наразі немає жодного бронювання.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu_show")]])
            )
            return

        text_list = "📋 **Останні заявки на екскурсії:**\n\n"
        # Пропускаємо заголовок (bookings_data[0]) і беремо дані
        for row in bookings_data[1:]:
            # A: Дата реєстрації, B: Дата екскурсії, C: Кількість, D: ПІБ, E: Телефон
            if row: # Переконуємося, що рядок не пустий
                reg_date = row[0]
                excursion_date = row[1] if len(row) > 1 else "N/A"
                count = row[2] if len(row) > 2 else "N/A"
                name = row[3] if len(row) > 3 else "N/A"
                phone = row[4] if len(row) > 4 else "N/A"

                text_list += (
                    f"▪️ <b>{name}</b> ({phone})\n"
                    f"   На дату: <b>{excursion_date}</b>, {count} осіб.\n"
                    f"   (Заявка від: {reg_date})\n"
                    f"---------------------\n"
                )

        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu_show")]]

        # Використовуємо HTML для форматування
        await query.edit_message_text(
            text=text_list,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"Failed to show bookings: {e}")
        await query.edit_message_text(f"❌ Помилка при читанні бронювань: {e}")

    # Ця функція не є частиною діалогу, тому нічого не повертаємо


# Обробник для повернення в адмін-меню
async def admin_menu_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Повертає адміна до ПОВНОГО головного меню адмін-панелі.
    Працює і з командами (/admin_museum), і з кнопками (Назад).
    """
    keyboard = await get_admin_main_menu_keyboard()
    text = "👋 Вітаю, Максиме! Ви в адмін-панелі Музею."

    if update.callback_query:
        # Якщо це натискання кнопки
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=keyboard
            )
        except Exception as e:
            # Помилка (напр., повідомлення те саме) - просто видаляємо та надсилаємо нове
            await update.callback_query.message.delete()
            await update.effective_chat.send_message(
                text=text,
                reply_markup=keyboard
            )
    else:
        # Якщо це команда /admin_museum
        await update.effective_chat.send_message(
            text=text,
            reply_markup=keyboard
        )

    return ConversationHandler.END
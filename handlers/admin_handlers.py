import logging
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, \
    filters
from config.settings import MUSEUM_ADMIN_ID, GOOGLE_SHEETS_ID
from integrations.google_sheets.client import GoogleSheetsClient
from utils.logger import logger
from bot.states import States
from handlers.command_handlers import get_admin_main_menu_keyboard

# Стани для адміна
(ADMIN_STATE_ADD_DATE, ADMIN_STATE_DEL_DATE_CONFIRM) = range(16, 18)  # Використовуємо нові стани


# Перевірка, чи є користувач адміном
async def is_admin(update: Update) -> bool:
    is_admin_user = update.effective_user.id == MUSEUM_ADMIN_ID
    if not is_admin_user:
        logger.warning(f"Non-admin user {update.effective_user.id} tried to access admin functions.")
        await update.message.reply_text("❌ У вас немає прав доступу до цієї команди.")
    return is_admin_user


# Головне меню адміна
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("➕ Додати дату екскурсії", callback_data="admin_add_date")],
        [InlineKeyboardButton("➖ Видалити дату екскурсії", callback_data="admin_del_date_menu")],
    ]
    await update.message.reply_text("Вітаю в адмін-панелі Музею!", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END  # Просто показуємо меню


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
        await admin_menu(update, context) # Показуємо меню
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

        await admin_menu(update, context) # Показуємо меню
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

    cell_to_delete = query.data.split(":")[1]  # "A5"

    try:
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        sheets.clear_cell(sheet_name="MuseumDates", cell=cell_to_delete)
        await query.edit_message_text(f"✅ Дату в комірці {cell_to_delete} видалено. Оновіть меню.")
    except Exception as e:
        logger.error(f"Failed to delete date: {e}")
        await query.edit_message_text(f"❌ Помилка при видаленні: {e}")

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
# Обробник для повернення в адмін-меню
async def admin_menu_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повертає адміна до ПОВНОГО головного меню адмін-панелі."""
    query = update.callback_query
    await query.answer()

    # Отримуємо повну клавіатуру з 4 кнопками
    keyboard = await get_admin_main_menu_keyboard()

    await query.edit_message_text(
        "👋 Вітаю, Максиме! Ви в адмін-панелі Музею.", # Використовуємо той самий текст, що й у /start
        reply_markup=keyboard
    )
    return ConversationHandler.END
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, \
    filters
from config.settings import MUSEUM_ADMIN_ID, GOOGLE_SHEETS_ID
from integrations.google_sheets.client import GoogleSheetsClient
from utils.logger import logger

# Стани для адміна
(ADMIN_STATE_ADD_DATE, ADMIN_STATE_DEL_DATE_CONFIRM) = range(14, 16)  # Використовуємо нові стани


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

    await query.edit_message_text("Введіть дату та час у форматі: `ДД.ММ.РРРР ГГ:ХХ`\nНаприклад: `25.11.2025 14:00`")
    return ADMIN_STATE_ADD_DATE


async def admin_add_date_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MUSEUM_ADMIN_ID: return ConversationHandler.END

    date_text = update.message.text
    # Тут можна додати валідацію дати, але поки просто зберігаємо

    try:
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        sheets.append_row(sheet_name="MuseumDates", values=[date_text])
        await update.message.reply_text(f"✅ Дату '{date_text}' успішно додано.")
    except Exception as e:
        logger.error(f"Failed to add date by admin: {e}")
        await update.message.reply_text(f"❌ Помилка при додаванні дати: {e}")

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

    return ADMIN_STATE_DEL_DATE_CONFIRM


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


# Обробник для повернення в адмін-меню
async def admin_menu_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ Додати дату екскурсії", callback_data="admin_add_date")],
        [InlineKeyboardButton("➖ Видалити дату екскурсії", callback_data="admin_del_date_menu")],
    ]
    await query.edit_message_text("Адмін-панель Музею:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END
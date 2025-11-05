from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from utils.logger import logger
from config.settings import MUSEUM_ADMIN_ID


async def get_main_menu_keyboard():
    """Повертає клавіатуру головного меню"""
    keyboard = [
        [InlineKeyboardButton("📍 Де мій транспорт? (Real-time)", callback_data="realtime_transport")],
        [InlineKeyboardButton("🎫 Квитки та тарифи", callback_data="tickets_menu")],
        [InlineKeyboardButton("✍️ Зворотній зв'язок", callback_data="feedback_menu")],
        [InlineKeyboardButton("ℹ️ Довідкова інформація", callback_data="info_menu")],
        [InlineKeyboardButton("👔 Вакансії", callback_data="vacancies_menu")],
        [InlineKeyboardButton("🎓 Навчально-курсовий комбінат", callback_data="education_menu")],
        [InlineKeyboardButton("🏛️ Музей КП 'ОМЕТ'", callback_data="museum_menu")],
        [InlineKeyboardButton("🏢 Про підприємство", callback_data="company_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def get_admin_main_menu_keyboard():
    """Повертає клавіатуру головного меню для Адміна Музею."""
    keyboard = [
        [InlineKeyboardButton("➕ Додати дату екскурсії", callback_data="admin_add_date")],
        [InlineKeyboardButton("➖ Видалити дату екскурсії", callback_data="admin_del_date_menu")],
        [InlineKeyboardButton("📋 Перелік зареєстрованих", callback_data="admin_show_bookings")],
        [InlineKeyboardButton("👤 Режим користувача", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - показує різне меню для адміна та користувача."""
    user_id = update.effective_user.id
    logger.info(f"👤 User {user_id} started bot")

    if user_id == MUSEUM_ADMIN_ID:
        # --- Меню для Адміністратора Музею ---
        keyboard = await get_admin_main_menu_keyboard()
        await update.message.reply_text(
            "👋 Вітаю, Максиме! Ви в адмін-панелі Музею.",
            reply_markup=keyboard
        )
    else:
        # --- Меню для Звичайного Користувача ---
        keyboard = await get_main_menu_keyboard()
        await update.message.reply_text(
            MESSAGES['welcome'],  # Ваш WELCOME_MESSAGE
            reply_markup=keyboard
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    text = "🆘 Допомога:\n\n/start - Головне меню\n/help - Цей текст"
    await update.message.reply_text(text)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from utils.logger import logger


async def get_main_menu_keyboard():
    """Повертає клавіатуру головного меню"""
    keyboard = [
        [InlineKeyboardButton("📍 Де мій транспорт? (Real-time)", callback_data="realtime_transport")],
        [InlineKeyboardButton("🗺️ Прокласти маршрут", callback_data="route_planner")],
        [InlineKeyboardButton("🎫 Квитки та тарифи", callback_data="tickets_menu")],
        [InlineKeyboardButton("✍️ Зворотний зв'язок", callback_data="feedback_menu")],
        [InlineKeyboardButton("ℹ️ Довідкова інформація", callback_data="info_menu")],
        [InlineKeyboardButton("🏛️ Музей КП 'ОМЕТ'", callback_data="museum_menu")],
        [InlineKeyboardButton("🏢 Про підприємство", callback_data="company_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - показує головне меню"""
    logger.info(f"👤 User {update.effective_user.id} started bot")

    keyboard = await get_main_menu_keyboard()
    await update.message.reply_text(
        MESSAGES['welcome'],  # Ваш WELCOME_MESSAGE з config/messages.py
        reply_markup=keyboard
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    text = "🆘 Допомога:\n\n/start - Головне меню\n/help - Цей текст"
    await update.message.reply_text(text)
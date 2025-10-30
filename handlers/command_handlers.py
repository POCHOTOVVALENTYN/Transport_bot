from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from utils.logger import logger


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    logger.info(f"👤 User {update.effective_user.id} started bot")

    keyboard = [
        [InlineKeyboardButton("😞 Залишити скаргу", callback_data="complaint")],
        [InlineKeyboardButton("❤️ Висловити подяку", callback_data="thanks")],
        [InlineKeyboardButton("💡 Залишити пропозицію", callback_data="suggestion")],
    ]

    await update.message.reply_text(
        MESSAGES['welcome'],
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    text = "🆘 Допомога:\n\n/start - Меню\n/help - Цей текст"
    await update.message.reply_text(text)
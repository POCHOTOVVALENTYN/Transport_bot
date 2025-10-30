import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.logger import logger

logger = logging.getLogger(__name__)


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню"""
    logger.info(f"User {update.effective_user.id} in menu")

    keyboard = [
        [InlineKeyboardButton("😞 Скарга", callback_data="complaint")],
        [InlineKeyboardButton("❤️ Подяка", callback_data="thanks")],
        [InlineKeyboardButton("💡 Пропозиція", callback_data="suggestion")],
    ]

    await update.callback_query.edit_message_text(
        text="Оберіть:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
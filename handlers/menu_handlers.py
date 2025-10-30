import logging
from telegram import Update
from telegram.ext import ContextTypes
from utils.logger import logger
# Імпортуємо нашу нову функцію клавіатури
from handlers.command_handlers import get_main_menu_keyboard

logger = logging.getLogger(__name__)


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повернення в головне меню (по натисканню кнопки 'назад' або 'main_menu')"""
    logger.info(f"User {update.effective_user.id} returned to main menu")

    query = update.callback_query
    await query.answer()

    keyboard = await get_main_menu_keyboard()
    await query.edit_message_text(
        text="🚊 Оберіть потрібну опцію:",  # Або ваш WELCOME_MESSAGE
        reply_markup=keyboard
    )
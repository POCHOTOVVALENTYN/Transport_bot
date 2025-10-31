import logging
from telegram import Update
from telegram.ext import ContextTypes
from utils.logger import logger
# Імпортуємо нашу нову функцію клавіатури
from handlers.command_handlers import get_main_menu_keyboard

logger = logging.getLogger(__name__)


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Повернення в головне меню.
    Обробляє як текстові повідомлення (edit), так і медіа (delete + reply).
    """
    logger.info(f"User {update.effective_user.id} returned to main menu")

    query = update.callback_query
    await query.answer()

    keyboard = await get_main_menu_keyboard()
    text = "🚊 Оберіть потрібну опцію:"

    if query.message.text:
        # Якщо це було текстове повідомлення, просто редагуємо його
        await query.edit_message_text(
            text=text,
            reply_markup=keyboard
        )
    else:
        # Якщо це було повідомлення з фото (або іншим медіа),
        # видаляємо його і надсилаємо нове текстове повідомлення
        await query.message.delete()
        await query.message.reply_text(
            text=text,
            reply_markup=keyboard
        )
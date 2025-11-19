
from utils.logger import logger
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from utils.logger import logger
# нова функція клавіатури
from handlers.command_handlers import get_main_menu_keyboard


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Повернення в головне меню.
    """
    logger.info(f"User {update.effective_user.id} returned to main menu")

    keyboard = await get_main_menu_keyboard(update.effective_user.id)
    text = "🚊 Оберіть потрібну опцію:"

    # --- 1. Видаляємо медіа (якщо вони були) ---
    if 'media_message_ids' in context.user_data:
        chat_id = update.effective_chat.id
        for msg_id in context.user_data['media_message_ids']:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass
        del context.user_data['media_message_ids']

    # --- 2. Визначаємо тип дії ---

    # Варіант А: Це натискання кнопки
    if update.callback_query:
        query = update.callback_query
        await query.answer()

        # Спробуємо відредагувати повідомлення
        try:
            await query.edit_message_text(text=text, reply_markup=keyboard)
        except Exception:
            # Якщо редагування неможливе (наприклад, це було фото), видаляємо і шлемо нове
            try:
                await query.message.delete()
            except Exception:
                pass
            await query.message.reply_text(text=text, reply_markup=keyboard)

    # Варіант Б: Це текстова команда або повідомлення
    elif update.message:
        await update.message.reply_text(text=text, reply_markup=keyboard)

    # Варіант В: Щось інше (наприклад, редагування повідомлення), просто ігноруємо або шлемо меню
    else:
        # На всяк випадок шлемо меню в чат
        if update.effective_chat:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=keyboard)

    return ConversationHandler.END
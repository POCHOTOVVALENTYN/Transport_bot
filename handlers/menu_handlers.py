from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler
from utils.logger import logger
from handlers.command_handlers import get_main_menu_keyboard  # Перевірте правильність імпорту


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Повернення в головне меню.
    Єдина точка входу для відображення меню.
    """
    logger.info(f"User {update.effective_user.id} returned to main menu")

    keyboard = await get_main_menu_keyboard(update.effective_user.id)
    text = "🚊 <b>Вас вітає бот Одеського міського електротранспорту!</b>\n\nОберіть потрібну опцію:"

    # --- 1. Очищення старих медіа (залишаємо як було) ---
    if 'media_message_ids' in context.user_data:
        chat_id = update.effective_chat.id
        for msg_id in context.user_data['media_message_ids']:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass
        del context.user_data['media_message_ids']

    # --- 2. Логіка відображення ---

    # ВАРІАНТ А: Користувач натиснув кнопку (callback)
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            # Редагуємо старе повідомлення
            await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        except Exception:
            # Якщо редагування неможливе (наприклад, старе повідомлення було з фото)
            # Спочатку надсилаємо НОВЕ повідомлення з меню...
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
            )
            # ...а потім пробуємо акуратно видалити старе, щоб уникнути «порожнього» екрану
            try:
                await query.message.delete()
            except Exception:
                pass

    # ВАРІАНТ Б: Користувач написав команду /start або текст "Меню"
    elif update.message:
        # Спробуємо видалити повідомлення користувача (щоб чат був чистим)
        # Якщо це /start, воно вже видалене в command_handlers, тому тут буде помилка, яку ми ігноруємо
        try:
            await update.message.delete()
        except Exception:
            pass

        # Надсилаємо НОВЕ красиве повідомлення (замість reply_text)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

    # ВАРІАНТ В: Інший випадок (fallback)
    else:
        if update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )

    return ConversationHandler.END
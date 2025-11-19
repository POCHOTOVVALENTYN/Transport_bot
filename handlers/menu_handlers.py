
from utils.logger import logger
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from utils.logger import logger
# нова функція клавіатури
from handlers.command_handlers import get_main_menu_keyboard


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Повернення в головне меню.
    Обробляє як CallbackQuery (кнопки), так і Message (після помилок).
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
            except Exception as e:
                logger.warning(f"Could not delete message {msg_id} in main_menu: {e}")
        del context.user_data['media_message_ids']

        # --- 2. НОВА ЛОГІКА: Перевірка типу update ---
        if update.callback_query:
            # --- 2.A. Це натискання кнопки (CallbackQuery) ---
            query = update.callback_query
            await query.answer()

            if query.message and query.message.text:
                # Якщо це було текстове повідомлення, просто редагуємо
                try:
                    await query.edit_message_text(
                        text=text,
                        reply_markup=keyboard
                    )
                except Exception as e:
                    logger.warning(f"Error editing message in main_menu, sending new: {e}")
                    # Якщо редагування не вдалося (напр., повідомлення те саме)
                    await query.message.reply_text(text=text, reply_markup=keyboard)

            elif query.message:
                # Якщо це було повідомлення з фото/документом (АБО воно вже видалене)

                # === 👇 ВИПРАВЛЕННЯ ТУТ 👇 ===
                try:
                    await query.message.delete()
                except Exception:
                    pass  # Ігноруємо помилку, якщо повідомлення вже видалене
                # ==============================

                await query.message.reply_text(
                    text=text,
                    reply_markup=keyboard
                )
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=keyboard)
    elif update.message:
        # --- 2.B. Це повідомлення (Message) ---
        # (Наприклад, після помилки в accessible_process_stub)
        # Просто надсилаємо нове повідомлення з меню
        await update.message.reply_text(
            text=text,
            reply_markup=keyboard
        )

    else:
        # --- 2.C. Невідомий тип update (про всяк випадок) ---
        logger.warning(f"main_menu called with unknown update type: {update}")
        if update.effective_chat:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=keyboard)

    # Чітко завершуємо ConversationHandler (це безпечно, навіть якщо він не активний)
    return ConversationHandler.END
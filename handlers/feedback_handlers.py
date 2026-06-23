from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from utils.logger import logger


async def show_feedback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню 'Зворотній зв'язок' та очищує будь-який діалог."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("😞 Залишити скаргу", callback_data="complaint")],
        [InlineKeyboardButton("❤️ Висловити подяку", callback_data="thanks")],
        [InlineKeyboardButton("💡 Залишити пропозицію", callback_data="suggestion")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "✍️ Оберіть опцію зворотнього зв'язку:"

    # --- ПОЧАТОК ВИПРАВЛЕННЯ: Логіка Edit/Delete ---
    # (Потрібно, бо ми можемо прийти сюди з текстового повідомлення)
    try:
        msg = await query.edit_message_text(
            text=text,
            reply_markup=reply_markup
        )
    except Exception:
        # Повідомлення не було текстовим або було видалено - надсилаємо нове
        msg = await query.message.reply_text(
            text=text,
            reply_markup=reply_markup
        )
    context.user_data['last_bot_msg_id'] = msg.message_id
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    return ConversationHandler.END
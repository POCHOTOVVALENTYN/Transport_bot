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
        [InlineKeyboardButton("🔍 Загублені речі", callback_data="lost_items")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "✍️ Оберіть опцію зворотнього зв'язку:"

    # --- ПОЧАТОК ВИПРАВЛЕННЯ: Логіка Edit/Delete ---
    # (Потрібно, бо ми можемо прийти сюди з текстового повідомлення)
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup
        )
    except Exception:
        # Повідомлення не було текстовим (напр., помилка) або було видалено
        # Просто видаляємо поточне і надсилаємо нове
        await query.message.delete()
        await query.message.reply_text(
            text=text,
            reply_markup=reply_markup
        )
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    return ConversationHandler.END
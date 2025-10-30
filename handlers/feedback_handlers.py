from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.logger import logger


async def show_feedback_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню 'Зворотний зв'язок'"""
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

    await query.edit_message_text(
        text="✍️ Оберіть опцію зворотного зв'язку:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
# handlers/common.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def get_back_keyboard(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
    """Повертає клавіатуру з кнопкою 'Назад'."""
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data=callback_data)]
    ]
    return InlineKeyboardMarkup(keyboard)
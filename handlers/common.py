from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def get_back_keyboard(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
    """Повертає клавіатуру з кнопками навігації."""
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data=callback_data)],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def get_back_button_only(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
    """Повертає клавіатуру тільки з кнопкою 'Назад'."""
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data=callback_data)]
    ]
    return InlineKeyboardMarkup(keyboard)

async def get_cancel_keyboard(cancel_callback: str = "museum_menu") -> InlineKeyboardMarkup:
    """
    Повертає клавіатуру для скасування поточного діалогу.
    'cancel_callback' - це куди поверне кнопка "Скасувати" (за замовчуванням - меню музею).
    """
    keyboard = [
        [InlineKeyboardButton("🚫 Скасувати реєстрацію", callback_data=cancel_callback)],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Update
from telegram.ext import ContextTypes
from handlers.command_handlers import get_main_menu_keyboard


async def dismiss_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Видаляє повідомлення розсилки і показує (оновлює) головне меню"""
    query = update.callback_query
    await query.answer()  # Щоб кнопка не блимала

    # 1. Видаляємо повідомлення розсилки
    try:
        await query.message.delete()
    except Exception:
        pass

    # 2. Надсилаємо свіже головне меню (щоб юзер не загубився)
    # АБО якщо меню вже є знизу, можна нічого не робити.
    # Але надіслати меню - це хороша практика "Home"

    # keyboard = await get_main_menu_keyboard(update.effective_user.id)
    # await query.message.reply_text("🚊 Головне меню:", reply_markup=keyboard)


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

async def get_feedback_cancel_keyboard(cancel_callback: str = "feedback_menu") -> InlineKeyboardMarkup:
    """
    Повертає клавіатуру для скасування діалогів зворотнього зв'язку.
    """
    keyboard = [
        [InlineKeyboardButton("🚫 Скасувати", callback_data=cancel_callback)],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)
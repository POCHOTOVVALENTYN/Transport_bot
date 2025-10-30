# handlers/tickets_handlers.py
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from handlers.common import get_back_keyboard


async def show_tickets_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню 'Квитки та тарифи'."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("💰 Вартість проїзду", callback_data="tickets:cost")],
        [InlineKeyboardButton("💳 Способи оплати", callback_data="tickets:payment")],
        [InlineKeyboardButton("🧾 Види проїзних", callback_data="tickets:passes")],
        [InlineKeyboardButton("🏪 Де придбати/поповнити", callback_data="tickets:purchase")],
        [InlineKeyboardButton("👵 Пільговий проїзд", callback_data="tickets:benefits")],
        [InlineKeyboardButton("⬅️ Головне меню", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text="🎫 Розділ 'Квитки та тарифи'. Оберіть опцію:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_ticket_static(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє всі статичні під-меню 'Квитків'."""
    query = update.callback_query
    await query.answer()

    # Отримуємо ключ (напр. 'cost') з callback_data (напр. 'tickets:cost')
    key = query.data.split(":")[1]

    # Отримуємо відповідний текст з MESSAGES
    text = MESSAGES.get(f"tickets_{key}", "Інформація не знайдена.")

    # Повертаємо клавіатуру "Назад" до меню квитків
    keyboard = await get_back_keyboard("tickets_menu")

    await query.edit_message_text(text=text, reply_markup=keyboard)
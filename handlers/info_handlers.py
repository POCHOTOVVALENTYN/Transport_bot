# handlers/info_handlers.py
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from handlers.common import get_back_keyboard


async def show_info_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню 'Довідкова інформація'."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🗺️ Наші маршрути (схеми)", callback_data="info:routes")],
        [InlineKeyboardButton("📜 Правила користування", callback_data="info:rules")],
        [InlineKeyboardButton("♿ Доступність (Інклюзивність)", callback_data="info:accessibility")],
        [InlineKeyboardButton("📞 Контакти", callback_data="info:contacts")],
        [InlineKeyboardButton("⬅️ Головне меню", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text="ℹ️ Розділ 'Довідкова інформація'. Оберіть опцію:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_info_static(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє всі статичні під-меню 'Довідки'."""
    query = update.callback_query
    await query.answer()

    key = query.data.split(":")[1]

    # Для маршрутів та правил ми можемо надсилати файли, але поки надішлемо текст
    if key == "routes":
        # Тут може бути логіка для відправки картинок чи кнопок з номерами
        text = MESSAGES.get("info_routes", "Тут буде список маршрутів...")
    elif key == "rules":
        # Тут може бути логіка для відправки PDF
        # await context.bot.send_document(chat_id=query.effective_chat.id, document=open('path/to/rules.pdf', 'rb'))
        text = MESSAGES.get("info_rules", "Тут буде PDF з правилами...")
    else:
        text = MESSAGES.get(f"info_{key}", "Інформація не знайдена.")

    keyboard = await get_back_keyboard("info_menu")
    await query.edit_message_text(text=text, reply_markup=keyboard)
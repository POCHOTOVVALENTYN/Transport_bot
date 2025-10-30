# handlers/tickets_handlers.py
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from handlers.common import get_back_keyboard
from telegram.constants import ParseMode # <--

logger = logging.getLogger(__name__) # <--


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


async def show_passes_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Надсилає довгий список проїзних, розділений на 2 повідомлення."""
    query = update.callback_query
    await query.answer()

    part_1 = MESSAGES.get("tickets_passes_1")
    part_2 = MESSAGES.get("tickets_passes_2")

    keyboard = await get_back_keyboard("tickets_menu")

    try:
        # 1. Редагуємо поточне повідомлення першою частиною списку
        await query.edit_message_text(
            text=part_1,
            parse_mode=ParseMode.MARKDOWN
        )

        # 2. Надсилаємо друге повідомлення (з кнопкою "Назад")
        await query.message.reply_text(
            text=part_2,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.error(f"❌ Error sending passes list: {e}")
        try:
            # Спроба відправити повідомлення про помилку
            await query.message.reply_text(
                "❌ Сталася помилка при завантаженні списку. Спробуйте пізніше.",
                reply_markup=keyboard
            )
        except Exception as e2:
            logger.error(f"❌❌ Critical error sending error message: {e2}")

async def handle_ticket_static(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє всі статичні під-меню 'Квитків'."""
    query = update.callback_query
    await query.answer()

    # Отримуємо ключ (напр. 'cost') з callback_data (напр. 'tickets:cost')
    key = query.data.split(":")[1]

    # 'passes' тепер обробляється окремо
    if key == "passes":
        logger.warning("handle_ticket_static received 'passes' key. Ignored.")
        return

    text = MESSAGES.get(f"tickets_{key}", "Інформація не знайдена.")
    keyboard = await get_back_keyboard("tickets_menu")

    try:
        await query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN  # <-- Додаємо Markdown і сюди
        )
    except Exception as e:
        logger.error(f"❌ Error in handle_ticket_static for key {key}: {e}")
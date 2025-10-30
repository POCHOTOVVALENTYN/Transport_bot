import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from config.settings import TICKET_PASSES_IMAGE
from handlers.common import get_back_keyboard, get_back_button_only
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


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
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text="🎫 Розділ 'Квитки та тарифи'. Оберіть опцію:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_passes_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Надсилає зображення + текст з видами проїзних."""
    query = update.callback_query
    await query.answer()

    keyboard = await get_back_keyboard("tickets_menu")

    try:
        # 1. Видаляємо поточне повідомлення
        await query.delete_message()

        # 2. Надсилаємо зображення
        with open(TICKET_PASSES_IMAGE, 'rb') as photo:
            await query.message.reply_photo(
                photo=photo,
                caption="🎫 Всі види проїзних для громадського транспорту Одеси:",
                reply_markup=keyboard
            )

        logger.info("✅ Passes image sent successfully")

    except FileNotFoundError:
        logger.error(f"❌ Image file not found: {TICKET_PASSES_IMAGE}")
        await query.message.reply_text(
            "❌ Зображення не знайдено. Спробуйте пізніше.",
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(f"❌ Error sending passes image: {e}")
        await query.message.reply_text(
            "❌ Сталася помилка при завантаженні зображення.",
            reply_markup=keyboard
        )


async def handle_ticket_static(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє всі статичні під-меню 'Квитків'."""
    query = update.callback_query
    await query.answer()

    # Отримуємо ключ (напр. 'cost') з callback_data (напр. 'tickets:cost')
    key = query.data.split(":")[1]

    # 'passes' тепер обробляється окремо
    if key == "passes":
        await show_passes_list(update, context)
        return

    text = MESSAGES.get(f"tickets_{key}", "Інформація не знайдена.")
    keyboard = await get_back_keyboard("tickets_menu")

    try:
        await query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"❌ Error in handle_ticket_static for key {key}: {e}")
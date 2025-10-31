import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from config.settings import TICKET_PASSES_IMAGE
from handlers.common import get_back_keyboard # <-- Використовуємо get_back_keyboard
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


async def show_tickets_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показує меню 'Квитки та тарифи'.
    Обробляє як текстові повідомлення (edit), так і медіа (delete + reply).
    """
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("💰 Вартість проїзду", callback_data="tickets:cost")],
        [InlineKeyboardButton("💳 Способи оплати", callback_data="tickets:payment")],
        [InlineKeyboardButton("🧾 Види проїзних", callback_data="tickets:passes")],
        [InlineKeyboardButton("🏪 Де придбати/поповнити", callback_data="tickets:purchase")],
        [InlineKeyboardButton("👵 Пільговий проїзд", callback_data="tickets:benefits")],
        # Використовуємо стандартні кнопки "Назад" і "Головне меню" з get_back_keyboard
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🎫 Розділ 'Квитки та тарифи'. Оберіть опцію:"

    if query.message.text:
        # Якщо це було текстове повідомлення, просто редагуємо його
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup
        )
    else:
        # Якщо це було повідомлення з фото, видаляємо його і надсилаємо нове
        await query.message.delete()
        await query.message.reply_text(
            text=text,
            reply_markup=reply_markup
        )


async def show_passes_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Надсилає зображення + текст з видами проїзних."""
    query = update.callback_query
    await query.answer()

    # get_back_keyboard вже містить "Назад" і "Головне меню"
    keyboard = await get_back_keyboard("tickets_menu")

    try:
        # 1. Видаляємо поточне повідомлення (меню "Квитки та тарифи")
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

    key = query.data.split(":")[1]

    # 'passes' обробляється show_passes_list, але цей роутер все одно його ловить
    # через `pattern="^tickets:"`. Ми повинні його явно проігнорувати.
    if key == "passes":
        logger.warning("handle_ticket_static received 'passes' key. Ignored.")
        return

    text = MESSAGES.get(f"tickets_{key}", "Інформація не знайдена.")
    keyboard = await get_back_keyboard("tickets_menu")

    try:
        await query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML # Змінено на HTML для узгодженості
        )
    except Exception as e:
        logger.error(f"❌ Error in handle_ticket_static for key {key}: {e}")
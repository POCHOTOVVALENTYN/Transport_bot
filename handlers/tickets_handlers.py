from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from config.settings import (
    TICKET_PASSES_FILE_ID_1, TICKET_PASSES_FILE_ID_2
)
from handlers.common import get_back_keyboard
from telegram.constants import ParseMode
from utils.logger import logger
import datetime
import random


# Функція генерації ID (якщо її немає)
def generate_ticket_id():
    return f"#THX-{random.randint(10000, 99999)}"


async def register_gratitude(data: dict):
    """
    Формує рядок для запису в Google Sheet.
    """
    ticket_id = generate_ticket_id()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    gratitude_type = "Конкретна" if data.get('is_specific') else "Загальна"
    transport_type = data.get('transport_type', '')

    row = [
        ticket_id,
        timestamp,
        gratitude_type,
        data.get('message', ''),
        data.get('user_name', ''),
        data.get('vehicle_number', ''),
        data.get('email', ''),
        "Новий",
        transport_type
    ]
    return ticket_id


async def show_tickets_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показує меню 'Квитки та тарифи'.
    """
    query = update.callback_query
    await query.answer()

    # --- 1. Очищення медіа (фото проїзних), якщо вони є ---
    if 'media_message_ids' in context.user_data:
        chat_id = update.effective_chat.id
        for msg_id in context.user_data['media_message_ids']:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.warning(f"Could not delete media message {msg_id}: {e}")
        del context.user_data['media_message_ids']

    # --- 2. Формування меню ---
    keyboard = [
        [InlineKeyboardButton("💰 Вартість проїзду", callback_data="tickets:cost")],
        [InlineKeyboardButton("💳 Способи оплати", callback_data="tickets:payment")],
        [InlineKeyboardButton("🧾 Види проїзних", callback_data="tickets:passes")],
        [InlineKeyboardButton("🏪 Де придбати?", callback_data="tickets:purchase")],
        [InlineKeyboardButton("👵 Пільговий проїзд", callback_data="tickets:benefits")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🎫 Розділ 'Квитки та тарифи'. Оберіть опцію:"

    # --- 3. Відображення (редагування або нове) ---
    try:
        # Спробуємо відредагувати поточне повідомлення (щоб не блимало)
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup
        )
    except Exception:
        # Якщо редагування неможливе (старе було з фото або видалене)
        try:
            await query.message.delete()
        except:
            pass
        await query.message.reply_text(
            text=text,
            reply_markup=reply_markup
        )


async def show_passes_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Надсилає 2 зображення за file_id, а потім текстове повідомлення.
    Використовує проміжне повідомлення 'Завантаження', щоб уникнути блимання.
    """
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    keyboard = await get_back_keyboard("tickets_menu")
    purchase_info_text = MESSAGES.get("tickets_purchase_info")

    # 1. ЗМІНЮЄМО старе меню на текст "Завантаження..."
    try:
        loading_msg = await query.edit_message_text(
            text="⏳ <b>Завантажую зображення проїзних...</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception:
        # Якщо не вийшло редагувати, надсилаємо нове
        loading_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="⏳ <b>Завантажую зображення проїзних...</b>",
            parse_mode=ParseMode.HTML
        )

    try:
        # 2. Надсилаємо зображення
        sent_photo_1 = await context.bot.send_photo(
            chat_id=chat_id,
            photo=TICKET_PASSES_FILE_ID_1,
            caption="Види проїзних (Частина 1)"
        )

        sent_photo_2 = await context.bot.send_photo(
            chat_id=chat_id,
            photo=TICKET_PASSES_FILE_ID_2,
            caption="Види проїзних (Частина 2)"
        )

        # Зберігаємо ID для видалення при натисканні "Назад"
        context.user_data['media_message_ids'] = [sent_photo_1.message_id, sent_photo_2.message_id]

        # 3. Видаляємо повідомлення "Завантаження"
        await context.bot.delete_message(chat_id=chat_id, message_id=loading_msg.message_id)

        # 4. Надсилаємо фінальне текстове повідомлення з кнопками
        await context.bot.send_message(
            chat_id=chat_id,
            text=purchase_info_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        logger.info("✅ Passes images sent successfully")

    except Exception as e:
        logger.error(f"❌ Error sending passes images: {e}")
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading_msg.message_id,
                text="❌ Не вдалося завантажити зображення. Спробуйте пізніше.",
                reply_markup=keyboard
            )
        except:
            await context.bot.send_message(chat_id=chat_id, text="❌ Помилка.", reply_markup=keyboard)


async def handle_ticket_static(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє всі статичні під-меню 'Квитків'."""
    query = update.callback_query
    await query.answer()

    key = query.data.split(":")[1]

    # Ігноруємо 'passes', бо він має свій окремий хендлер
    if key == "passes":
        return

    text = MESSAGES.get(f"tickets_{key}", "Інформація не знайдена.")
    keyboard = await get_back_keyboard("tickets_menu")

    try:
        await query.edit_message_text(
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"❌ Error in handle_ticket_static for key {key}: {e}")
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from config.messages import MESSAGES
from config.settings import (
    TICKET_PASSES_FILE_ID_1, TICKET_PASSES_FILE_ID_2
)
from handlers.common import get_back_keyboard # <-- Використовуємо get_back_keyboard
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
    data - словник з даними, які ми зібрали у хендлерах.
    """
    ticket_id = generate_ticket_id()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Визначаємо тип подяки для звіту
    gratitude_type = "Конкретна" if data.get('is_specific') else "Загальна"

    # Формуємо дані.
    # УВАГА: Структура списку залежить від вашої таблиці.
    # Я зробив припущення щодо порядку колонок A-H.
    # Колонка I (9-та) - це transport_type.

    transport_type = data.get('transport_type', '')  # Трамвай/Тролейбус або пусто

    row = [
        ticket_id,  # A: ID
        timestamp,  # B: Дата
        gratitude_type,  # C: Тип звернення
        data.get('message', ''),  # D: Текст подяки
        data.get('user_name', ''),  # E: Ім'я користувача (або водія для конкретної)
        data.get('vehicle_number', ''),  # F: Бортовий номер
        data.get('email', ''),  # G: Email
        "Новий",  # H: Статус
        transport_type  # I: Тип транспорту (Трамвай/Тролейбус)
    ]

    # Тут має бути виклик вашого клієнта для запису
    # Наприклад: await google_sheets_client.append_row("АркушПодяки", row)
    # Повертаємо ID, щоб показати користувачу
    return ticket_id


async def show_tickets_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показує меню 'Квитки та тарифи'.
    Обробляє як текстові повідомлення (edit), так і медіа (delete + reply).
    """
    query = update.callback_query
    await query.answer()

    # Перевіряємо, чи є ID медіа-повідомлень у user_data (залишені з show_passes_list)
    if 'media_message_ids' in context.user_data:
        chat_id = update.effective_chat.id
        # Проходимо по списку ID і видаляємо кожне повідомлення
        for msg_id in context.user_data['media_message_ids']:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                # Попередження, якщо повідомлення не вдалося видалити (напр., воно застаріле)
                logger.warning(f"Could not delete message {msg_id} in show_tickets_menu: {e}")

        # Очищуємо список, щоб не спробувати видалити їх знову
        del context.user_data['media_message_ids']

    keyboard = [
        [InlineKeyboardButton("💰 Вартість проїзду", callback_data="tickets:cost")],
        [InlineKeyboardButton("💳 Способи оплати", callback_data="tickets:payment")],
        [InlineKeyboardButton("🧾 Види проїзних", callback_data="tickets:passes")],
        [InlineKeyboardButton("🏪 Де придбати?", callback_data="tickets:purchase")],
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
    """Надсилає 2 зображення за file_id, а потім текстове повідомлення."""
    query = update.callback_query

    # --- ПОКРАЩЕННЯ: Миттєво відповідаємо на запит ---
    # Це прибере "помилку" (тайм-аут) на кнопці у користувача
    await query.answer()

    keyboard = await get_back_keyboard("tickets_menu")
    purchase_info_text = MESSAGES.get("tickets_purchase_info")

    try:
        # 1. Видаляємо поточне повідомлення (меню "Квитки та тарифи")
        await query.delete_message()

        # 2. Надсилаємо перше зображення (миттєво, за file_id)
        sent_photo_1 = await query.message.reply_photo(
            photo=TICKET_PASSES_FILE_ID_1,
            caption="Види проїзних (Частина 1)"
        )

        # 3. Надсилаємо друге зображення (миттєво, за file_id)
        sent_photo_2 = await query.message.reply_photo(
            photo=TICKET_PASSES_FILE_ID_2,
            caption="Види проїзних (Частина 2)"
        )

        # 4. Зберігаємо ID надісланих фото для подальшого видалення
        context.user_data['media_message_ids'] = [sent_photo_1.message_id, sent_photo_2.message_id]

        # 5. Надсилаємо текстове повідомлення (з кнопками "Назад")
        await query.message.reply_text(
            text=purchase_info_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        logger.info("✅ Passes images (from file_id) sent successfully")

    except Exception as e:
        # Ця помилка може виникнути, якщо file_id стане недійсним
        logger.error(f"❌ Error sending passes images by file_id: {e}")
        await query.message.reply_text(
            "❌ Сталася помилка при завантаженні зображення (file_id invalid?).",
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
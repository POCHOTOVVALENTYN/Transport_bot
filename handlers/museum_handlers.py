import datetime

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from config.messages import MESSAGES
from handlers.common import get_back_keyboard
from bot.states import States
from utils.logger import logger
from config.settings import MUSEUM_LOGO_IMAGE, GOOGLE_SHEETS_ID, MUSEUM_ADMIN_ID
from telegram.constants import ParseMode
from integrations.google_sheets.client import GoogleSheetsClient


async def show_museum_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню 'Музей'."""
    query = update.callback_query
    await query.answer()

    # --- ПОЧАТОК ВИПРАВЛЕННЯ --- 03.11.2025
    # 1. Блок видалення медіа (фото)
    if 'media_message_ids' in context.user_data:
        chat_id = update.effective_chat.id
        for msg_id in context.user_data['media_message_ids']:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.warning(f"Could not delete message {msg_id} in show_museum_menu: {e}")

        # Очищуємо список
        del context.user_data['media_message_ids']
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    keyboard = [
        [InlineKeyboardButton("🖼️ Інфо про музей", callback_data="museum:info")],
        [InlineKeyboardButton("📱 Соц. мережі музею", callback_data="museum:socials")],
        [InlineKeyboardButton("🗓️ Запис на екскурсію", callback_data="museum:register_start")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text="🏛️ Розділ 'Музей КП 'ОМЕТ''. Оберіть опцію:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
# --- НОВА ФУНКЦІЇЯ (Надсилання зображення та інформації) --- 03.11.2025 р. 11:28

async def show_museum_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Надсилає фото логотип та інформацію про музей."""
    query = update.callback_query
    await query.answer()

    keyboard = await get_back_keyboard("museum_menu")
    caption_text = MESSAGES.get("museum_info")

    try:
        # 1. Видаляємо поточне повідомлення (меню "Музей")
        await query.delete_message()

        # 2. Надсилаємо фото
        with open(MUSEUM_LOGO_IMAGE, 'rb') as photo:
            # --- ПОЧАТОК ЗМІН ---
            # Зберігаємо надіслане повідомлення у змінну
            sent_photo = await query.message.reply_photo(
                photo=photo,
                # Ви можете додати короткий підпис до самого фото, якщо хочете
                # caption="Логотип Музею",
            )

            # Додаємо ID фото у user_data
        context.user_data['media_message_ids'] = [sent_photo.message_id]
        # --- КІНЕЦЬ ЗМІН ---

        # 3. Надсилаємо основний текст з кнопками "Назад"
        await query.message.reply_text(
            text=caption_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        logger.info("✅ Museum info and logo sent successfully")

    except FileNotFoundError:
        logger.error(f"❌ Museum logo file not found: {MUSEUM_LOGO_IMAGE}")
        await query.message.reply_text(
            "❌ Файл з логотипом музею не знайдено. Спробуйте пізніше.",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"❌ Error sending museum info: {e}")
        await query.message.reply_text(
            "❌ Сталася помилка при завантаженні інформації.",
            reply_markup=keyboard
        )
# --- КІНЕЦЬ НОВОЇ ФУНКЦІЇ --- 03.11.2025 р. 11:28

async def handle_museum_static(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє статичні під-меню 'Музей'."""
    query = update.callback_query
    await query.answer()

    # Оскільки ця функція тепер обробляє лише 'museum:socials'
    # (згідно з bot.py), ми можемо жорстко задати клавіатуру

    text = "👇 Оберіть соціальну мережу музею:"

    keyboard = [
        [InlineKeyboardButton("📘 Facebook Музею", url="https://www.facebook.com/museumoget")],
        [InlineKeyboardButton("📸 Instagram Музею", url="https://www.instagram.com/museum_kp_omet")],
        # Додаємо стандартні кнопки навігації
        [InlineKeyboardButton("⬅️ Назад", callback_data="museum_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Редагуємо повідомлення, показуючи нові кнопки
    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        disable_web_page_preview=True  # Вимикаємо превью посилань у самому повідомленні
    )


async def museum_register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок реєстрації до музею (ДИНАМІЧНИЙ)."""
    query = update.callback_query
    await query.answer()

    try:
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        # Читаємо дати з аркуша "MuseumDates", стовпець A
        dates_data = sheets.read_range(sheet_range="MuseumDates!A1:A50")

        if not dates_data:
            keyboard = await get_back_keyboard("museum_menu")
            await query.edit_message_text(
                text="😢 На жаль, наразі вільних дат для запису немає. Спробуйте пізніше.",
                reply_markup=keyboard
            )
            return ConversationHandler.END

        keyboard = []
        text = "🗓️ Оберіть вільну дату та час для екскурсії:\n"

        for row in dates_data:
            if row: # Якщо рядок не пустий
                date_str = row[0]
                # 'callback_data' тепер містить саму дату
                keyboard.append([InlineKeyboardButton(date_str, callback_data=f"museum_date:{date_str}")])

        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="museum_menu")])

        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return States.MUSEUM_DATE

    except Exception as e:
        logger.error(f"Failed to read museum dates from sheets: {e}")
        keyboard = await get_back_keyboard("museum_menu")
        await query.edit_message_text(
            text=f"❌ Сталася помилка при завантаженні дат: {e}",
            reply_markup=keyboard
        )
        return ConversationHandler.END


async def museum_get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує обрану дату (вона тепер у callback_data)."""
    query = update.callback_query
    await query.answer()

    # Ми більше не перевіряємо "other", оскільки такої кнопки немає

    selected_date = query.data.split(":")[1]
    context.user_data['museum_date'] = selected_date

    await query.edit_message_text("Вкажіть кількість осіб у вашій групі (напишіть цифрою):")
    return States.MUSEUM_PEOPLE_COUNT


async def museum_get_people_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує кількість осіб."""
    try:
        count = int(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Будь ласка, введіть число. Скільки осіб?")
        return States.MUSEUM_PEOPLE_COUNT

    if count == 1:
        keyboard = await get_back_keyboard("museum_menu")
        await update.message.reply_text(
            "😢 На жаль, екскурсії проводяться для груп від 2-х осіб. "
            "Будь ласка, зателефонуйте 050-399-42-11, можливо, ми зможемо додати вас до вже існуючої групи.",
            reply_markup=keyboard
        )
        return ConversationHandler.END

    if count > 10:
        keyboard = await get_back_keyboard("museum_menu")
        await update.message.reply_text(
            "📞 Для груп понад 10 осіб потрібна індивідуальна домовленість. "
            "Будь ласка, зателефонуйте організатору за номером 050-399-42-11.",
            reply_markup=keyboard
        )
        return ConversationHandler.END

    context.user_data['museum_people_count'] = count
    await update.message.reply_text("✅ Чудово! Вкажіть Ваші ПІБ та контактний телефон для підтвердження реєстрації.")
    return States.MUSEUM_CONTACT_INFO


async def museum_save_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Зберігає реєстрацію, пише в Sheet ТА надсилає адміну."""
    contact_info = update.message.text

    date = context.user_data.get('museum_date', 'НЕ ВКАЗАНО')
    count = context.user_data.get('museum_people_count', 'НЕ ВКАЗАНО')

    logger.info(f"New museum registration: {date}, {count} people, contact: {contact_info}")

    # --- ЗБЕРІГАЄМО В GOOGLE SHEETS ("MuseumBookings") ---
    try:
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        row_data = [
            datetime.now().strftime("%d.%m.%Y %H:%M"), # Час заявки
            date, # Обрана дата
            count, # Кількість
            contact_info # ПІБ + Телефон
        ]
        sheets.append_row(sheet_name="MuseumBookings", values=row_data)
        logger.info("✅ Museum booking saved to Google Sheets")

    except Exception as e:
        logger.error(f"❌ FAILED to save museum booking to Google Sheets: {e}")
        # Не зупиняємо процес, головне - повідомити адміна

    # --- НАДСИЛАЄМО ПОВІДОМЛЕННЯ АДМІНУ (Максиму) ---
    try:
        admin_message = (
            f"🔔 Нова заявка на екскурсію до Музею!\n\n"
            f"🗓 <b>Дата:</b> {date}\n"
            f"👥 <b>Кількість:</b> {count}\n"
            f"👤 <b>Контакти:</b> {contact_info}"
        )
        await context.bot.send_message(
            chat_id=MUSEUM_ADMIN_ID,
            text=admin_message,
            parse_mode=ParseMode.HTML
        )
        logger.info(f"✅ Museum booking notification sent to MUSEUM_ADMIN_ID {MUSEUM_ADMIN_ID}")


    except Exception as e:

        logger.error(f"❌ FAILED to send museum booking to MUSEUM_ADMIN_ID {MUSEUM_ADMIN_ID}: {e}")
        # Повідомляємо користувача, що сталася помилка
        keyboard = await get_back_keyboard("main_menu")
        await update.message.reply_text(
            "❌ Сталася помилка при надсиланні вашої заявки. Будь ласка, спробуйте пізніше.",
            reply_markup=keyboard
        )
        context.user_data.clear()
        return ConversationHandler.END

    # --- Відповідь користувачу ---
    keyboard = await get_back_keyboard("main_menu")
    await update.message.reply_text(
        "✅ Дякуємо! Ваша заявка прийнята. Організатор зв'яжеться з вами для підтвердження.",
        reply_markup=keyboard
    )
    context.user_data.clear()
    return ConversationHandler.END
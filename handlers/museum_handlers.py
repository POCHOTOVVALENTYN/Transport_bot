from datetime import datetime
import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from config.messages import MESSAGES
from handlers.common import get_back_keyboard, get_cancel_keyboard
from bot.states import States
from services import museum_service
from utils.logger import logger
from config.settings import MUSEUM_LOGO_IMAGE, GOOGLE_SHEETS_ID, MUSEUM_ADMIN_ID
from telegram.constants import ParseMode
from integrations.google_sheets.client import GoogleSheetsClient
from services.museum_service import MuseumService


async def show_museum_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показує меню 'Музей'.
    Завершує будь-який активний діалог (напр. реєстрацію).
    """
    query = update.callback_query
    await query.answer()

    # --- ВИДАЛЯЄМО ПОВІДОМЛЕННЯ З КНОПКОЮ "СКАСУВАТИ" ---
    if 'cancel_message_id' in context.user_data:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['cancel_message_id']
            )
            logger.info(f"✅ Deleted cancel button message: {context.user_data['cancel_message_id']}")
        except Exception as e:
            logger.warning(f"Could not delete cancel message: {e}")
        del context.user_data['cancel_message_id']

    # --- ВИДАЛЯЄМО ФОТО ---
    if 'media_message_ids' in context.user_data:
        chat_id = update.effective_chat.id
        for msg_id in context.user_data['media_message_ids']:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.warning(f"Could not delete message {msg_id}: {e}")
        del context.user_data['media_message_ids']

    # Видаляємо останнє повідомлення-запитання з діалогу (якщо воно є)
    if 'dialog_message_id' in context.user_data:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['dialog_message_id']
            )
        except Exception as e:
            logger.warning(f"Could not delete dialog message on cancel (museum): {e}")
        del context.user_data['dialog_message_id']

    # --- ВИДАЛЯЄМО ПОВІДОМЛЕННЯ З ДАТАМИ ---
    if 'dates_message_id' in context.user_data:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=context.user_data['dates_message_id']
            )
            logger.info(f"✅ Deleted dates message: {context.user_data['dates_message_id']}")
        except Exception as e:
            logger.warning(f"Could not delete dates message: {e}")
        del context.user_data['dates_message_id']

    # --- ВИДАЛЯЄМО ПОТОЧНЕ ПОВІДОМЛЕННЯ (якщо воно ще існує) ---
    # ВАЖЛИВО: Це може бути те саме повідомлення, яке ми вже видалили вище
    # Тому просто ігноруємо помилку
    try:
        await query.message.delete()
        logger.info(f"✅ Deleted current message in show_museum_menu")
    except Exception as e:
        # Це нормально - повідомлення могло бути вже видалене
        logger.info(f"ℹ️ Current message already deleted or not found: {e}")

    # Очищуємо всі дані реєстрації
    context.user_data.pop('museum_date', None)
    context.user_data.pop('museum_people_count', None)
    context.user_data.pop('museum_name', None)

    keyboard = [
        [InlineKeyboardButton("🖼️ Інфо про музей", callback_data="museum:info")],
        [InlineKeyboardButton("📱 Соц. мережі музею", callback_data="museum:socials")],
        [InlineKeyboardButton("🗓️ Запис на екскурсію", callback_data="museum:register_start")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🏛️ Розділ 'Музей КП 'ОМЕТ''. Оберіть опцію:"

    # Надсилаємо НОВЕ повідомлення
    await query.message.reply_text(
        text=text,
        reply_markup=reply_markup
    )

    return ConversationHandler.END


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
    # --- КРИТИЧНЕ ЛОГУВАННЯ ---
    logger.info(f"🔥 museum_register_start CALLED by user {update.effective_user.id}")
    logger.info(f"🔥 Update type: {type(update)}")
    logger.info(f"🔥 Has callback_query: {update.callback_query is not None}")
    if update.callback_query:
        logger.info(f"🔥 Callback data: {update.callback_query.data}")
    # --- КІНЕЦЬ ЛОГУВАННЯ ---

    query = update.callback_query
    await query.answer()

    #Логування для діагностики
    logger.info(f"User {update.effective_user.id} started museum registration. Context: {context.user_data}")

    # ЗАМІСТЬ прямого виклику GoogleSheetsClient:
    try:
        # Викликаємо наш розумний метод з кешуванням
        dates_list = await museum_service.get_available_dates()

        # --- ДОДАНО: Діагностичне логування ---
        #logger.info(f"📊 Google Sheets read result: {dates_data}")
        #logger.info(f"📊 Number of dates loaded: {len(dates_data) if dates_data else 0}")
        # --- КІНЕЦЬ ДОДАВАННЯ ---

        if not dates_list:
            keyboard = await get_back_keyboard("museum_menu")
            # --- ВИПРАВЛЕННЯ: Видаляємо + надсилаємо нове ---
            await query.message.delete()
            await query.message.reply_text(
                text="😢 На жаль, наразі вільних дат для запису немає. Спробуйте пізніше.",
                reply_markup=keyboard
            )
            # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---
            return ConversationHandler.END

        keyboard = []
        for date_str in dates_list:
            keyboard.append([InlineKeyboardButton(date_str, callback_data=f"museum_date:{date_str}")])

        for row in dates_list:
            if row: # Якщо рядок не пустий
                date_str = row[0]
                # 'callback_data' тепер містить саму дату
                keyboard.append([InlineKeyboardButton(date_str, callback_data=f"museum_date:{date_str}")])

        keyboard.append([
            InlineKeyboardButton("⬅️ Назад", callback_data="museum_menu"),
            InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")
        ])

        # --- ВИПРАВЛЕННЯ: Видаляємо старе повідомлення + надсилаємо нове ---
        await query.message.delete()
        sent_message = await query.message.reply_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        # Зберігаємо ID нового повідомлення
        context.user_data['dialog_message_id'] = sent_message.message_id
        # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---
        return States.MUSEUM_DATE


    except Exception as e:

        logger.error(f"Error: {e}")
        keyboard = await get_back_keyboard("museum_menu")
        # --- ВИПРАВЛЕННЯ: Видаляємо + надсилаємо нове ---
        await query.message.delete()
        await query.message.reply_text(
            text=f"❌ Сталася помилка при завантаженні дат: {e}",
            reply_markup=keyboard
        )
        # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---
        return ConversationHandler.END


async def museum_get_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує обрану дату (вона тепер у callback_data)."""
    query = update.callback_query
    await query.answer()

    # Ми більше не перевіряємо "other", оскільки такої кнопки немає

    selected_date = query.data.split(":")[1]
    context.user_data['museum_date'] = selected_date

    keyboard = await get_cancel_keyboard("museum_menu")

    # --- ВИПРАВЛЕННЯ: Видаляємо повідомлення з датами ---
    try:
        # 1. Видаляємо список дат
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']  # <-- Використовуємо новий ключ
        )
    except Exception as e:
        logger.warning(f"Could not delete dates message in museum_get_date: {e}")
    keyboard = await get_cancel_keyboard("museum_menu")  # <-- Кнопка "Скасувати реєстрацію"

    # 2. Надсилаємо нове запитання
    sent_message = await query.message.reply_text(
        "Вкажіть кількість осіб у вашій групі (напишіть цифрою):",
        reply_markup=keyboard
    )
    # 3. Зберігаємо ID нового запитання
    context.user_data['dialog_message_id'] = sent_message.message_id

    return States.MUSEUM_PEOPLE_COUNT


async def museum_get_people_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує кількість осіб та запитує ПІБ."""
    await update.message.delete() # 1. Видаляємо відповідь користувача

    try:
        count_text = update.message.text
        count = int(count_text)
    except ValueError:
        count = 0 # Якщо ввели не число

    keyboard = await get_cancel_keyboard("museum_menu")

    # 2. Видаляємо попереднє запитання бота
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete people count message: {e}")

    # ВАЛІДАЦІЯ (як у вас і було)
    if count <= 0:
        sent_message = await update.message.reply_text(
            "❌ Введіть коректну кількість осіб (цифрою, більше 0).",
            reply_markup=keyboard
        )
        context.user_data['dialog_message_id'] = sent_message.message_id
        return States.MUSEUM_PEOPLE_COUNT # Повертаємо на той самий крок

    if count > 10:
        # Це кінець діалогу, просто надсилаємо повідомлення (ID не зберігаємо)
        await update.message.reply_text(
            "Для груп понад 10 осіб потрібна індивідуальна домовленість.\n"
            "Будь ласка, зателефонуйте організатору за номером <code>050-399-42-11</code>.",
            reply_markup=await get_back_keyboard("museum_menu"), # Кнопка "Назад"
            parse_mode=ParseMode.HTML
        )
        context.user_data.clear()
        return ConversationHandler.END # Завершуємо

    # Валідація пройдена:
    context.user_data['museum_people_count'] = count
    logger.info(f"People count: {count}")

    # 3. Надсилаємо нове запитання
    sent_message = await update.message.reply_text(
        "✅ Чудово! Тепер вкажіть Ваше П.І.Б. (наприклад: Писаренко Олег Анатолійович):",
        reply_markup=keyboard
    )
    # 4. Зберігаємо ID нового запитання
    context.user_data['dialog_message_id'] = sent_message.message_id

    return States.MUSEUM_NAME

async def museum_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує ПІБ, ВАЛІДУЄ його та запитує телефон."""
    await update.message.delete()  # 1. Видаляємо відповідь користувача
    name_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("museum_menu")

    # 2. Видаляємо попереднє запитання бота
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete name message: {e}")

    # --- ПОЧАТОК БЛОКУ ВАЛІДАЦІЇ ПІБ ---
    if not re.match(r"^[А-Яа-яЇїІіЄєҐґA-Za-z\s'-]{5,}$", name_text):
        sent_message = await update.message.reply_text(
            f"❌ Будь ласка, введіть коректне П.І.Б. (тільки літери, довжина від 5 символів).",
            reply_markup=keyboard
        )
        context.user_data['dialog_message_id'] = sent_message.message_id
        return States.MUSEUM_NAME  # Повертаємо на той самий крок
    # --- КІНЕЦЬ БЛОКУ ВАЛІДАЦІЇ ---

    # Валідація пройдена:
    context.user_data['museum_name'] = name_text
    logger.info(f"Museum Name: {name_text}")

    # 3. Надсилаємо нове запитання
    sent_message = await update.message.reply_text(
        "📞 Вкажіть контактний телефон для підтвердження (наприклад: 0994564778):",
        reply_markup=keyboard
    )
    # 4. Зберігаємо ID нового запитання
    context.user_data['dialog_message_id'] = sent_message.message_id

    return States.MUSEUM_PHONE


# handlers/museum_handlers.py

async def museum_get_phone_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує, ВАЛІДУЄ телефон та зберігає реєстрацію."""

    await update.message.delete()  # 1. Видаляємо відповідь користувача (телефон)
    phone_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("museum_menu")

    # 2. Видаляємо попереднє запитання бота
    try:
        await context.bot.delete_message(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['dialog_message_id']
        )
    except Exception as e:
        logger.warning(f"Could not delete final museum message: {e}")

    # --- ПОЧАТОК БЛОКУ ВАЛІДАЦІЇ ТЕЛЕФОНУ ---
    # Очищуємо номер від пробілів та дефісів перед перевіркою
    cleaned_phone = phone_text.replace(" ", "").replace("-", "")

    if not re.match(r"^(\+?38)?0\d{9}$", cleaned_phone):
        sent_message = await update.message.reply_text(
            f"❌ Не схоже на український номер телефону.\n\n"
            f"Будь ласка, введіть номер у форматі <code>0991234567</code> (10 цифр).",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
        context.user_data['dialog_message_id'] = sent_message.message_id
        return States.MUSEUM_PHONE  # Повертаємо на той самий крок
    # --- КІНЕЦЬ БЛОКУ ВАЛІДАЦІЇ ---

    # Валідація пройдена, збираємо дані:
    # Збираємо дані
    date = context.user_data.get('museum_date')
    count = context.user_data.get('museum_people_count')
    name = context.user_data.get('museum_name')
    phone = phone_text

    # ЗАМІСТЬ запису в Google Sheets напряму:
    success = await museum_service.create_booking(date, count, name, phone)
        # Не зупиняємо процес, головне - повідомити адміна

    # --- НАДСИЛАЄМО ПОВІДОМЛЕННЯ АДМІНУ (Максиму) ---
    if success:
        try:
            admin_message = (
                f"🔔 Нова заявка на екскурсію до Музею!\n\n"
                f"🗓 <b>Дата екскурсії:</b> {date}\n"
                f"👥 <b>Кількість:</b> {count}\n"
                f"👤 <b>ПІБ:</b> {name}\n"
                f"📞 <b>Телефон:</b> {phone}"
            )

            keyboard_admin = [
                [InlineKeyboardButton("⚙️ Адмін-панель", callback_data="admin_menu_show")]
            ]
            reply_markup_admin = InlineKeyboardMarkup(keyboard_admin)

            await context.bot.send_message(
                chat_id=MUSEUM_ADMIN_ID,
                text=admin_message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup_admin
            )
            logger.info(f"✅ Museum booking notification sent to MUSEUM_ADMIN_ID {MUSEUM_ADMIN_ID}")

    else:
        except Exception as e:
            logger.error(f"❌ FAILED to send museum booking to MUSEUM_ADMIN_ID {MUSEUM_ADMIN_ID}: {e}")
            # Повідомляємо користувача, що сталася помилка
            keyboard_final = await get_back_keyboard("main_menu")
            await update.message.reply_text(
                "❌ Сталася помилка при надсиланні вашої заявки. Будь ласка, спробуйте пізніше.",
                reply_markup=keyboard_final
            )
            context.user_data.clear()
            return ConversationHandler.END

        # --- Відповідь користувачу ---
        keyboard_final = await get_back_keyboard("main_menu")
        await update.message.reply_text(
            "✅ Дякуємо! Ваша заявка прийнята. Організатор зв'яжеться з вами для підтвердження.",
            reply_markup=keyboard_final
        )
        context.user_data.clear()
        return ConversationHandler.END
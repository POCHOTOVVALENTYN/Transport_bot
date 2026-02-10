from datetime import datetime
import re
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from config.messages import MESSAGES
from config.settings import MUSEUM_LOGO_IMAGE, MUSEUM_ADMIN_ID # GOOGLE_SHEETS_ID вже не потрібен тут
from handlers.common import get_back_keyboard, get_cancel_keyboard
from bot.states import States
from utils.logger import logger

# Імпорт  нового сервісу
from services.museum_service import MuseumService

# Ініціалізація сервісу (один раз)
museum_service = MuseumService()


async def _edit_museum_dialog_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    parse_mode: Optional[str] = None,
):
    msg_id = context.user_data.get('dialog_message_id')
    if msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return msg_id
        except Exception as e:
            logger.warning(f"Could not edit museum dialog message {msg_id}: {e}")

    sent_message = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )
    context.user_data['dialog_message_id'] = sent_message.message_id
    return sent_message.message_id


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

    # --- ВИПРАВЛЕННЯ: РЕДАГУВАННЯ ЗАМІСТЬ ВИДАЛЕННЯ ---
    try:
        # Спроба 1: Просто змінити текст і кнопки (найплавніший варіант)
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup
        )
    except Exception:
        # Спроба 2: Якщо старе повідомлення було з фото, редагування тексту не спрацює.
        # Тоді просто надсилаємо нове.
        await query.message.reply_text(
            text=text,
            reply_markup=reply_markup
        )

    return ConversationHandler.END


async def show_museum_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Надсилає фото логотип та інформацію про музей."""
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("ℹ️ Більше інформації", url="https://oget.od.ua/muzei/")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="museum_menu")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ])
    caption_text = MESSAGES.get("museum_info")

    try:
        # 1. Редагуємо меню "Музей" на інформаційний текст
        try:
            await query.edit_message_text(
                text=caption_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        except Exception:
            await query.message.reply_text(
                text=caption_text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )

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
        media_ids = context.user_data.get('media_message_ids', [])
        media_ids.append(sent_photo.message_id)
        context.user_data['media_message_ids'] = media_ids
        # --- КІНЕЦЬ ЗМІН ---

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

    user = update.effective_user
    logger.info(f"🔥 museum_register_start CALLED by user {user.id}")

    try:
        # 1. МИТТЄВА РЕАКЦІЯ: Показуємо "Завантаження..." замість видалення
        # Це запобігає "пустому екрану"
        try:
            await query.edit_message_text(
                text="⏳ <b>Завантажую вільні дати...</b>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

            # 2. Отримуємо дати (поки юзер бачить "Завантаження")
        dates_list = await museum_service.get_available_dates()

        # 2. Якщо дат немає
        if not dates_list:
            if not dates_list:
                keyboard = await get_back_keyboard("museum_menu")
                # Редагуємо повідомлення "Завантаження" на помилку
                await query.edit_message_text(
                    text="😢 На жаль, наразі вільних дат для запису немає. Спробуйте пізніше.",
                    reply_markup=keyboard
                )
                return ConversationHandler.END

        # 3. Формуємо клавіатуру (ОДИН РАЗ)
        keyboard = []
        for date_str in dates_list:
            # Створюємо кнопку для кожної дати
            keyboard.append([InlineKeyboardButton(date_str, callback_data=f"museum_date:{date_str}")])

        # Додаємо кнопки навігації
        keyboard.append([
            InlineKeyboardButton("⬅️ Назад", callback_data="museum_menu"),
            InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")
        ])

        text = "🗓️ Оберіть вільну дату та час для екскурсії:\n"

        # 4. РЕДАГУЄМО повідомлення "Завантаження" на список дат
        sent_message = await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # Зберігаємо ID для подальшого видалення
        context.user_data['dialog_message_id'] = sent_message.message_id
        return States.MUSEUM_DATE

    except Exception as e:
        logger.error(f"Error in museum_register_start: {e}", exc_info=True)
        keyboard = await get_back_keyboard("museum_menu")

        # Показуємо повідомлення про помилку
        await query.message.reply_text(
            text=f"❌ Сталася технічна помилка при завантаженні дат. Спробуйте пізніше.",
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

    keyboard = await get_cancel_keyboard("museum_menu")

    keyboard = await get_cancel_keyboard("museum_menu")  # <-- Кнопка "Скасувати реєстрацію"

    # 2. Редагуємо повідомлення зі списком дат на наступне питання
    context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
        context,
        update.effective_chat.id,
        "Вкажіть кількість осіб у вашій групі (напишіть цифрою):",
        keyboard
    )

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

    # ВАЛІДАЦІЯ (як у вас і було)
    if count <= 0:
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "❌ Введіть коректну кількість осіб (цифрою, більше 0).",
            keyboard
        )
        return States.MUSEUM_PEOPLE_COUNT # Повертаємо на той самий крок

    if count > 10:
        # Це кінець діалогу, просто надсилаємо повідомлення (ID не зберігаємо)
        await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "Для груп понад 10 осіб потрібна індивідуальна домовленість.\n"
            "Будь ласка, зателефонуйте організатору за номером <code>050-399-42-11</code>.",
            await get_back_keyboard("museum_menu"), # Кнопка "Назад"
            ParseMode.HTML
        )
        context.user_data.clear()
        return ConversationHandler.END # Завершуємо

    # Валідація пройдена:
    context.user_data['museum_people_count'] = count
    logger.info(f"People count: {count}")

    # 3. Редагуємо повідомлення на наступне запитання
    context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
        context,
        update.effective_chat.id,
        "✅ Чудово! Тепер вкажіть Ваше П.І.Б. (наприклад: Писаренко Олег Анатолійович):",
        keyboard
    )

    return States.MUSEUM_NAME

async def museum_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує ПІБ, ВАЛІДУЄ його та запитує телефон."""
    await update.message.delete()  # 1. Видаляємо відповідь користувача
    name_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("museum_menu")

    # --- ПОЧАТОК БЛОКУ ВАЛІДАЦІЇ ПІБ ---
    if not re.match(r"^[А-Яа-яЇїІіЄєҐґA-Za-z\s'-]{5,}$", name_text):
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            f"❌ Будь ласка, введіть коректне П.І.Б. (тільки літери, довжина від 5 символів).",
            keyboard
        )
        return States.MUSEUM_NAME  # Повертаємо на той самий крок
    # --- КІНЕЦЬ БЛОКУ ВАЛІДАЦІЇ ---

    # Валідація пройдена:
    context.user_data['museum_name'] = name_text
    logger.info(f"Museum Name: {name_text}")

    # 3. Редагуємо повідомлення на наступне запитання
    context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
        context,
        update.effective_chat.id,
        "📞 Вкажіть контактний телефон для підтвердження (наприклад: 0994564778):",
        keyboard
    )

    return States.MUSEUM_PHONE


# handlers/museum_handlers.py

async def museum_get_phone_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує телефон, валідує його, зберігає в БД та повідомляє адміна."""

    # 1. Видаляємо відповідь користувача
    await update.message.delete()
    phone_text = update.message.text.strip()

    # Клавіатура для скасування (на випадок помилки валідації)
    keyboard_cancel = await get_cancel_keyboard("museum_menu")

    # --- ВАЛІДАЦІЯ ТЕЛЕФОНУ ---
    cleaned_phone = phone_text.replace(" ", "").replace("-", "")
    if not re.match(r"^(\+?38)?0\d{9}$", cleaned_phone):
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            f"❌ Не схоже на український номер телефону.\n\n"
            f"Будь ласка, введіть номер у форматі <code>0991234567</code> (10 цифр).",
            keyboard_cancel,
            ParseMode.HTML
        )
        return States.MUSEUM_PHONE  # Повертаємо на той самий крок

    # --- ЗБІР ДАНИХ ---
    date = context.user_data.get('museum_date', 'Не вказано')
    count = context.user_data.get('museum_people_count', 0)
    name = context.user_data.get('museum_name', 'Не вказано')
    phone = phone_text

    # --- ЗБЕРЕЖЕННЯ В БД (SQLite) ---
    # Це відбувається миттєво
    success = await museum_service.create_booking(date, count, name, phone)

    if not success:
        # Якщо база даних не відповіла
        keyboard_final = await get_back_keyboard("main_menu")
        await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "❌ Сталася системна помилка при збереженні заявки. Спробуйте пізніше.",
            keyboard_final
        )
        context.user_data.clear()
        return ConversationHandler.END

    # --- ЯКЩО УСПІШНО ЗБЕРЕГЛИ В БД ---

    # 1. Повідомляємо Адміна (в блоці try, щоб помилка тут не лякала користувача)
    try:
        admin_message = (
            f"🔔 <b>Нова заявка на екскурсію!</b>\n"
            f"➖➖➖➖➖➖➖\n"
            f"🗓 <b>Дата:</b> {date}\n"
            f"👥 <b>Людей:</b> {count}\n"
            f"👤 <b>Ім'я:</b> {name}\n"
            f"📞 <b>Телефон:</b> {phone}\n"
            f"💾 <i>Збережено в локальній базі</i>"
        )

        keyboard_admin = [
            [InlineKeyboardButton("⚙️ Адмін-панель", callback_data="admin_menu_show")]
        ]

        await context.bot.send_message(
            chat_id=MUSEUM_ADMIN_ID,
            text=admin_message,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard_admin)
        )
        logger.info(f"✅ Museum notification sent to admin {MUSEUM_ADMIN_ID}")

    except Exception as e:
        # Якщо не вдалося відправити адміну, просто логуємо.
        # Користувачу про це знати не обов'язково, адже заявка вже в базі.
        logger.error(f"⚠️ Failed to send admin notification: {e}")

    # 2. Відповідь користувачу
    keyboard_final = await get_back_keyboard("main_menu")
    await _edit_museum_dialog_message(
        context,
        update.effective_chat.id,
        f"✅ <b>Заявку прийнято!</b>\n\n"
        f"Ми чекаємо вас <b>{date}</b>.\n"
        f"Адреса музею: <b>м. Одеса, площа Олексіївська, 21А.</b>",
        keyboard_final,
        ParseMode.HTML
    )

    context.user_data.clear()
    return ConversationHandler.END
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


def _build_museum_summary(context: ContextTypes.DEFAULT_TYPE) -> str:
    date = context.user_data.get('museum_date', 'Не вказано')
    count = context.user_data.get('museum_people_count', 'Не вказано')
    name = context.user_data.get('museum_name', 'Не вказано')
    phone = context.user_data.get('museum_phone', 'Не вказано')

    return (
        "🔍 <b>Перевірте дані заявки:</b>\n\n"
        f"🗓 <b>Дата:</b> {date}\n"
        f"👥 <b>Кількість:</b> {count}\n"
        f"👤 <b>ПІБ:</b> {name}\n"
        f"📞 <b>Телефон:</b> {phone}\n\n"
        "Все вірно?"
    )


def _clear_museum_edit_flags(context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('museum_edit_mode', None)
    context.user_data.pop('museum_edit_field', None)


async def museum_show_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Підтвердити", callback_data="museum_confirm_send")],
        [InlineKeyboardButton("✏️ Редагувати", callback_data="museum_edit")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="museum_menu")]
    ])

    context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
        context,
        update.effective_chat.id,
        _build_museum_summary(context),
        keyboard,
        ParseMode.HTML
    )
    return States.MUSEUM_CONFIRM


async def museum_edit_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗓 Дата", callback_data="museum_edit:date")],
        [InlineKeyboardButton("👥 Кількість", callback_data="museum_edit:people")],
        [InlineKeyboardButton("👤 ПІБ", callback_data="museum_edit:name")],
        [InlineKeyboardButton("📞 Телефон", callback_data="museum_edit:phone")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="museum_confirm_back")]
    ])

    context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
        context,
        update.effective_chat.id,
        "Що саме хочете відредагувати?",
        keyboard
    )
    return States.MUSEUM_EDIT_CHOICE


async def museum_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    field = query.data.split(":", 1)[1]
    context.user_data['museum_edit_mode'] = True
    context.user_data['museum_edit_field'] = field

    if field == "date":
        return await museum_register_start(update, context)

    if field == "people":
        keyboard = await get_cancel_keyboard("museum_menu")
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "Вкажіть кількість осіб у вашій групі (напишіть цифрою):",
            keyboard
        )
        return States.MUSEUM_PEOPLE_COUNT

    if field == "name":
        keyboard = await get_cancel_keyboard("museum_menu")
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "✅ Чудово! Тепер вкажіть Ваше П.І.Б. (наприклад: Писаренко Олег Анатолійович):",
            keyboard
        )
        return States.MUSEUM_NAME

    keyboard = await get_cancel_keyboard("museum_menu")
    context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
        context,
        update.effective_chat.id,
        "📞 Вкажіть контактний телефон для підтвердження (наприклад: 0994564778):",
        keyboard
    )
    return States.MUSEUM_PHONE


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
    context.user_data.pop('museum_phone', None)
    context.user_data.pop('museum_edit_mode', None)
    context.user_data.pop('museum_edit_field', None)

    keyboard = [
        [InlineKeyboardButton("🖼️ Інфо про музей", callback_data="museum:info")],
        [InlineKeyboardButton("📱 Соц. мережі музею", callback_data="museum:socials")],
        [InlineKeyboardButton("🗓️ Запис на екскурсію", callback_data="museum:register_start")],
        [InlineKeyboardButton("🎉 Запис на святкову екскурсію", callback_data="museum:holiday_register_start")],
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
        # Редагуємо меню "Музей" на інформаційний текст (без фото)
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

        logger.info("✅ Museum info sent successfully")
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

        if query.data == "museum:holiday_register_start":
            context.user_data['museum_type'] = 'holiday'
        elif query.data == "museum:register_start":
            context.user_data['museum_type'] = 'regular'

        excursion_type = context.user_data.get('museum_type', 'regular')

        # 2. Отримуємо дати (поки юзер бачить "Завантаження")
        if excursion_type == 'holiday':
            dates_list = await museum_service.get_available_holiday_dates()
        else:
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

    selected_date = query.data.split(":", 1)[1]
    context.user_data['museum_date'] = selected_date

    keyboard = await get_cancel_keyboard("museum_menu")

    if context.user_data.get('museum_edit_field') == "date":
        _clear_museum_edit_flags(context)
        return await museum_show_confirm(update, context)

    excursion_type = context.user_data.get('museum_type', 'regular')
    if excursion_type == 'holiday':
        count_exist = await museum_service.get_holiday_bookings_count(selected_date)
        if count_exist >= 20:
            keyboard_back = await get_back_keyboard("museum_menu")
            await query.edit_message_text(
                text="😔 Вільні місця закінчилися. КП 'ОМЕТ' приносить свої вибачення, потрібно очікувати іншу доступну святкову екскурсію. 🏛️",
                reply_markup=keyboard_back
            )
            context.user_data.clear()
            return ConversationHandler.END
        
        people_prompt = "Вкажіть кількість осіб у вашій групі (напишіть цифрою). Зверніть увагу: для святкової екскурсії максимальна кількість осіб в одній заявці — 3 людей:"
    else:
        people_prompt = "Вкажіть кількість осіб у вашій групі (напишіть цифрою):"

    # 2. Редагуємо повідомлення зі списком дат на наступне питання
    context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
        context,
        update.effective_chat.id,
        people_prompt,
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

    # ВАЛІДАЦІЯ
    if count <= 0:
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "❌ Введіть коректну кількість осіб (цифрою, більше 0).",
            keyboard
        )
        return States.MUSEUM_PEOPLE_COUNT # Повертаємо на той самий крок

    excursion_type = context.user_data.get('museum_type', 'regular')

    if excursion_type == 'holiday':
        if count > 3:
            context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
                context,
                update.effective_chat.id,
                "❌ Для святкової екскурсії максимальна кількість осіб в одній заявці — 3 людей. Будь ласка, введіть число від 1 до 3:",
                keyboard
            )
            return States.MUSEUM_PEOPLE_COUNT
    else:
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
            return ConversationHandler.END

    # Валідація пройдена:
    context.user_data['museum_people_count'] = count
    logger.info(f"People count: {count}")

    if context.user_data.get('museum_edit_field') == "people":
        _clear_museum_edit_flags(context)
        return await museum_show_confirm(update, context)

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

    if context.user_data.get('museum_edit_field') == "name":
        _clear_museum_edit_flags(context)
        return await museum_show_confirm(update, context)

    # 3. Редагуємо повідомлення на наступне запитання
    context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
        context,
        update.effective_chat.id,
        "📞 Вкажіть контактний телефон для підтвердження (наприклад: 0994564778):",
        keyboard
    )

    return States.MUSEUM_PHONE


# handlers/museum_handlers.py

async def museum_get_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує телефон, валідує його та переходить на підтвердження."""

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

    context.user_data['museum_phone'] = phone_text

    _clear_museum_edit_flags(context)
    return await museum_show_confirm(update, context)


async def museum_confirm_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фінальне збереження заявки після підтвердження."""
    query = update.callback_query
    await query.answer()

    # --- ЗБІР ДАНИХ ---
    date = context.user_data.get('museum_date', 'Не вказано')
    count = context.user_data.get('museum_people_count', 0)
    name = context.user_data.get('museum_name', 'Не вказано')
    phone = context.user_data.get('museum_phone', 'Не вказано')

    # --- ЗБЕРЕЖЕННЯ В БД (SQLite) ---
    # Це відбувається миттєво
    excursion_type = context.user_data.get('museum_type', 'regular')
    if excursion_type == 'holiday':
        # Перевіряємо ліміт ще раз (на випадок одночасних запитів)
        count_exist = await museum_service.get_holiday_bookings_count(date)
        if count_exist >= 20:
            keyboard_final = await get_back_keyboard("museum_menu")
            await _edit_museum_dialog_message(
                context,
                update.effective_chat.id,
                "😔 Вільні місця закінчилися. КП 'ОМЕТ' приносить свої вибачення, потрібно очікувати іншу доступну святкову екскурсію. 🏛️",
                keyboard_final
            )
            context.user_data.clear()
            return ConversationHandler.END
            
        success = await museum_service.create_holiday_booking(date, count, name, phone)
    else:
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
        title = "Нова заявка на святкову екскурсію!" if excursion_type == 'holiday' else "Нова заявка на екскурсію!"
        admin_message = (
            f"🔔 <b>{title}</b>\n"
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
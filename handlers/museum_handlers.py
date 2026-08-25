from datetime import datetime
import re
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from config.messages import MESSAGES
from config.settings import MUSEUM_LOGO_IMAGE, MUSEUM_ADMIN_ID, MUSEUM_ADMIN_IDS # GOOGLE_SHEETS_ID вже не потрібен тут
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


def _build_museum_summary(context: ContextTypes.DEFAULT_TYPE) -> str:
    date = context.user_data.get('museum_date', 'Не вказано')
    count = context.user_data.get('museum_people_count', 'Не вказано')
    name = context.user_data.get('museum_name', 'Не вказано')
    phone = context.user_data.get('museum_phone', 'Не вказано')
    excursion_type = context.user_data.get('museum_type', 'regular')

    summary = (
        "🔍 <b>Перевірте дані заявки:</b>\n\n"
        f"🗓 <b>Дата:</b> {date}\n"
        f"👥 <b>Кількість осіб:</b> {count}\n"
    )

    if excursion_type == 'holiday':
        participants = context.user_data.get('museum_participants', [])
        if participants:
            summary += "👥 <b>Перелік відвідувачів:</b>\n"
            for idx, p in enumerate(participants, 1):
                summary += f"  {idx}. {p['name']} ({p['age']} р.)\n"
        else:
            summary += f"👤 <b>ПІБ:</b> {name}\n"
    else:
        summary += f"👤 <b>ПІБ:</b> {name}\n"

    summary += f"📞 <b>Телефон:</b> {phone}\n\nВсе вірно?"
    return summary


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

    excursion_type = context.user_data.get('museum_type', 'regular')

    if field == "date":
        if excursion_type == 'holiday':
            dates = await museum_service.get_available_holiday_dates()
        else:
            dates = await museum_service.get_available_dates()

        if not dates:
            keyboard_back = await get_back_keyboard("museum_menu")
            await query.edit_message_text("Наразі немає доступних дат для редагування.", reply_markup=keyboard_back)
            return ConversationHandler.END

        keyboard_list = []
        for d in dates:
            keyboard_list.append([InlineKeyboardButton(f"🗓 {d}", callback_data=f"museum_date:{d}")])
        keyboard_list.append([InlineKeyboardButton("🚫 Скасувати", callback_data="museum_menu")])

        await query.edit_message_text("Оберіть нову дату:", reply_markup=InlineKeyboardMarkup(keyboard_list))
        return States.MUSEUM_DATE

    elif field == "people":
        keyboard = await get_cancel_keyboard("museum_menu")
        if excursion_type == 'holiday':
            available = context.user_data.get('holiday_available_places', 40)
            prompt = f"Оберіть або вкажіть нову кількість осіб (максимум 2 людини, доступно місць: {available}):"
            kb_people = InlineKeyboardMarkup([
                [InlineKeyboardButton("1 особа 👤", callback_data="museum_count:1"), InlineKeyboardButton("2 особи 👥", callback_data="museum_count:2")],
                [InlineKeyboardButton("🚫 Скасувати", callback_data="museum_menu")]
            ])
            await query.edit_message_text(prompt, reply_markup=kb_people)
        else:
            await query.edit_message_text("Вкажіть нову кількість осіб:", reply_markup=keyboard)
        return States.MUSEUM_PEOPLE_COUNT

    elif field == "name":
        keyboard = await get_cancel_keyboard("museum_menu")
        if excursion_type == 'holiday':
            context.user_data['museum_participants'] = []
            context.user_data['museum_current_participant_idx'] = 0
            count = context.user_data.get('museum_people_count', 1)
            p_prefix = "1-го " if count > 1 else ""
            await query.edit_message_text(f"👤 Вкажіть П.І.Б. {p_prefix}відвідувача:", reply_markup=keyboard)
            return States.MUSEUM_PARTICIPANT_NAME
        else:
            await query.edit_message_text("Вкажіть нове П.І.Б.:", reply_markup=keyboard)
            return States.MUSEUM_NAME

    elif field == "phone":
        keyboard = await get_cancel_keyboard("museum_menu")
        await query.edit_message_text("Вкажіть новий контактний телефон:", reply_markup=keyboard)
        return States.MUSEUM_PHONE

    return States.MUSEUM_CONFIRM


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
        if count_exist >= 40:
            keyboard_back = await get_back_keyboard("museum_menu")
            await query.edit_message_text(
                text="😔 Вільні місця на цю дату закінчилися (досягнуто ліміт 40 осіб). КП 'ОМЕТ' приносить свої вибачення, зачекайте на доступну іншу святкову екскурсію. 🏛️",
                reply_markup=keyboard_back
            )
            context.user_data.clear()
            return ConversationHandler.END

        available = 40 - count_exist
        context.user_data['holiday_available_places'] = available

        if available == 1:
            context.user_data['museum_people_count'] = 1
            context.user_data['museum_participants'] = []
            context.user_data['museum_current_participant_idx'] = 0
            people_prompt = (
                "ℹ️ На обрану дату залишилось <b>лише 1 вільне місце</b>. Автоматично обрано: 1 особа.\n\n"
                "👤 Введіть П.І.Б. відвідувача (тільки літери, довжина від 5 символів):"
            )
            context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
                context,
                update.effective_chat.id,
                people_prompt,
                keyboard,
                ParseMode.HTML
            )
            return States.MUSEUM_PARTICIPANT_NAME
        else:
            people_prompt = (
                f"Вкажіть кількість осіб у вашій групі (напишіть цифрою 1 чи 2 або оберіть кнопкою нижче).\n"
                f"⚠️ Зверніть увагу: для святкової екскурсії максимальна кількість осіб в одній заявці — <b>2 людей</b> (Вільних місць на дату: {available}):"
            )
            kb_people = InlineKeyboardMarkup([
                [InlineKeyboardButton("1 особа 👤", callback_data="museum_count:1"), InlineKeyboardButton("2 особи 👥", callback_data="museum_count:2")],
                [InlineKeyboardButton("🚫 Скасувати", callback_data="museum_menu")]
            ])
            context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
                context,
                update.effective_chat.id,
                people_prompt,
                kb_people,
                ParseMode.HTML
            )
            return States.MUSEUM_PEOPLE_COUNT
    else:
        people_prompt = "Вкажіть кількість осіб у вашій групі (напишіть цифрою):"
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            people_prompt,
            keyboard
        )
        return States.MUSEUM_PEOPLE_COUNT


async def museum_get_people_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує кількість осіб та переходить до запиту ПІБ."""
    is_callback = update.callback_query is not None

    if is_callback:
        query = update.callback_query
        await query.answer()
        try:
            count = int(query.data.split(":", 1)[1])
        except ValueError:
            count = 0
    else:
        await update.message.delete()
        try:
            count_text = update.message.text.strip()
            count = int(count_text)
        except ValueError:
            count = 0

    keyboard = await get_cancel_keyboard("museum_menu")

    if count <= 0:
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "❌ Введіть коректну кількість осіб (цифрою, більше 0).",
            keyboard
        )
        return States.MUSEUM_PEOPLE_COUNT

    excursion_type = context.user_data.get('museum_type', 'regular')

    if excursion_type == 'holiday':
        if count > 2:
            context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
                context,
                update.effective_chat.id,
                "❌ Для святкової екскурсії максимальна кількість осіб в одній заявці — <b>2 людей</b>. Будь ласка, введіть 1 або 2:",
                keyboard,
                ParseMode.HTML
            )
            return States.MUSEUM_PEOPLE_COUNT
        
        available = context.user_data.get('holiday_available_places', 40)
        if count > available:
            context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
                context,
                update.effective_chat.id,
                f"❌ На обрану дату залишилося тільки {available} вільних місць. Будь ласка, введіть число від 1 до {available}:",
                keyboard,
                ParseMode.HTML
            )
            return States.MUSEUM_PEOPLE_COUNT
    else:
        if count > 10:
            await _edit_museum_dialog_message(
                context,
                update.effective_chat.id,
                "Для груп понад 10 осіб потрібна індивідуальна домовленість.\n"
                "Будь ласка, зателефонуйте організатору за номером <code>050-399-42-11</code>.",
                await get_back_keyboard("museum_menu"),
                ParseMode.HTML
            )
            context.user_data.clear()
            return ConversationHandler.END

    context.user_data['museum_people_count'] = count
    logger.info(f"People count: {count}")

    if context.user_data.get('museum_edit_field') == "people":
        _clear_museum_edit_flags(context)
        return await museum_show_confirm(update, context)

    if excursion_type == 'holiday':
        context.user_data['museum_participants'] = []
        context.user_data['museum_current_participant_idx'] = 0
        p_prefix = "1-го " if count > 1 else ""
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            f"👤 Вкажіть П.І.Б. {p_prefix}відвідувача (тільки літери, довжина від 5 символів):",
            keyboard
        )
        return States.MUSEUM_PARTICIPANT_NAME
    else:
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "✅ Чудово! Тепер вкажіть Ваше П.І.Б. (наприклад: Писаренко Олег Анатолійович):",
            keyboard
        )
        return States.MUSEUM_NAME


async def museum_get_participant_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує ПІБ відвідувача святкової екскурсії та запитує його вік."""
    await update.message.delete()
    name_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("museum_menu")

    if not re.match(r"^[А-Яа-яЇїІіЄєҐґA-Za-z\s'-]{5,}$", name_text):
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "❌ Будь ласка, введіть коректне П.І.Б. (тільки літери, довжина від 5 символів).",
            keyboard
        )
        return States.MUSEUM_PARTICIPANT_NAME

    context.user_data['current_participant_name'] = name_text
    idx = context.user_data.get('museum_current_participant_idx', 0)
    count = context.user_data.get('museum_people_count', 1)
    prefix_str = f"{idx + 1}-го " if count > 1 else ""

    context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
        context,
        update.effective_chat.id,
        f"🎂 Вкажіть вік {prefix_str}відвідувача (числом від 1 до 100):",
        keyboard
    )
    return States.MUSEUM_PARTICIPANT_AGE


async def museum_get_participant_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує та валідує вік відвідувача (1..100)."""
    await update.message.delete()
    age_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("museum_menu")

    try:
        age = int(age_text)
        if not (1 <= age <= 100):
            raise ValueError()
    except ValueError:
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "❌ Будь ласка, введіть дійсний вік відвідувача (числом від 1 до 100):",
            keyboard
        )
        return States.MUSEUM_PARTICIPANT_AGE

    name = context.user_data.pop('current_participant_name', '')
    participants = context.user_data.get('museum_participants', [])
    participants.append({"name": name, "age": age})
    context.user_data['museum_participants'] = participants

    idx = context.user_data.get('museum_current_participant_idx', 0) + 1
    context.user_data['museum_current_participant_idx'] = idx
    count = context.user_data.get('museum_people_count', 1)

    if idx < count:
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            f"👤 Вкажіть П.І.Б. {idx + 1}-го відвідувача (тільки літери, довжина від 5 символів):",
            keyboard
        )
        return States.MUSEUM_PARTICIPANT_NAME
    else:
        context.user_data['museum_name'] = participants[0]['name']
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "📞 Вкажіть контактний телефон для підтвердження (наприклад: 0994564778):",
            keyboard
        )
        return States.MUSEUM_PHONE


async def museum_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує ПІБ, ВАЛІДУЄ його та запитує телефон."""
    await update.message.delete()
    name_text = update.message.text.strip()
    keyboard = await get_cancel_keyboard("museum_menu")

    if not re.match(r"^[А-Яа-яЇїІіЄєҐґA-Za-z\s'-]{5,}$", name_text):
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "❌ Будь ласка, введіть коректне П.І.Б. (тільки літери, довжина від 5 символів).",
            keyboard
        )
        return States.MUSEUM_NAME

    context.user_data['museum_name'] = name_text
    logger.info(f"Museum Name: {name_text}")

    if context.user_data.get('museum_edit_field') == "name":
        _clear_museum_edit_flags(context)
        return await museum_show_confirm(update, context)

    context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
        context,
        update.effective_chat.id,
        "📞 Вкажіть контактний телефон для підтвердження (наприклад: 0994564778):",
        keyboard
    )
    return States.MUSEUM_PHONE


async def museum_get_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримує телефон, валідує його та перевіряє на дублікати реєстрації."""
    await update.message.delete()
    phone_text = update.message.text.strip()
    keyboard_cancel = await get_cancel_keyboard("museum_menu")

    cleaned_phone = phone_text.replace(" ", "").replace("-", "")
    if not re.match(r"^(\+?38)?0\d{9}$", cleaned_phone):
        context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "❌ Не схоже на український номер телефону.\n\nБудь ласка, введіть номер у форматі <code>0991234567</code> (10 цифр).",
            keyboard_cancel,
            ParseMode.HTML
        )
        return States.MUSEUM_PHONE

    excursion_type = context.user_data.get('museum_type', 'regular')
    if excursion_type == 'holiday':
        selected_date = context.user_data.get('museum_date')
        has_booking = await museum_service.has_existing_holiday_booking(selected_date, phone_text)
        if has_booking:
            context.user_data['dialog_message_id'] = await _edit_museum_dialog_message(
                context,
                update.effective_chat.id,
                f"⚠️ З номера <code>{phone_text}</code> вже є зареєстрована заявка на обрану дату (<b>{selected_date}</b>).\n\nНа один номер телефону дозволено не більше 1 реєстрації на одну й ту саму дату.",
                keyboard_cancel,
                ParseMode.HTML
            )
            return States.MUSEUM_PHONE

    context.user_data['museum_phone'] = phone_text
    _clear_museum_edit_flags(context)
    return await museum_show_confirm(update, context)


async def museum_confirm_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фінальне збереження заявки після підтвердження."""
    query = update.callback_query
    await query.answer()

    date = context.user_data.get('museum_date', 'Не вказано')
    count = context.user_data.get('museum_people_count', 0)
    name = context.user_data.get('museum_name', 'Не вказано')
    phone = context.user_data.get('museum_phone', 'Не вказано')
    excursion_type = context.user_data.get('museum_type', 'regular')

    if excursion_type == 'holiday':
        count_exist = await museum_service.get_holiday_bookings_count(date)
        if count_exist + count > 40:
            keyboard_final = await get_back_keyboard("museum_menu")
            await _edit_museum_dialog_message(
                context,
                update.effective_chat.id,
                "😔 Вільні місця закінчилися. На жаль, інші користувачі щойно зайняли останні місця на цю дату. КП 'ОМЕТ' приносить свої вибачення. 🏛️",
                keyboard_final
            )
            context.user_data.clear()
            return ConversationHandler.END

        has_booking = await museum_service.has_existing_holiday_booking(date, phone)
        if has_booking:
            keyboard_final = await get_back_keyboard("museum_menu")
            await _edit_museum_dialog_message(
                context,
                update.effective_chat.id,
                f"⚠️ З номера {phone} вже є зареєстрована заявка на обрану дату ({date}).",
                keyboard_final
            )
            context.user_data.clear()
            return ConversationHandler.END

        import json
        participants = context.user_data.get('museum_participants', [])
        participants_json = json.dumps(participants, ensure_ascii=False) if participants else None

        success = await museum_service.create_holiday_booking(date, count, name, phone, participants_json)
    else:
        success = await museum_service.create_booking(date, count, name, phone)

    if not success:
        keyboard_final = await get_back_keyboard("main_menu")
        await _edit_museum_dialog_message(
            context,
            update.effective_chat.id,
            "❌ Сталася системна помилка при збереженні заявки. Спробуйте пізніше.",
            keyboard_final
        )
        context.user_data.clear()
        return ConversationHandler.END

    try:
        title = "Нова заявка на святкову екскурсію!" if excursion_type == 'holiday' else "Нова заявка на екскурсію!"
        participants = context.user_data.get('museum_participants', [])
        part_info = ""
        if participants:
            part_info = "\n👥 <b>Відвідувачі:</b>\n" + "\n".join([f"  • {p['name']} ({p['age']} р.)" for p in participants])

        admin_message = (
            f"🔔 <b>{title}</b>\n"
            f"➖➖➖➖➖➖➖\n"
            f"🗓 <b>Дата:</b> {date}\n"
            f"👥 <b>Людей:</b> {count}\n"
            f"{part_info}\n"
            f"📞 <b>Телефон:</b> {phone}\n"
            f"💾 <i>Збережено в локальній базі</i>"
        )

        keyboard_admin = [
            [InlineKeyboardButton("⚙️ Адмін-панель", callback_data="admin_menu_show")]
        ]

        for admin_id in MUSEUM_ADMIN_IDS:
            if not admin_id:
                continue
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard_admin)
                )
                logger.info(f"✅ Museum notification sent to admin {admin_id}")
            except Exception as e:
                logger.error(f"⚠️ Failed to send admin notification to {admin_id}: {e}")

    except Exception as e:
        logger.error(f"⚠️ Failed to send admin notification: {e}")

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
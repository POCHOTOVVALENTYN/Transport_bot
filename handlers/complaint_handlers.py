import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from services.tickets_service import TicketsService
from utils.logger import logger
from bot.states import States
from handlers.common import get_feedback_cancel_keyboard, safe_edit_prev_message


def clean_phone(phone_text: str) -> str | None:
    """Очищає та валідує номер телефону. Повертає формат +380... або None"""
    digits = re.sub(r'\D', '', phone_text)
    if len(digits) == 10 and digits.startswith('0'):
        return "+38" + digits
    if len(digits) == 12 and digits.startswith('380'):
        return "+" + digits
    if 9 <= len(digits) <= 15:
        return "+" + digits if phone_text.startswith('+') else digits
    return None


def is_valid_email(email_text: str) -> bool:
    """Проста перевірка формату email"""
    return bool(re.match(r'^[^@]+@[^@]+\.[^@]+$', email_text))


def _build_complaint_summary(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Будує підсумковий текст скарги для екрану підтвердження"""
    ctype = context.user_data.get('complaint_type', 'general')
    route = context.user_data.get('complaint_route', 'Не вказано')
    board = context.user_data.get('complaint_board', 'Не вказано')
    text = context.user_data.get('complaint_text', 'Не вказано')
    name = context.user_data.get('complaint_name', 'Не вказано')
    phone = context.user_data.get('complaint_phone', 'Не вказано')
    email = context.user_data.get('complaint_email', 'Не вказано')

    type_str = "📝 Загальна скарга" if ctype == 'general' else "🚋 Скарга на конкретний транспорт"

    summary = (
        "🔍 <b>Перевірте правильність введених даних:</b>\n\n"
        f"📌 <b>Тип скарги:</b> {type_str}\n"
    )
    if ctype == 'specific':
        summary += (
            f"🚋 <b>Маршрут:</b> {route}\n"
            f"🔢 <b>Бортовий номер:</b> {board}\n"
        )

    summary += (
        f"✍️ <b>Опис проблеми:</b> {text}\n"
        f"👤 <b>П.І.Б.:</b> {name}\n"
        f"📞 <b>Телефон:</b> {phone}\n"
        f"📧 <b>E-mail:</b> {email}\n\n"
        "Усе правильно?"
    )
    return summary


def _build_complaint_edit_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    """Будує меню вибору поля для редагування"""
    ctype = context.user_data.get('complaint_type', 'general')
    keyboard = []

    if ctype == 'specific':
        keyboard.append([
            InlineKeyboardButton("🚋 Маршрут", callback_data="complaint_edit:route"),
            InlineKeyboardButton("🔢 Бортовий номер", callback_data="complaint_edit:board")
        ])

    keyboard.append([InlineKeyboardButton("✍️ Опис проблеми", callback_data="complaint_edit:text")])
    keyboard.append([
        InlineKeyboardButton("👤 П.І.Б.", callback_data="complaint_edit:name"),
        InlineKeyboardButton("📞 Телефон", callback_data="complaint_edit:phone")
    ])
    keyboard.append([InlineKeyboardButton("📧 E-mail", callback_data="complaint_edit:email")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад до підтвердження", callback_data="complaint_edit_back")])

    return InlineKeyboardMarkup(keyboard)


async def complaint_show_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує екран перевірки введених даних"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Надіслати скаргу", callback_data="complaint_confirm_send")],
        [InlineKeyboardButton("✏️ Редагувати дані", callback_data="complaint_edit_menu")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ])

    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text=_build_complaint_summary(context),
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return States.COMPLAINT_CONFIRMATION


# ================= КРОКИ ДІАЛОГУ =================

async def complaint_start_simplified(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок подання скарги - запит типу"""
    query = update.callback_query
    await query.answer()

    # Очищуємо попередній стан
    context.user_data.pop('complaint_type', None)
    context.user_data.pop('complaint_route', None)
    context.user_data.pop('complaint_board', None)
    context.user_data.pop('complaint_text', None)
    context.user_data.pop('complaint_name', None)
    context.user_data.pop('complaint_phone', None)
    context.user_data.pop('complaint_email', None)
    context.user_data.pop('complaint_edit_mode', None)
    context.user_data.pop('complaint_edit_field', None)

    text = (
        "📨 <b>Подання скарги або пропозиції</b>\n\n"
        "Будь ласка, оберіть тип Вашої скарги:\n\n"
        "📝 <b>Загальна скарга</b> — стосується загальних питань роботи транспорту, зупинок чи обслуговування.\n"
        "🚋 <b>Скарга на конкретний транспорт</b> — стосується конкретного трамвая чи тролейбуса (маршрут, борт тощо)."
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Загальна скарга", callback_data="complaint_type:general")],
        [InlineKeyboardButton("🚋 Скарга на конкретний транспорт", callback_data="complaint_type:specific")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ])

    msg = await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='HTML')
    context.user_data['last_bot_msg_id'] = msg.message_id
    return States.COMPLAINT_CHOOSE_TYPE


async def complaint_choose_type_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка вибору типу скарги"""
    query = update.callback_query
    await query.answer()

    ctype = query.data.split(":", 1)[1]
    context.user_data['complaint_type'] = ctype

    if ctype == 'general':
        # Для загальної скарги пропускаємо транспортні поля
        context.user_data['complaint_route'] = 'Загальна скарга'
        context.user_data['complaint_board'] = 'Загальна скарга'

        text = (
            "✍️ <b>Опис скарги</b>\n\n"
            "Будь ласка, опишіть суть Вашої проблеми детально:"
        )
        keyboard = await get_feedback_cancel_keyboard("feedback_menu")
        await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='HTML')
        return States.COMPLAINT_TEXT

    else:
        # Для конкретної скарги просимо вказати маршрут
        text = (
            "🚋 <b>Крок 1: Номер маршруту</b>\n\n"
            "Будь ласка, введіть номер маршруту (наприклад: 3, 10, 28):"
        )
        keyboard = await get_feedback_cancel_keyboard("feedback_menu")
        await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='HTML')
        return States.COMPLAINT_ROUTE


async def complaint_route_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання номера маршруту"""
    await update.message.delete()
    route = update.message.text.strip()
    context.user_data['complaint_route'] = route

    if context.user_data.get('complaint_edit_mode'):
        context.user_data.pop('complaint_edit_mode', None)
        return await complaint_show_confirm(update, context)

    # Переходимо до запиту бортового номера
    text = (
        "🔢 <b>Крок 2: Бортовий номер</b>\n\n"
        "Будь ласка, введіть бортовий номер транспортного засобу (наприклад: 3012, 4015).\n\n"
        "<i>Якщо Ви не пам'ятаєте бортовий номер, натисніть кнопку «Пропустити» нижче 👇</i>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Пропустити ⏭️", callback_data="complaint_skip_board")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ])

    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text=text,
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return States.COMPLAINT_BOARD


async def complaint_board_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання бортового номера (текстом чи skip-кнопкою)"""
    is_callback = update.callback_query is not None

    if is_callback:
        query = update.callback_query
        await query.answer()
        board = "Не пам'ятаю"
    else:
        await update.message.delete()
        board = update.message.text.strip()

    context.user_data['complaint_board'] = board

    if context.user_data.get('complaint_edit_mode'):
        context.user_data.pop('complaint_edit_mode', None)
        return await complaint_show_confirm(update, context)

    # Переходимо до запиту тексту скарги
    text = (
        "✍️ <b>Крок 3: Опис скарги</b>\n\n"
        "Будь ласка, опишіть суть Вашої проблеми детально:"
    )
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    if is_callback:
        await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='HTML')
    else:
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text=text,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    return States.COMPLAINT_TEXT


async def complaint_text_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання опису проблеми"""
    await update.message.delete()
    text = update.message.text.strip()
    context.user_data['complaint_text'] = text

    if context.user_data.get('complaint_edit_mode'):
        context.user_data.pop('complaint_edit_mode', None)
        return await complaint_show_confirm(update, context)

    # Переходимо до запиту імені
    prompt = (
        "👤 <b>Крок 4: Ваше П.І.Б.</b>\n\n"
        "Будь ласка, введіть Ваше ім'я та прізвище для офіційної реєстрації звернення:"
    )
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")
    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text=prompt,
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return States.COMPLAINT_NAME


async def complaint_name_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання імені"""
    await update.message.delete()
    name = update.message.text.strip()
    context.user_data['complaint_name'] = name

    if context.user_data.get('complaint_edit_mode'):
        context.user_data.pop('complaint_edit_mode', None)
        return await complaint_show_confirm(update, context)

    # Переходимо до запиту телефону
    prompt = (
        "📞 <b>Крок 5: Номер телефону</b>\n\n"
        "Будь ласка, введіть Ваш контактний номер телефону (наприклад: 0951234567):"
    )
    keyboard = await get_feedback_cancel_keyboard("feedback_menu")
    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text=prompt,
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return States.COMPLAINT_PHONE


async def complaint_phone_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та валідація номера телефону"""
    await update.message.delete()
    raw_phone = update.message.text.strip()
    phone = clean_phone(raw_phone)

    if not phone:
        # Помилка валідації
        prompt = (
            "⚠️ <b>Некоректний формат телефону!</b>\n\n"
            "Будь ласка, введіть дійсний номер телефону (наприклад: 0951234567 або +380951234567):"
        )
        keyboard = await get_feedback_cancel_keyboard("feedback_menu")
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text=prompt,
            reply_markup=keyboard,
            parse_mode='HTML'
        )
        return States.COMPLAINT_PHONE

    context.user_data['complaint_phone'] = phone

    if context.user_data.get('complaint_edit_mode'):
        context.user_data.pop('complaint_edit_mode', None)
        return await complaint_show_confirm(update, context)

    # Переходимо до запиту Email
    prompt = (
        "📧 <b>Крок 6: E-mail для відповіді</b>\n\n"
        "Будь ласка, введіть Вашу адресу електронної пошти:\n\n"
        "<i>Якщо Ви не хочете вказувати email, натисніть кнопку «Пропустити» нижче 👇</i>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Пропустити ⏭️", callback_data="complaint_skip_email")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
    ])

    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text=prompt,
        reply_markup=keyboard,
        parse_mode='HTML'
    )
    return States.COMPLAINT_EMAIL


async def complaint_email_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отримання та валідація email (або пропуск)"""
    is_callback = update.callback_query is not None

    if is_callback:
        query = update.callback_query
        await query.answer()
        email = "Не вказано"
    else:
        await update.message.delete()
        raw_email = update.message.text.strip()

        if not is_valid_email(raw_email):
            prompt = (
                "⚠️ <b>Некоректний формат E-mail!</b>\n\n"
                "Будь ласка, введіть дійсну пошту (наприклад: user@example.com) або натисніть «Пропустити»:"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Пропустити ⏭️", callback_data="complaint_skip_email")],
                [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
            ])
            await safe_edit_prev_message(
                context,
                update.effective_chat.id,
                text=prompt,
                reply_markup=keyboard,
                parse_mode='HTML'
            )
            return States.COMPLAINT_EMAIL

        email = raw_email

    context.user_data['complaint_email'] = email

    if context.user_data.get('complaint_edit_mode'):
        context.user_data.pop('complaint_edit_mode', None)

    return await complaint_show_confirm(update, context)


# ================= РЕДАГУВАННЯ =================

async def complaint_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню редагування полів"""
    query = update.callback_query
    await query.answer()

    await safe_edit_prev_message(
        context,
        update.effective_chat.id,
        text="✏️ <b>Оберіть поле, яке бажаєте змінити:</b>",
        reply_markup=_build_complaint_edit_keyboard(context),
        parse_mode='HTML'
    )
    return States.COMPLAINT_EDIT_CHOICE


async def complaint_edit_field_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє натискання на кнопку вибору поля для зміни"""
    query = update.callback_query
    await query.answer()

    field = query.data.split(":", 1)[1]
    context.user_data['complaint_edit_mode'] = True
    context.user_data['complaint_edit_field'] = field

    keyboard = await get_feedback_cancel_keyboard("feedback_menu")

    if field == "route":
        text = "🚋 <b>Введіть новий номер маршруту:</b>"
        await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='HTML')
        return States.COMPLAINT_ROUTE

    elif field == "board":
        text = (
            "🔢 <b>Введіть новий бортовий номер:</b>\n\n"
            "<i>Або натисніть кнопку нижче, якщо не пам'ятаєте:</i>"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Пропустити ⏭️", callback_data="complaint_skip_board")],
            [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode='HTML')
        return States.COMPLAINT_BOARD

    elif field == "text":
        text = "✍️ <b>Введіть новий опис проблеми:</b>"
        await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='HTML')
        return States.COMPLAINT_TEXT

    elif field == "name":
        text = "👤 <b>Введіть нове П.І.Б.:</b>"
        await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='HTML')
        return States.COMPLAINT_NAME

    elif field == "phone":
        text = "📞 <b>Введіть новий номер телефону:</b>"
        await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode='HTML')
        return States.COMPLAINT_PHONE

    elif field == "email":
        text = "📧 <b>Введіть нову адресу E-mail (або пропустіть):</b>"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Пропустити ⏭️", callback_data="complaint_skip_email")],
            [InlineKeyboardButton("🚫 Скасувати", callback_data="feedback_menu")]
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode='HTML')
        return States.COMPLAINT_EMAIL


async def complaint_edit_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повернення з меню редагування до підтвердження"""
    query = update.callback_query
    await query.answer()
    context.user_data.pop('complaint_edit_mode', None)
    context.user_data.pop('complaint_edit_field', None)
    return await complaint_show_confirm(update, context)


# ================= ФІНАЛЬНЕ ЗБЕРЕЖЕННЯ =================

async def complaint_save_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фінальне збереження скарги у БД та підтвердження користувачу"""
    query = update.callback_query
    await query.answer()

    ctype = context.user_data.get('complaint_type', 'general')
    problem = context.user_data.get('complaint_text')
    route = context.user_data.get('complaint_route', 'N/A')
    board = context.user_data.get('complaint_board', 'N/A')
    name = context.user_data.get('complaint_name')
    phone = context.user_data.get('complaint_phone')
    email = context.user_data.get('complaint_email', 'Не вказано')

    # Якщо тип загальний, то фіксуємо це в полях маршруту та борта
    if ctype == 'general':
        route = 'Загальна скарга'
        board = 'Загальна скарга'

    complaint_data = {
        "problem": problem,
        "route": route,
        "board_number": board,
        "user_name": name,
        "user_phone": phone,
        "user_email": email
    }

    try:
        service = TicketsService()
        result = await service.create_complaint_ticket(update.effective_user.id, complaint_data)

        # Видаляємо всі тимчасові дані з сесії
        context.user_data.pop('complaint_type', None)
        context.user_data.pop('complaint_route', None)
        context.user_data.pop('complaint_board', None)
        context.user_data.pop('complaint_text', None)
        context.user_data.pop('complaint_name', None)
        context.user_data.pop('complaint_phone', None)
        context.user_data.pop('complaint_email', None)
        context.user_data.pop('complaint_edit_mode', None)
        context.user_data.pop('complaint_edit_field', None)

        success_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]])
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text=result['message'],
            reply_markup=success_markup,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Error saving complaint: {e}")
        await safe_edit_prev_message(
            context,
            update.effective_chat.id,
            text="❌ <b>Сталася помилка при збереженні скарги.</b> Будь ласка, спробуйте пізніше або зверніться до адміністратора.",
            parse_mode='HTML'
        )

    return ConversationHandler.END
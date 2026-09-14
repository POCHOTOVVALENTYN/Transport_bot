import asyncio
import logging
import re
import html
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler,
                          filters)
from config.settings import MUSEUM_ADMIN_ID, MUSEUM_ADMIN_IDS, GOOGLE_SHEETS_ID, GENERAL_ADMIN_IDS, BROADCAST_BATCH_SIZE, BROADCAST_PAUSE_SEC, LEGACY_USERS_OFFSET
from integrations.google_sheets.client import GoogleSheetsClient
from utils.logger import logger
from bot.states import States
from handlers.command_handlers import get_admin_main_menu_keyboard

from services.user_service import UserService
from services.tickets_service import TicketsService
from services.museum_service import MuseumService
from services.news_service import NewsService, format_kyiv_time
from services.lost_items_service import LostItemsService, format_kyiv_date as format_lost_date


user_service = UserService()
tickets_service = TicketsService()
museum_service = MuseumService()
news_service = NewsService()
lost_items_service = LostItemsService()



# Стани для адміна
#(ADMIN_STATE_ADD_DATE, ADMIN_STATE_DEL_DATE_CONFIRM) = range(16, 18)  # Використовуємо нові стани


from database.db import AsyncSessionLocal, Feedback
from sqlalchemy import select

async def send_moderation_card_to_admins(bot, ticket_id: str):
    """Надсилає картку нового звернення адміністраторам для перевірки"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Feedback).where(Feedback.ticket_id == ticket_id))
        feedback = result.scalar_one_or_none()
        if not feedback:
            logger.error(f"❌ Звернення {ticket_id} не знайдено для відправки модерації")
            return

        category_ua = {
            "complaint": "СКАРГА ⚠️",
            "thanks": "ПОДЯКА ❤️",
            "suggestion": "ПРОПОЗИЦІЯ 💡"
        }.get(feedback.category, feedback.category.upper())

        text = (
            f"📥 <b>Нове звернення громадян: {category_ua}</b>\n"
            f"🆔 <b>ID:</b> <code>{feedback.ticket_id}</code>\n"
            f"📅 <b>Дата:</b> {feedback.created_at.strftime('%d.%m.%Y %H:%M') if feedback.created_at else ''}\n"
            f"----------------------------------------\n"
            f"👤 <b>Заявник:</b> {feedback.user_name or 'Не вказано'}\n"
            f"📞 <b>Телефон:</b> {feedback.user_phone or 'Не вказано'}\n"
            f"📧 <b>Email:</b> {feedback.user_email or 'Не вказано'}\n"
        )

        if feedback.category in ("complaint", "thanks") and (feedback.route or feedback.board_number or feedback.transport_type):
            t_prefix = "Трамвай" if feedback.transport_type == "tram" else "Тролейбус" if feedback.transport_type == "trolleybus" else ""
            route_str = f"{t_prefix} № {feedback.route}" if t_prefix and feedback.route else (feedback.route or "")
            text += (
                f"🚊 <b>Транспорт:</b> {route_str or 'Не вказано'}\n"
                f"🔢 <b>Бортовий номер:</b> {feedback.board_number or 'Не вказано'}\n"
            )

        text += (
            f"----------------------------------------\n"
            f"📝 <b>Текст звернення:</b>\n{feedback.text}\n"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Затвердити та надіслати", callback_data=f"feed_mod:approve:{feedback.ticket_id}")],
            [InlineKeyboardButton("❌ Відхилити", callback_data=f"feed_mod:reject:{feedback.ticket_id}")]
        ])

        for admin_id in GENERAL_ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"❌ Не вдалося надіслати картку модерації адміну {admin_id}: {e}")


async def moderate_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник затвердження звернення модератором"""
    query = update.callback_query
    await query.answer()

    ticket_id = query.data.split(":")[2]

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Feedback).where(Feedback.ticket_id == ticket_id))
        feedback = result.scalar_one_or_none()
        if not feedback:
            await query.edit_message_text("❌ Звернення не знайдено в базі даних.")
            return

        if feedback.email_status == "sent":
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("Зрозуміло 👍", callback_data="delete_message")]])
            await query.edit_message_text(f"⚠️ Звернення {ticket_id} вже було надіслано на пошту.", reply_markup=markup)
            return
        elif feedback.email_status == "rejected":
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("Зрозуміло 👍", callback_data="delete_message")]])
            await query.edit_message_text(f"⚠️ Звернення {ticket_id} вже було відхилено.", reply_markup=markup)
            return

        # Зберігаємо статус "sent"
        feedback.email_status = "sent"
        await session.commit()

        # Повідомляємо адміна про старт генерації
        await query.edit_message_text(f"⏳ Обробка звернення {ticket_id}... Генеруємо PDF...")

        from services.pdf_service import generate_feedback_pdf
        from services.email_service import send_feedback_email
        import os

        pdf_path = None
        try:
            # Генеруємо PDF
            pdf_path = generate_feedback_pdf(feedback)

            # Відправляємо Email у фоновому пулі потоків
            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(
                None,
                send_feedback_email,
                pdf_path,
                feedback.ticket_id,
                feedback.category
            )

            if success:
                admin_name = update.effective_user.first_name or update.effective_user.username or "Адмін"
                time_str = datetime.now().strftime("%d.%m.%Y %H:%M")

                # Формуємо новий текст з кнопкою повернення
                category_ua = {
                    "complaint": "СКАРГА ⚠️",
                    "thanks": "ПОДЯКА ❤️",
                    "suggestion": "ПРОПОЗИЦІЯ 💡"
                }.get(feedback.category, feedback.category.upper())

                new_text = (
                    f"📥 <b>Звернення громадян: {category_ua}</b>\n"
                    f"🆔 <b>ID:</b> <code>{feedback.ticket_id}</code>\n"
                    f"👤 <b>Заявник:</b> {feedback.user_name or 'Не вказано'}\n"
                    f"📞 <b>Телефон:</b> {feedback.user_phone or 'Не вказано'}\n"
                    f"📧 <b>Email:</b> {feedback.user_email or 'Не вказано'}\n"
                    f"📝 <b>Текст звернення:</b>\n{feedback.text}\n"
                    f"----------------------------------------\n"
                    f"<b>✅ Затверджено та надіслано на Email секретаря</b>\n"
                    f"👤 Модератор: {admin_name}\n"
                    f"🕒 Час: {time_str}"
                )

                markup = InlineKeyboardMarkup([[InlineKeyboardButton("Зрозуміло 👍", callback_data="delete_message")]])
                await query.edit_message_text(text=new_text, reply_markup=markup, parse_mode="HTML")

                # Сповіщаємо користувача
                user_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Зрозуміло 👍", callback_data="delete_message")]])
                try:
                    await context.bot.send_message(
                        chat_id=feedback.user_id,
                        text=f"✉️ <b>Ваше звернення {feedback.ticket_id} було розглянуто модератором та успішно надіслано до офіційної реєстрації.</b>",
                        reply_markup=user_markup,
                        parse_mode="HTML"
                    )
                except Exception as user_err:
                    logger.error(f"Не вдалося сповістити користувача {feedback.user_id}: {user_err}")
            else:
                feedback.email_status = "pending"
                await session.commit()
                await query.edit_message_text(
                    f"❌ Помилка відправки листа для {ticket_id}. Перевірте налаштування SMTP у .env файлі.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Спробувати знову", callback_data=f"feed_mod:approve:{ticket_id}")],
                        [InlineKeyboardButton("❌ Відхилити", callback_data=f"feed_mod:reject:{ticket_id}")],
                        [InlineKeyboardButton("Зрозуміло 👍", callback_data="delete_message")]
                    ])
                )
        except Exception as err:
            logger.error(f"❌ Помилка при затвердженні звернення {ticket_id}: {err}")
            feedback.email_status = "pending"
            await session.commit()
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("Зрозуміло 👍", callback_data="delete_message")]])
            await query.edit_message_text(f"❌ Помилка обробки звернення: {err}", reply_markup=markup)
        finally:
            if pdf_path and os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except Exception as del_err:
                    logger.error(f"Не вдалося видалити тимчасовий PDF {pdf_path}: {del_err}")


async def moderate_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробник відхилення звернення модератором"""
    query = update.callback_query
    await query.answer()

    ticket_id = query.data.split(":")[2]

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Feedback).where(Feedback.ticket_id == ticket_id))
        feedback = result.scalar_one_or_none()
        if not feedback:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("Зрозуміло 👍", callback_data="delete_message")]])
            await query.edit_message_text("❌ Звернення не знайдено.", reply_markup=markup)
            return

        if feedback.email_status in ("sent", "rejected"):
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("Зрозуміло 👍", callback_data="delete_message")]])
            await query.edit_message_text(f"⚠️ Звернення {ticket_id} вже оброблено (статус: {feedback.email_status}).", reply_markup=markup)
            return

        feedback.email_status = "rejected"
        await session.commit()

        admin_name = update.effective_user.first_name or update.effective_user.username or "Адмін"
        time_str = datetime.now().strftime("%d.%m.%Y %H:%M")

        category_ua = {
            "complaint": "СКАРГА ⚠️",
            "thanks": "ПОДЯКА ❤️",
            "suggestion": "ПРОПОЗИЦІЯ 💡"
        }.get(feedback.category, feedback.category.upper())

        new_text = (
            f"📥 <b>Звернення громадян: {category_ua}</b>\n"
            f"🆔 <b>ID:</b> <code>{feedback.ticket_id}</code>\n"
            f"👤 <b>Заявник:</b> {feedback.user_name or 'Не вказано'}\n"
            f"📞 <b>Телефон:</b> {feedback.user_phone or 'Не вказано'}\n"
            f"📧 <b>Email:</b> {feedback.user_email or 'Не вказано'}\n"
            f"📝 <b>Текст звернення:</b>\n{feedback.text}\n"
            f"----------------------------------------\n"
            f"<b>❌ Відхилено модератором (некоректний вміст / спам)</b>\n"
            f"👤 Модератор: {admin_name}\n"
            f"🕒 Час: {time_str}"
        )

        markup = InlineKeyboardMarkup([[InlineKeyboardButton("Зрозуміло 👍", callback_data="delete_message")]])
        await query.edit_message_text(text=new_text, reply_markup=markup, parse_mode="HTML")

        # Сповіщаємо користувача
        user_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Зрозуміло 👍", callback_data="delete_message")]])
        try:
            await context.bot.send_message(
                chat_id=feedback.user_id,
                text=f"⚠️ <b>Ваше звернення {feedback.ticket_id} було відхилено модератором через некоректний вміст (спам, нецензурну лексику чи відсутність конкретики).</b>",
                reply_markup=user_markup,
                parse_mode="HTML"
            )
        except Exception as user_err:
            logger.error(f"Не вдалося сповістити користувача {feedback.user_id}: {user_err}")


# --- НОВА ФУНКЦІЯ: Меню Загального Адміна (Валентин і Тетяна) ---
async def show_general_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Головне меню для новин та керування ботом"""
    query = update.callback_query
    if query: await query.answer()

    user_id = update.effective_user.id
    if user_id not in GENERAL_ADMIN_IDS:
        return

    # Отримуємо статистику
    stats = await user_service.get_stats()
    current_users = stats['total_users']
    grand_total = current_users + LEGACY_USERS_OFFSET

    text = (
        f"⚙️ <b>Панель Керування</b>\n\n"
        f"👥 Всього користувачів: <b>{grand_total}</b> (поточна серверна БД: {current_users} + {LEGACY_USERS_OFFSET} з попереднього сервера)\n"
        f"👋 Вітаю, {update.effective_user.first_name}!"
    )

    keyboard = [
        [InlineKeyboardButton("📢 Зробити розсилку (Новини)", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton("🗄️ Архів новин", callback_data="admin_news_archive:0")],
        [InlineKeyboardButton("🔍 Загублені речі", callback_data="admin_lost_menu")],
        [InlineKeyboardButton("📧 Поштовий архів", callback_data="admin_mail_archive")],
        [InlineKeyboardButton("🔄 Синхронізувати БД -> Sheets", callback_data="admin_sync_db")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🏠 В режим користувача", callback_data="main_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def admin_news_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Відображає перелік усіх новин в архіві для Загальних Адміністраторів"""
    query = update.callback_query
    if query:
        await query.answer()

    user_id = update.effective_user.id
    if user_id not in GENERAL_ADMIN_IDS:
        return

    offset = 0
    if query and query.data and ":" in query.data:
        try:
            offset = int(query.data.split(":")[1])
        except (ValueError, IndexError):
            offset = 0

    limit = 7
    result = await news_service.get_news_archive(limit=limit, offset=offset)
    items = result["items"]
    total_count = result["total_count"]
    has_prev = result["has_prev"]
    has_next = result["has_next"]

    if not items:
        empty_text = (
            "🗄️ <b>Архів оперативних новин та розсилок</b>\n\n"
            "В базі даних наразі немає збережених повідомлень розсилки."
        )
        empty_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 В адмін-панель", callback_data="general_admin_menu")]
        ])
        if query and query.message:
            await query.edit_message_text(empty_text, reply_markup=empty_markup, parse_mode=ParseMode.HTML)
        return

    header_text = (
        "🗄️ <b>Архів оперативних новин та розсилок</b>\n\n"
        f"Всього повідомлень: <b>{total_count}</b>\n"
        "🟢 = Актуальна (видима пасажирам) | 🔴 = В архіві (прихована)\n\n"
        "Оберіть новину для перегляду та керування актуальністю:"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    for item in items:
        created_time = format_kyiv_time(item.created_at)
        status_icon = "🟢" if item.is_active else "🔴"
        snippet = (item.text or "").strip().replace("\n", " ")
        if len(snippet) > 24:
            snippet = snippet[:22] + ".."
        elif not snippet:
            snippet = "📸 Медіаматеріал"

        btn_label = f"{status_icon} {created_time}: {snippet}"
        keyboard.append([
            InlineKeyboardButton(btn_label, callback_data=f"admin_news_view:{item.id}:{offset}")
        ])

    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        prev_offset = max(0, offset - limit)
        nav_row.append(InlineKeyboardButton("⬅️ Попередня", callback_data=f"admin_news_archive:{prev_offset}"))
    if has_next:
        next_offset = offset + limit
        nav_row.append(InlineKeyboardButton("Наступна ➡️", callback_data=f"admin_news_archive:{next_offset}"))

    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("🔙 В адмін-панель", callback_data="general_admin_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query and query.message:
        await query.edit_message_text(header_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def admin_news_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Відображає картку новини з можливістю перемикання актуальності"""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    user_id = update.effective_user.id
    if user_id not in GENERAL_ADMIN_IDS:
        return

    parts = query.data.split(":")
    news_id = int(parts[1]) if len(parts) > 1 else 0
    offset = int(parts[2]) if len(parts) > 2 else 0

    news = await news_service.get_news_by_id(news_id)
    if not news:
        await query.edit_message_text(
            "⚠️ Новину не знайдено.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ До списку архіву", callback_data=f"admin_news_archive:{offset}")]
            ])
        )
        return

    created_time = format_kyiv_time(news.created_at)
    status_label = (
        "🟢 <b>Актуальна</b> (відображається в меню пасажирів)"
        if news.is_active
        else "🔴 <b>Неактуальна / В архіві</b> (прихована від пасажирів)"
    )
    content_text = news.text or "<i>(Текст відсутній / тільки медіа)</i>"
    admin_name_safe = html.escape(news.admin_name or "Адміністратор")

    detail_text = (
        f"🗄️ <b>Картка розсилки #{news.id}</b>\n\n"
        f"📅 <b>Дата та час:</b> {created_time}\n"
        f"👤 <b>Автор:</b> {admin_name_safe} (ID: <code>{news.admin_id}</code>)\n"
        f"📊 <b>Результат розсилки:</b> Успішно: <b>{news.sent_count}</b> | Блокувань: <b>{news.blocked_count}</b>\n"
        f"📌 <b>Статус:</b> {status_label}\n"
        f"----------------------------------------\n"
        f"💬 <b>Текст оголошення:</b>\n{content_text}"
    )

    toggle_btn_text = "🔴 Зробити неактуальною (В архів)" if news.is_active else "🟢 Зробити актуальною"
    keyboard = [
        [InlineKeyboardButton(toggle_btn_text, callback_data=f"admin_news_toggle:{news.id}:{offset}")],
        [InlineKeyboardButton("⬅️ До архіву", callback_data=f"admin_news_archive:{offset}")],
        [InlineKeyboardButton("🔙 В адмін-панель", callback_data="general_admin_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(detail_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def admin_news_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перемикає статус актуальності новини адміністратором"""
    query = update.callback_query
    if not query:
        return

    user_id = update.effective_user.id
    if user_id not in GENERAL_ADMIN_IDS:
        return

    parts = query.data.split(":")
    news_id = int(parts[1]) if len(parts) > 1 else 0
    offset = int(parts[2]) if len(parts) > 2 else 0

    new_status = await news_service.toggle_news_active(news_id)
    if new_status is None:
        await query.answer("⚠️ Новину не знайдено!", show_alert=True)
        return

    alert_text = (
        "✅ Новина тепер АКТУАЛЬНА і доступна пасажирам"
        if new_status
        else "📦 Новину перенесено в АРХІВ (приховано від пасажирів)"
    )
    await query.answer(alert_text, show_alert=False)

    # Оновлюємо відображення картки з новим статусом та новою кнопкою
    await admin_news_detail(update, context)


async def admin_lost_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Головне меню керування загубленими речами для адміністраторів"""
    query = update.callback_query
    if query:
        await query.answer()
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return

    text = (
        "🔍 <b>Керування розділом «Загублені речі»</b>\n\n"
        "Оберіть дію:\n"
        "• Додати нову знахідку до бази\n"
        "• Переглянути наявні речі або документи на зберіганні\n"
        "• Відзначити повернення знахідки власнику або переглянути архів"
    )
    keyboard = [
        [InlineKeyboardButton("➕ Додати нову знахідку", callback_data="admin_lost_add_start")],
        [InlineKeyboardButton("🪪 Документи на зберіганні", callback_data="admin_lost_list:document:0")],
        [InlineKeyboardButton("🎒 Особисті речі на зберіганні", callback_data="admin_lost_list:thing:0")],
        [InlineKeyboardButton("🗄️ Архів виданих знахідок", callback_data="admin_lost_archive:0")],
        [InlineKeyboardButton("🔙 В адмін-панель", callback_data="general_admin_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if query and query.message:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def admin_lost_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує список знахідок за категорією з пагінацією"""
    query = update.callback_query
    if query:
        await query.answer()
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return

    parts = query.data.split(":")
    category = parts[1] if len(parts) > 1 else "document"
    offset = int(parts[2]) if len(parts) > 2 else 0
    limit = 7

    cat_label = "🪪 Документи" if category == "document" else "🎒 Особисті речі"
    result = await lost_items_service.get_admin_items(status="active", category=category, limit=limit, offset=offset)
    items = result["items"]
    total_count = result["total_count"]
    has_prev = result["has_prev"]
    has_next = result["has_next"]

    if not items:
        empty_text = (
            f"🔍 <b>{cat_label} (на зберіганні)</b>\n\n"
            "На зберіганні наразі немає зареєстрованих знахідок у цій категорії."
        )
        empty_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Додати знахідку", callback_data="admin_lost_add_start")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_lost_menu")]
        ])
        if query and query.message:
            await query.edit_message_text(empty_text, reply_markup=empty_markup, parse_mode=ParseMode.HTML)
        return

    header_text = (
        f"🔍 <b>{cat_label} на зберіганні</b>\n\n"
        f"Всього знахідок: <b>{total_count}</b>\n"
        "Оберіть запис для перегляду деталей, повернення власнику або видалення:"
    )
    keyboard = []
    for item in items:
        created_date = format_lost_date(item.created_at)
        title_snippet = (item.title or "").strip()
        if len(title_snippet) > 28:
            title_snippet = title_snippet[:26] + ".."
        btn_label = f"🟢 {created_date}: {title_snippet}"
        keyboard.append([
            InlineKeyboardButton(btn_label, callback_data=f"admin_lost_view:{item.id}:{category}:{offset}")
        ])

    nav_row = []
    if has_prev:
        prev_offset = max(0, offset - limit)
        nav_row.append(InlineKeyboardButton("⬅️ Попередня", callback_data=f"admin_lost_list:{category}:{prev_offset}"))
    if has_next:
        next_offset = offset + limit
        nav_row.append(InlineKeyboardButton("Наступна ➡️", callback_data=f"admin_lost_list:{category}:{next_offset}"))

    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("➕ Додати нову", callback_data="admin_lost_add_start")])
    keyboard.append([InlineKeyboardButton("⬅️ До меню знахідок", callback_data="admin_lost_menu")])

    await query.edit_message_text(header_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def admin_lost_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Картка знахідки в адмін-панелі"""
    query = update.callback_query
    if not query:
        return
    await query.answer()
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return

    parts = query.data.split(":")
    item_id = int(parts[1]) if len(parts) > 1 else 0
    category = parts[2] if len(parts) > 2 else "document"
    offset = int(parts[3]) if len(parts) > 3 else 0

    item = await lost_items_service.get_item_by_id(item_id)
    if not item:
        await query.edit_message_text(
            "⚠️ Запис не знайдено або вже видалено.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ До списку", callback_data=f"admin_lost_list:{category}:{offset}")]
            ])
        )
        return

    created_date = format_lost_date(item.created_at)
    cat_label = "🪪 Документ" if item.category == "document" else "🎒 Особиста річ"
    status_label = "🟢 На зберіганні в інфоцентрі" if item.status == "active" else "✅ Повернуто власнику"
    admin_name_safe = html.escape(item.admin_name or "Адміністратор")
    title_safe = html.escape(item.title)
    details_safe = html.escape(item.details or "Деталі не вказані")

    text = (
        f"🔍 <b>Картка знахідки #{item.id}</b>\n\n"
        f"📁 <b>Категорія:</b> {cat_label}\n"
        f"🏷️ <b>Назва / ПІБ:</b> {title_safe}\n"
        f"ℹ️ <b>Деталі:</b> {details_safe}\n"
        f"🗓️ <b>Дата внесення:</b> {created_date}\n"
        f"👤 <b>Додав(ла):</b> {admin_name_safe}\n"
        f"📌 <b>Статус:</b> {status_label}\n"
    )

    keyboard = []
    if item.status == "active":
        keyboard.append([
            InlineKeyboardButton("✅ Позначити: Повернуто власнику", callback_data=f"admin_lost_return:{item.id}:{category}:{offset}")
        ])
    keyboard.append([
        InlineKeyboardButton("🗑️ Видалити запис", callback_data=f"admin_lost_delete:{item.id}:{category}:{offset}")
    ])
    back_target = f"admin_lost_list:{category}:{offset}" if item.status == "active" else f"admin_lost_archive:{offset}"
    keyboard.append([InlineKeyboardButton("⬅️ Назад до списку", callback_data=back_target)])
    keyboard.append([InlineKeyboardButton("🔙 До меню знахідок", callback_data="admin_lost_menu")])

    await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def admin_lost_return(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Позначає знахідку як повернену власнику"""
    query = update.callback_query
    if not query:
        return
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return

    parts = query.data.split(":")
    item_id = int(parts[1]) if len(parts) > 1 else 0
    category = parts[2] if len(parts) > 2 else "document"
    offset = int(parts[3]) if len(parts) > 3 else 0

    res = await lost_items_service.mark_as_returned(item_id)
    if res:
        await query.answer("✅ Знахідку позначено як повернену власнику!", show_alert=False)
    else:
        await query.answer("⚠️ Запис не знайдено.", show_alert=True)

    query.data = f"admin_lost_list:{category}:{offset}"
    await admin_lost_list(update, context)


async def admin_lost_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Видаляє запис про знахідку"""
    query = update.callback_query
    if not query:
        return
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return

    parts = query.data.split(":")
    item_id = int(parts[1]) if len(parts) > 1 else 0
    category = parts[2] if len(parts) > 2 else "document"
    offset = int(parts[3]) if len(parts) > 3 else 0

    await lost_items_service.delete_lost_item(item_id)
    await query.answer("🗑️ Запис видалено!", show_alert=False)

    query.data = f"admin_lost_list:{category}:{offset}"
    await admin_lost_list(update, context)


async def admin_lost_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує архів виданих знахідок"""
    query = update.callback_query
    if query:
        await query.answer()
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return

    offset = 0
    if query and query.data and ":" in query.data:
        try:
            offset = int(query.data.split(":")[1])
        except (ValueError, IndexError):
            offset = 0
    limit = 7

    result = await lost_items_service.get_admin_items(status="returned", limit=limit, offset=offset)
    items = result["items"]
    total_count = result["total_count"]
    has_prev = result["has_prev"]
    has_next = result["has_next"]

    if not items:
        empty_text = (
            "🗄️ <b>Архів повернених знахідок</b>\n\n"
            "В архіві наразі немає виданих знахідок."
        )
        empty_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ До меню знахідок", callback_data="admin_lost_menu")]
        ])
        if query and query.message:
            await query.edit_message_text(empty_text, reply_markup=empty_markup, parse_mode=ParseMode.HTML)
        return

    header_text = (
        "🗄️ <b>Архів повернутих знахідок</b>\n\n"
        f"Всього видано громадянам: <b>{total_count}</b>\n"
        "Оберіть запис для перегляду деталей:"
    )
    keyboard = []
    for item in items:
        ret_date = format_lost_date(item.returned_at or item.created_at)
        title_snippet = (item.title or "").strip()
        if len(title_snippet) > 26:
            title_snippet = title_snippet[:24] + ".."
        btn_label = f"✅ {ret_date}: {title_snippet}"
        keyboard.append([
            InlineKeyboardButton(btn_label, callback_data=f"admin_lost_view:{item.id}:{item.category}:{offset}")
        ])

    nav_row = []
    if has_prev:
        prev_offset = max(0, offset - limit)
        nav_row.append(InlineKeyboardButton("⬅️ Попередня", callback_data=f"admin_lost_archive:{prev_offset}"))
    if has_next:
        next_offset = offset + limit
        nav_row.append(InlineKeyboardButton("Наступна ➡️", callback_data=f"admin_lost_archive:{next_offset}"))

    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("⬅️ До меню знахідок", callback_data="admin_lost_menu")])
    await query.edit_message_text(header_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


# --- CONVERSATION HANDLER: ДОДАВАННЯ ЗНАХІДКИ АДМІНОМ ---

async def admin_lost_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок діалогу додавання знахідки"""
    query = update.callback_query
    if query:
        await query.answer()
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return ConversationHandler.END

    text = (
        "➕ <b>Додавання нової знахідки</b>\n\n"
        "Крок 1/3: Оберіть категорію знахідки:"
    )
    keyboard = [
        [InlineKeyboardButton("🪪 Документ", callback_data="admin_lost_set_cat:document")],
        [InlineKeyboardButton("🎒 Особиста річ", callback_data="admin_lost_set_cat:thing")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="admin_lost_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query and query.message:
        sent_msg = await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        context.user_data['lost_add_prompt_id'] = sent_msg.message_id
    else:
        sent_msg = await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        context.user_data['lost_add_prompt_id'] = sent_msg.message_id

    return States.ADMIN_LOST_CATEGORY


async def admin_lost_cat_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка вибору категорії"""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return ConversationHandler.END

    category = query.data.split(":")[1] if ":" in query.data else "thing"
    context.user_data['lost_add_cat'] = category

    cat_label = "🪪 Документ" if category == "document" else "🎒 Особиста річ"
    prompt_example = "«Пенсійне посвідчення — Петренко Іван Васильович»" if category == "document" else "«Чорний рюкзак Adidas»"

    text = (
        f"➕ <b>Додавання: {cat_label}</b>\n\n"
        f"Крок 2/3: Надішліть текстом назву знахідки або ПІБ власника на документі.\n\n"
        f"<i>Приклад: {prompt_example}</i>"
    )
    cancel_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Скасувати", callback_data="admin_lost_cancel")]
    ])

    sent_msg = await query.edit_message_text(text=text, reply_markup=cancel_markup, parse_mode=ParseMode.HTML)
    context.user_data['lost_add_prompt_id'] = sent_msg.message_id
    return States.ADMIN_LOST_TITLE


async def admin_lost_title_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка введення назви знахідки"""
    user_id = update.effective_user.id
    if user_id not in GENERAL_ADMIN_IDS:
        return ConversationHandler.END

    title = update.message.text.strip()
    context.user_data['lost_add_title'] = title

    try:
        await update.message.delete()
    except Exception:
        pass

    text = (
        f"➕ <b>Додавання знахідки</b>\n\n"
        f"Назва: <b>{html.escape(title)}</b>\n\n"
        "Крок 3/3: Вкажіть деталі (наприклад: <i>«Трамвай №7, знайдено на зупинці Тираспольська пл.»</i>) "
        "або натисніть <b>Пропустити</b>:"
    )
    keyboard = [
        [InlineKeyboardButton("⏩ Пропустити деталі", callback_data="admin_lost_skip_details")],
        [InlineKeyboardButton("🚫 Скасувати", callback_data="admin_lost_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    prompt_id = context.user_data.get('lost_add_prompt_id')
    if prompt_id:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=prompt_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            return States.ADMIN_LOST_DETAILS
        except Exception:
            pass

    sent_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    context.user_data['lost_add_prompt_id'] = sent_msg.message_id
    return States.ADMIN_LOST_DETAILS


async def _admin_lost_save_finish(update: Update, context: ContextTypes.DEFAULT_TYPE, details: str = ""):
    """Збереження знахідки у базі даних"""
    admin_user = update.effective_user
    category = context.user_data.get('lost_add_cat', 'thing')
    title = context.user_data.get('lost_add_title', '')

    if not title:
        return ConversationHandler.END

    item = await lost_items_service.create_lost_item({
        "admin_id": admin_user.id,
        "admin_name": admin_user.full_name or admin_user.first_name or "Адміністратор",
        "category": category,
        "title": title,
        "details": details or "Інформаційний центр (вул. Водопровідна, 1)"
    })

    cat_label = "🪪 Документ" if category == "document" else "🎒 Особиста річ"
    success_text = (
        f"✅ <b>Знахідку успішно додано!</b>\n\n"
        f"📁 <b>Категорія:</b> {cat_label}\n"
        f"🏷️ <b>Назва:</b> {html.escape(title)}\n"
        f"ℹ️ <b>Деталі:</b> {html.escape(item.details or '')}\n\n"
        "Знахідка тепер відображається пасажирам у розділі «Загублені речі»."
    )
    keyboard = [
        [InlineKeyboardButton("➕ Додати ще одну", callback_data="admin_lost_add_start")],
        [InlineKeyboardButton("🔍 До меню знахідок", callback_data="admin_lost_menu")],
        [InlineKeyboardButton("🔙 В адмін-панель", callback_data="general_admin_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    prompt_id = context.user_data.pop('lost_add_prompt_id', None)
    context.user_data.pop('lost_add_cat', None)
    context.user_data.pop('lost_add_title', None)

    if update.callback_query:
        await update.callback_query.edit_message_text(text=success_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        if prompt_id:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_id)
            except Exception:
                pass
        await context.bot.send_message(chat_id=update.effective_chat.id, text=success_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

    return ConversationHandler.END


async def admin_lost_details_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка введених деталей знахідки"""
    user_id = update.effective_user.id
    if user_id not in GENERAL_ADMIN_IDS:
        return ConversationHandler.END

    details = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass

    return await _admin_lost_save_finish(update, context, details=details)


async def admin_lost_skip_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск кроку деталей знахідки"""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return ConversationHandler.END

    return await _admin_lost_save_finish(update, context, details="Інформаційний центр (вул. Водопровідна, 1)")


async def admin_lost_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування діалогу додавання знахідки"""
    query = update.callback_query
    if query:
        await query.answer("Дію скасовано")
    context.user_data.pop('lost_add_prompt_id', None)
    context.user_data.pop('lost_add_cat', None)
    context.user_data.pop('lost_add_title', None)

    if query:
        await admin_lost_menu(update, context)
    return ConversationHandler.END


async def admin_mail_archive_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню вибору категорії поштового архіву"""
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in GENERAL_ADMIN_IDS:
        return

    text = "📧 <b>Поштовий архів звернень</b>\n\nОберіть категорію для перегляду та відправки:"
    keyboard = [
        [InlineKeyboardButton("⚠️ Скарги (Complaints)", callback_data="admin_mail_cat:complaint:0")],
        [InlineKeyboardButton("❤️ Подяки (Thanks)", callback_data="admin_mail_cat:thanks:0")],
        [InlineKeyboardButton("💡 Пропозиції (Suggestions)", callback_data="admin_mail_cat:suggestion:0")],
        [InlineKeyboardButton("⬅️ Назад до панелі", callback_data="general_admin_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def admin_mail_show_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує список звернень у обраній категорії з пагінацією"""
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in GENERAL_ADMIN_IDS:
        return

    # Callback data format: admin_mail_cat:<category>:<offset>
    parts = query.data.split(":")
    category = parts[1]
    offset = int(parts[2]) if len(parts) > 2 else 0
    limit = 8

    # Нормалізуємо категорію до англійського ключа
    if category in ("thanks", "Подяки"):
        category = "thanks"
    elif category in ("complaint", "Скарги"):
        category = "complaint"
    elif category in ("suggestion", "Пропозиції"):
        category = "suggestion"

    category_ua = {
        "complaint": "Скарги ⚠️",
        "thanks": "Подяки ❤️",
        "suggestion": "Пропозиції 💡"
    }.get(category, category.upper())

    categories_to_query = [category]
    if category == "thanks":
        categories_to_query = ["thanks", "Подяки"]
    elif category == "complaint":
        categories_to_query = ["complaint", "Скарги"]
    elif category == "suggestion":
        categories_to_query = ["suggestion", "Пропозиції"]

    async with AsyncSessionLocal() as session:
        # Отримуємо загальну кількість
        from sqlalchemy import func
        total = await session.scalar(
            select(func.count(Feedback.id)).where(Feedback.category.in_(categories_to_query))
        ) or 0

        # Отримуємо самі записи
        result = await session.execute(
            select(Feedback)
            .where(Feedback.category.in_(categories_to_query))
            .order_by(Feedback.id.desc())
            .offset(offset)
            .limit(limit)
        )
        feedbacks = result.scalars().all()

        if not feedbacks:
            keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_mail_archive")]]
            await query.edit_message_text(
                f"📧 <b>Архів: {category_ua}</b>\n\nНемає звернень у цій категорії.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
            return

        text = f"📧 <b>Архів: {category_ua}</b> (Показано {offset + 1}-{min(offset + limit, total)} з {total}):\n\nОберіть запис для перегляду:"
        keyboard = []

        status_icons = {
            "sent": "✅",
            "rejected": "❌",
            "pending": "⏳"
        }

        for f in feedbacks:
            icon = status_icons.get(f.email_status, "⏳")
            created_str = f.created_at.strftime("%d.%m") if f.created_at else "N/A"
            btn_text = f"{icon} {created_str} | {f.ticket_id} ({f.user_name or 'Не вказано'})"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"admin_mail_detail:{f.ticket_id}:{offset}")])

        # Кнопки навігації
        nav_row = []
        if offset > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"admin_mail_cat:{category}:{max(0, offset - limit)}"))
        if offset + limit < total:
            nav_row.append(InlineKeyboardButton("Далі ➡️", callback_data=f"admin_mail_cat:{category}:{offset + limit}"))
        if nav_row:
            keyboard.append(nav_row)

        keyboard.append([InlineKeyboardButton("⬅️ До вибору категорій", callback_data="admin_mail_archive")])

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def admin_mail_show_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальний перегляд звернення"""
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in GENERAL_ADMIN_IDS:
        return

    # Callback data format: admin_mail_detail:<ticket_id>:<return_offset>
    parts = query.data.split(":")
    ticket_id = parts[1]
    return_offset = int(parts[2]) if len(parts) > 2 else 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Feedback).where(Feedback.ticket_id == ticket_id))
        feedback = result.scalar_one_or_none()
        if not feedback:
            await query.edit_message_text("❌ Звернення не знайдено.")
            return

        category_ua = {
            "complaint": "СКАРГА ⚠️",
            "thanks": "ПОДЯКА ❤️",
            "suggestion": "ПРОПОЗИЦІЯ 💡"
        }.get(feedback.category, feedback.category.upper())

        status_text = {
            "sent": "✅ Надіслано на omet@omr.gov.ua",
            "rejected": "❌ Відхилено модератором",
            "pending": "⏳ Очікує модерації"
        }.get(feedback.email_status, "⏳ Очікує модерації")

        text = (
            f"📧 <b>Картка звернення {feedback.ticket_id}</b>\n\n"
            f"📌 <b>Категорія:</b> {category_ua}\n"
            f"📅 <b>Дата:</b> {feedback.created_at.strftime('%d.%m.%Y %H:%M') if feedback.created_at else ''}\n"
            f"👤 <b>Заявник:</b> {feedback.user_name or 'Не вказано'}\n"
            f"📞 <b>Телефон:</b> {feedback.user_phone or 'Не вказано'}\n"
            f"📧 <b>Email:</b> {feedback.user_email or 'Не вказано'}\n"
        )

        if feedback.category in ("complaint", "thanks") and (feedback.route or feedback.board_number or feedback.transport_type):
            t_prefix = "Трамвай" if feedback.transport_type == "tram" else "Тролейбус" if feedback.transport_type == "trolleybus" else ""
            route_str = f"{t_prefix} № {feedback.route}" if t_prefix and feedback.route else (feedback.route or "")
            text += (
                f"🚊 <b>Транспорт:</b> {route_str or 'Не вказано'}\n"
                f"🔢 <b>Бортовий номер:</b> {feedback.board_number or 'Не вказано'}\n"
            )

        text += (
            f"----------------------------------------\n"
            f"📝 <b>Текст звернення:</b>\n{feedback.text}\n"
            f"----------------------------------------\n"
            f"✉️ <b>Статус відправки:</b>\n{status_text}"
        )

        keyboard = [
            [InlineKeyboardButton("📧 Надіслати повторно на Email", callback_data=f"admin_mail_resend:{feedback.ticket_id}:{return_offset}")],
            [InlineKeyboardButton("⬅️ Назад до списку", callback_data=f"admin_mail_cat:{feedback.category}:{return_offset}")]
        ]

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)


async def admin_mail_resend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повторне або примусове надсилання звернення на Email секретаря"""
    query = update.callback_query
    await query.answer("⏳ Пересилання... Зачекайте.")
    if query.from_user.id not in GENERAL_ADMIN_IDS:
        return

    # Callback data format: admin_mail_resend:<ticket_id>:<return_offset>
    parts = query.data.split(":")
    ticket_id = parts[1]
    return_offset = int(parts[2]) if len(parts) > 2 else 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Feedback).where(Feedback.ticket_id == ticket_id))
        feedback = result.scalar_one_or_none()
        if not feedback:
            await query.answer("❌ Звернення не знайдено.")
            return

        from services.pdf_service import generate_feedback_pdf
        from services.email_service import send_feedback_email
        import os

        pdf_path = None
        try:
            await query.edit_message_text(f"⏳ Спроба відправки звернення {ticket_id} на пошту секретарю... Генеруємо PDF...")

            pdf_path = generate_feedback_pdf(feedback)

            loop = asyncio.get_running_loop()
            success = await loop.run_in_executor(
                None,
                send_feedback_email,
                pdf_path,
                feedback.ticket_id,
                feedback.category
            )

            if success:
                feedback.email_status = "sent"
                await session.commit()
                await query.answer("✅ Успішно надіслано на omet@omr.gov.ua!", show_alert=True)
            else:
                await query.answer("❌ Збій відправки SMTP. Перевірте логи.", show_alert=True)
        except Exception as err:
            logger.error(f"❌ Помилка при повторному надсиланні звернення {ticket_id}: {err}")
            await query.answer(f"❌ Помилка: {err}", show_alert=True)
        finally:
            if pdf_path and os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except Exception as del_err:
                    logger.error(f"Не вдалося видалити тимчасовий PDF {pdf_path}: {del_err}")

    # Повертаємося до картки деталей
    query.data = f"admin_mail_detail:{ticket_id}:{return_offset}"
    await admin_mail_show_detail(update, context)


# --- ФУНКЦІЇ ЗАГАЛЬНИХ АДМІНІВ (Розсилка і Sync) ---

async def admin_sync_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручний запуск синхронізації"""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return
    await query.edit_message_text("⏳ Синхронізація даних... Зачекайте.")

    try:
        count = await tickets_service.sync_new_feedbacks_to_sheets()
        # Кнопка "Назад" має вести в General Menu
        back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В адмінку", callback_data="general_admin_menu")]])

        await query.edit_message_text(
            f"✅ Успішно!\nВивантажено нових записів: <b>{count}</b>",
            reply_markup=back_btn,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await query.edit_message_text(f"❌ Помилка: {e}")


async def admin_show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує статистику для загального адміна"""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return

    user_stats = await user_service.get_stats()
    feedback_stats = await tickets_service.get_feedback_stats()
    by_category = feedback_stats.get("by_category", {})

    def _cat_count(key: str) -> int:
        if key == "thanks":
            return by_category.get("thanks", 0) + by_category.get("Подяки", 0) + by_category.get("Подяка", 0)
        if key == "complaint":
            return by_category.get("complaint", 0) + by_category.get("Скарги", 0) + by_category.get("Скарга", 0)
        if key == "suggestion":
            return by_category.get("suggestion", 0) + by_category.get("Пропозиції", 0) + by_category.get("Пропозиція", 0)
        return by_category.get(key, 0)

    known_total = _cat_count("complaint") + _cat_count("thanks") + _cat_count("suggestion")
    other_count = max(0, feedback_stats["total"] - known_total)

    current_users = user_stats['total_users']
    grand_total = current_users + LEGACY_USERS_OFFSET

    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всього користувачів: <b>{grand_total}</b> (поточна серверна БД: {current_users} + {LEGACY_USERS_OFFSET} з попереднього сервера)\n\n"
        f"📩 Всього звернень: <b>{feedback_stats['total']}</b>\n"
        f"🆕 Нових (не синхр.): <b>{feedback_stats['new']}</b>\n"
        f"✅ Синхронізованих: <b>{feedback_stats['synced']}</b>\n\n"
        "📂 Розподіл за категоріями:\n"
        f"• Скарги: <b>{_cat_count('complaint')}</b>\n"
        f"• Подяки: <b>{_cat_count('thanks')}</b>\n"
        f"• Пропозиції: <b>{_cat_count('suggestion')}</b>\n"
        f"• Інше: <b>{other_count}</b>\n"
    )

    keyboard = [
        [InlineKeyboardButton("📥 Вивантажити користувачів (CSV)", callback_data="admin_export_users")],
        [InlineKeyboardButton("🔙 В адмінку", callback_data="general_admin_menu")]
    ]
    back_btn = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=back_btn, parse_mode=ParseMode.HTML)


async def admin_export_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Експортує список усіх користувачів у CSV файл та надсилає його"""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return

    try:
        users = await user_service.get_all_users()
        
        import io
        import csv
        from datetime import timezone
        from zoneinfo import ZoneInfo

        output = io.StringIO()
        # Використовуємо крапку з комою як роздільник (для автоматичного відкриття в Excel)
        writer = csv.writer(output, delimiter=';')
        
        writer.writerow(["Telegram ID", "ПІБ", "Username", "Дата реєстрації", "Підписка на новини"])
        
        for u in users:
            local_dt = "N/A"
            if u.joined_at:
                dt_val = u.joined_at
                if dt_val.tzinfo is None:
                    dt_val = dt_val.replace(tzinfo=timezone.utc)
                local_dt = dt_val.astimezone(ZoneInfo("Europe/Kyiv")).strftime("%d.%m.%Y %H:%M")

            subscribed_str = "Так" if u.is_subscribed else "Ні"
            
            writer.writerow([
                str(u.telegram_id),
                str(u.first_name or ""),
                str(u.username or ""),
                local_dt,
                subscribed_str
            ])
            
        csv_data = output.getvalue().encode('utf-8-sig')
        output.close()

        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=io.BytesIO(csv_data),
            filename="users_export.csv",
            caption=f"📊 Вивантажено список усіх користувачів бота.\nВсього записів: <b>{len(users)}</b>",
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"Failed to export users: {e}", exc_info=True)
        await query.message.reply_text(f"❌ Сталася помилка при експорті користувачів: {e}")


async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return

    # Кнопка "Скасувати" веде в General Menu
    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Скасувати", callback_data="general_admin_menu")]])

    # --- ЗМІНА: Зберігаємо результат (повідомлення) у змінну ---
    sent_msg = await query.edit_message_text(
        "📢 <b>Режим розсилки новин</b>\n\n"
        "Надішліть повідомлення (текст, фото або відео), яке отримають <b>ВСІ</b> користувачі бота.",
        reply_markup=back_btn,
        parse_mode=ParseMode.HTML
    )

    # --- ЗМІНА: Запам'ятовуємо ID цього повідомлення, щоб видалити пізніше ---
    context.user_data['broadcast_start_msg_id'] = sent_msg.message_id

    return States.ADMIN_BROADCAST_TEXT


async def admin_broadcast_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отримує повідомлення від адміна, показує прев'ю (без зайвих кнопок)
    та меню підтвердження. Зберігає ID повідомлень для подальшого видалення.
    """
    user_id = update.effective_user.id
    msg = update.message
    if user_id not in GENERAL_ADMIN_IDS:
        return ConversationHandler.END

    # 1. Перевіряємо кількість підписників
    users = await user_service.get_subscribed_users_ids()
    if not users:
        # Очищення стартового повідомлення, якщо користувачів немає
        start_msg_id = context.user_data.pop('broadcast_start_msg_id', None)
        if start_msg_id:
            try:
                await context.bot.delete_message(chat_id=msg.chat_id, message_id=start_msg_id)
            except Exception:
                pass

        await msg.reply_text(
            "🤷‍♂️ Немає користувачів для розсилки.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 В адмінку", callback_data="general_admin_menu")]])
        )
        return ConversationHandler.END

    # 2. Зберігаємо дані для розсилки
    context.user_data['broadcast_msg_id'] = msg.message_id
    context.user_data['broadcast_chat_id'] = msg.chat_id

    # Визначаємо текст та медіа для збереження в новинах
    news_text = msg.text or msg.caption or ""
    news_media_type = None
    news_media_file_id = None
    if msg.photo:
        news_media_type = "photo"
        news_media_file_id = msg.photo[-1].file_id
    elif msg.video:
        news_media_type = "video"
        news_media_file_id = msg.video.file_id
    elif msg.animation:
        news_media_type = "animation"
        news_media_file_id = msg.animation.file_id
    elif msg.document:
        news_media_type = "document"
        news_media_file_id = msg.document.file_id

    context.user_data['broadcast_news_data'] = {
        'text': news_text,
        'media_type': news_media_type,
        'media_file_id': news_media_file_id
    }

    # --- Формуємо список видалення ---
    msgs_to_delete = []

    # а) Додаємо стартове повідомлення ("Режим розсилки..."), якщо воно є
    start_msg_id = context.user_data.pop('broadcast_start_msg_id', None)
    if start_msg_id:
        msgs_to_delete.append(start_msg_id)

    # б) Додаємо повідомлення, яке щойно надіслав адмін (текст/фото)
    msgs_to_delete.append(msg.message_id)

    # Зберігаємо список у контекст (поки що неповний)
    context.user_data['msgs_to_delete'] = msgs_to_delete

    # 3. Робимо "Прев'ю"
    # Ми зберігаємо повідомлення в змінну і додаємо його ID у список видалення
    preview_title_msg = await msg.reply_text("👁 <b>Попередній перегляд:</b>", parse_mode=ParseMode.HTML)
    msgs_to_delete.append(preview_title_msg.message_id)
    # ==============================

    preview_msg = await msg.copy(chat_id=user_id)
    # Додаємо ID самого прев'ю (копії) до списку видалення
    context.user_data['msgs_to_delete'].append(preview_msg.message_id)

    # 4. Клавіатура підтвердження
    confirm_keyboard = [
        [InlineKeyboardButton(f"✅ Надіслати ({len(users)} кор.)", callback_data="broadcast_confirm")],
        [InlineKeyboardButton("❌ Скасувати / Редагувати", callback_data="broadcast_cancel")]
    ]

    menu_msg = await msg.reply_text(
        f"📢 <b>Підготовка до розсилки</b>\n\n"
        f"👥 Кількість отримувачів: <b>{len(users)}</b>\n"
        f"⚠️ Перевірте вигляд повідомлення вище. \n"
        f"Натисніть <b>Надіслати</b> для запуску або <b>Скасувати</b> для редагування.",
        reply_markup=InlineKeyboardMarkup(confirm_keyboard),
        parse_mode=ParseMode.HTML
    )
    # Додаємо ID меню до списку видалення
    context.user_data['msgs_to_delete'].append(menu_msg.message_id)

    # Переходимо до стану очікування підтвердження
    return States.ADMIN_BROADCAST_CONFIRM


async def admin_broadcast_send_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Виконує розсилку або скасування та очищає чат"""
    query = update.callback_query
    await query.answer()
    if update.effective_user.id not in GENERAL_ADMIN_IDS:
        return ConversationHandler.END

    action = query.data
    chat_id = update.effective_chat.id

    # Отримуємо список повідомлень для видалення
    msgs_to_delete = context.user_data.get('msgs_to_delete', [])
    # Додаємо поточне меню до списку видалення (щоб не висіло)
    msgs_to_delete.append(query.message.message_id)

    try:
        # --- ЛОГІКА СКАСУВАННЯ ---
        if action == "broadcast_cancel":
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Розсилку скасовано. Ви можете спробувати знову.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 В адмінку", callback_data="general_admin_menu")]])
            )
            return ConversationHandler.END

        # --- ЛОГІКА ВІДПРАВКИ ---
        status_msg = await query.message.reply_text("🚀 Розсилка розпочалась... Не закривайте бота.")

        # РЕКОМЕНДАЦІЯ: Додайте його в список на видалення для надійності
        msgs_to_delete.append(status_msg.message_id)

        msg_id = context.user_data.get('broadcast_msg_id')
        from_chat_id = context.user_data.get('broadcast_chat_id')
        users = await user_service.get_subscribed_users_ids()

        # Автоматичне створення запису в оперативних новинах
        news_payload = context.user_data.get('broadcast_news_data', {})
        admin_user = update.effective_user
        created_news = None
        try:
            admin_name = admin_user.full_name or admin_user.first_name or "Адміністратор"
            created_news = await news_service.save_broadcast_news({
                "admin_id": admin_user.id,
                "admin_name": admin_name,
                "text": news_payload.get("text", ""),
                "media_type": news_payload.get("media_type"),
                "media_file_id": news_payload.get("media_file_id"),
                "sent_count": 0,
                "blocked_count": 0
            })
        except Exception as save_err:
            logger.error(f"Failed to auto-save news broadcast: {save_err}")

        count = 0
        blocked = 0
        start_time = datetime.now()

        # Кнопка "Закрити" ТІЛЬКИ для користувачів
        user_close_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Зрозуміло (Приховати)", callback_data="broadcast_dismiss")]
        ])

        # Цикл розсилки
        for index, user_id in enumerate(users, start=1):
            try:
                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=from_chat_id,
                    message_id=msg_id,
                    reply_markup=user_close_btn  # Додаємо кнопку тільки тут
                )
                count += 1
                if index % BROADCAST_BATCH_SIZE == 0:
                    await asyncio.sleep(BROADCAST_PAUSE_SEC)
            except Exception as e:
                logger.warning(f"Failed to send broadcast to {user_id}: {e}")
                blocked += 1

        # Оновлюємо статистику створеної новини
        if created_news:
            try:
                await news_service.update_broadcast_stats(
                    news_id=created_news.id,
                    sent_count=count,
                    blocked_count=blocked
                )
            except Exception as update_err:
                logger.error(f"Failed to update news broadcast stats: {update_err}")

        # Видаляємо повідомлення "Розсилка розпочалась..."
        #await status_msg.delete()

        # Фінальний звіт
        duration = (datetime.now() - start_time).total_seconds()
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"✅ <b>Розсилка завершена та додана в «Оперативні новини»!</b>\n\n"
                f"📨 Успішно надіслано: <b>{count}</b>\n"
                f"🚫 Не отримали (блокували): <b>{blocked}</b>\n"
                f"⏱️ Час виконання: <b>{duration:.1f} сек.</b>"
            ),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 В адмінку", callback_data="general_admin_menu")]]),
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"Error in broadcast confirm: {e}")
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Виникла помилка при розсилці.")

    finally:
        # --- ОЧИЩЕННЯ ЧАТУ (Видалення технічних повідомлень) ---
        for mid in msgs_to_delete:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception as e:
                # Повідомлення може бути вже видалене або застаріле
                logger.debug(f"Could not delete message {mid}: {e}")

        # Очищаємо дані сесії
        context.user_data.pop('broadcast_msg_id', None)
        context.user_data.pop('broadcast_chat_id', None)
        context.user_data.pop('broadcast_news_data', None)
        context.user_data.pop('msgs_to_delete', None)

    return ConversationHandler.END


# --- ІСНУЮЧА ФУНКЦІЯ: Меню Музею (Максим) ---
async def admin_museum_menu_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню музею"""
    query = update.callback_query
    if query: await query.answer()

    # Перевірка на адміна
    if update.effective_user.id not in MUSEUM_ADMIN_IDS:
        return ConversationHandler.END

    keyboard = await get_admin_main_menu_keyboard()
    text = "👋 Вітаємо в адмін-панелі Музею!"

    if query:
        await query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.effective_chat.send_message(text, reply_markup=keyboard)

    # ВАЖЛИВО: Ми завершуємо попередній діалог, щоб очистити стан
    return ConversationHandler.END





# Перевірка, чи є користувач адміном
async def is_admin(update: Update) -> bool:
    is_admin_user = update.effective_user.id in MUSEUM_ADMIN_IDS
    if not is_admin_user:
        logger.warning(f"Non-admin user {update.effective_user.id} tried to access admin functions.")
        await update.message.reply_text("❌ У вас немає прав доступу до цієї команди.")
    return is_admin_user


# Головне меню адміна
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Вхідна точка для команди /admin_museum.
    Перевіряє права та перенаправляє на показ повного меню.
    """
    if not await is_admin(update):
        return ConversationHandler.END

    # Просто викликаємо нашу "правильну" функцію показу меню
    # Вона покаже 4 кнопки і завершить будь-який діалог
    return await admin_menu_show(update, context)


# --- Потік додавання дати ---
async def admin_add_date_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    logger.info(f"📢 Admin attempt by user_id: {user_id}. Expected: {MUSEUM_ADMIN_IDS}")  # <-- ЛОГ

    if user_id not in MUSEUM_ADMIN_IDS:
        await query.message.reply_text(f"⛔ Помилка доступу. Ваш ID: {user_id}")  # <-- ПОВІДОМЛЕННЯ
        return ConversationHandler.END

    # Клавіатура для скасування
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        "Будь ласка, введіть дату та час екскурсії у чіткому форматі:\n\n"
        "<code>ДД.ММ.РРРР ГГ:ХХ</code>\n\n"
        "Наприклад: <code>25.11.2025 11:00</code>"
    )

    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML # Використовуємо HTML для <code>
    )
    return States.ADMIN_STATE_ADD_DATE


async def admin_add_date_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in MUSEUM_ADMIN_IDS: return ConversationHandler.END

    date_text = update.message.text.strip()

    # --- ПОЧАТОК ВАЛІДАЦІЇ ---
    try:
        # 1. Перевірка формату (ДД.ММ.РРРР ГГ:ХХ)
        if not re.match(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$", date_text):
            raise ValueError("Невірний формат. Очікується <code>ДД.ММ.РРРР ГГ:ХХ</code>.")

        # 2. Перевірка коректності дати (напр., не 30.02.2025)
        try:
            parsed_date = datetime.strptime(date_text, '%d.%m.%Y %H:%M')
        except ValueError:
            raise ValueError("Некоректна дата. Можливо, неіснуючий день або місяць?")

        # 3. Перевірка, чи дата не в минулому
        if parsed_date < datetime.now():
            raise ValueError("Дата не може бути у минулому.")

        # --- ВАЛІДАЦІЯ ПРОЙДЕНА ---
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        sheets.append_row(sheet_name="MuseumDates", values=[date_text])
        museum_service.invalidate_dates_cache()

        logger.info(f"✅ Admin added new date: {date_text}")
        await update.message.reply_text(f"✅ Дату '<b>{date_text}</b>' успішно додано.", parse_mode=ParseMode.HTML)

        # Повертаємося до головного адмін-меню
        await admin_menu_show(update, context) # Показуємо повне меню
        return ConversationHandler.END # Завершуємо діалог

    except ValueError as e:
        # --- ВАЛІДАЦІЯ НЕ ПРОЙДЕНА ---
        logger.warning(f"Admin date validation failed: {e}")
        await update.message.reply_text(
            f"❌ <b>Помилка:</b> {e}\n\n"
            f"Будь ласка, спробуйте ще раз або натисніть 'Назад'.",
            parse_mode=ParseMode.HTML
        )
        # Повертаємося до ЦЬОГО Ж стану, змушуючи адміна ввести дату знову
        return States.ADMIN_STATE_ADD_DATE

    except Exception as e:
        # --- Інша помилка (напр. Google Sheets) ---
        logger.error(f"Failed to add date by admin: {e}")
        await update.message.reply_text(f"❌ Сталася системна помилка при додаванні дати: {e}")

        await admin_menu_show(update, context) # Показуємо ПОВНЕ меню
        return ConversationHandler.END


# --- Потік видалення дати ---
async def admin_del_date_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Одразу відповідаємо, щоб телеграм не показував "годинничок"
    await query.answer()

    if query.from_user.id not in MUSEUM_ADMIN_IDS:
        return ConversationHandler.END

    # Показуємо "Зачекайте", бо читання може бути довгим
    await query.edit_message_text("⏳ Завантажую список дат...")

    try:
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        loop = asyncio.get_running_loop()

        # Асинхронне читання
        dates_data = await loop.run_in_executor(
            None,
            sheets.read_range,
            "MuseumDates!A1:A100"
        )

        if not dates_data:
            await query.edit_message_text("Немає дат для видалення.", reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")]]))
            return ConversationHandler.END

        keyboard = []
        for i, row in enumerate(dates_data):
            if row:  # Переконуємося, що рядок не пустий
                date_str = row[0]
                cell_ref = f"A{i + 1}"  # A1, A2, ...
                keyboard.append([InlineKeyboardButton(f"❌ {date_str}", callback_data=f"admin_del_confirm:{cell_ref}")])

        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")])
        await query.edit_message_text("Оберіть дату, яку потрібно видалити:",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Failed to show dates for deletion: {e}")
        await query.edit_message_text(f"❌ Помилка: {e}")

    return States.ADMIN_STATE_DEL_DATE_CONFIRM


async def admin_del_date_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in MUSEUM_ADMIN_IDS: return ConversationHandler.END

    cell_to_delete = query.data.split(":")[1] # "A5"

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---

    # 1. Створюємо клавіатуру "Назад" ЗАЗДАЛЕГІДЬ
    keyboard_back = [
        [InlineKeyboardButton("⬅️ Назад до адмін-панелі", callback_data="admin_museum_menu")]
    ]
    reply_markup_back = InlineKeyboardMarkup(keyboard_back)

    # 2. (Покращення) Отримуємо текст кнопки, яку натиснули
    #    (Ваш старий код [0][0] працював би, лише якщо натиснути першу кнопку)
    date_str = ""
    for row in query.message.reply_markup.inline_keyboard:
        if row[0].callback_data == query.data:
            date_str = row[0].text.replace("❌ ", "")
            break
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

    try:
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        ok = sheets.clear_cell(sheet_name="MuseumDates", cell=cell_to_delete)
        if ok:
            museum_service.invalidate_dates_cache()

        # --- ПОЧАТОК ВИПРАВЛЕННЯ 2 ---
        if ok:
            await query.edit_message_text(
                text=f"✅ Дату '{date_str}' (комірка {cell_to_delete}) видалено.",
                reply_markup=reply_markup_back
            )
        else:
            await query.edit_message_text(
                text=(
                    "❌ Не вдалося очистити дату в Google Sheets (перевірте права сервісного "
                    f"акаунта та вкладку MuseumDates). Комірка: {cell_to_delete}"
                ),
                reply_markup=reply_markup_back
            )
        # --- КІНЕЦЬ ВИПРАВЛЕННЯ 2 ---

    except Exception as e:
        logger.error(f"Failed to delete date: {e}")

        # --- ПОЧАТОК ВИПРАВЛЕННЯ 3 ---
        # Додаємо reply_markup до повідомлення про помилку
        await query.edit_message_text(
            text=f"❌ Помилка при видаленні: {e}",
            reply_markup=reply_markup_back
        )
        # --- КІНЕЦЬ ВИПРАВЛЕННЯ 3 ---

    return ConversationHandler.END


async def admin_show_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує список останніх бронювань з 'MuseumBookings' з пагінацією."""
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in MUSEUM_ADMIN_IDS: return

    # Визначаємо offset з callback_data (наприклад, "admin_show_bookings:15")
    offset = 0
    if query.data and ":" in query.data:
        try:
            offset = int(query.data.split(":")[1])
        except (ValueError, IndexError):
            offset = 0

    limit = 15
    try:
        # Читаємо на 1 більше, щоб зрозуміти чи є наступна сторінка
        bookings_data = await museum_service.get_last_bookings(limit=limit + 1, offset=offset)

        # Перевіряємо наявність наступної сторінки (якщо отримали більше ніж limit + 1 елементів з урахуванням заголовка)
        has_next = len(bookings_data) > (limit + 1)
        
        # Залишаємо тільки 15 елементів (+ заголовок)
        display_data = bookings_data[:limit + 1] if has_next else bookings_data

        if not display_data or len(display_data) < 2: # Якщо є тільки заголовок
            if offset > 0:
                keyboard = []
                nav_buttons = []
                nav_buttons.append(InlineKeyboardButton("⬅️ Попередні 15", callback_data=f"admin_show_bookings:{max(0, offset - limit)}"))
                keyboard.append(nav_buttons)
                keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")])
                
                await query.edit_message_text(
                    "📋 Більше немає заявок.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await query.edit_message_text(
                    "📋 Наразі немає жодного бронювання.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")]])
                )
            return

        # Відображення діапазону заявок
        start_num = offset + 1
        end_num = offset + len(display_data) - 1
        text_list = f"📋 <b>Останні заявки на екскурсії ({start_num}-{end_num}):</b>\n\n"
        
        # Пропускаємо заголовок (display_data[0]) і беремо дані
        for row in display_data[1:]:
            if row:
                reg_date = html.escape(str(row[0]))
                excursion_date = html.escape(str(row[1])) if len(row) > 1 else "N/A"
                count = html.escape(str(row[2])) if len(row) > 2 else "N/A"
                name = html.escape(str(row[3])) if len(row) > 3 else "N/A"
                phone = html.escape(str(row[4])) if len(row) > 4 else "N/A"

                text_list += (
                    f"▪️ <b>{name}</b> ({phone})\n"
                    f"   На дату: <b>{excursion_date}</b>, {count} осіб.\n"
                    f"   (Заявка від: {reg_date})\n"
                    f"---------------------\n"
                )

        # Кнопки навігації
        keyboard = []
        nav_buttons = []
        if offset > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Попередні 15", callback_data=f"admin_show_bookings:{max(0, offset - limit)}"))
        if has_next:
            nav_buttons.append(InlineKeyboardButton("Наступні 15 ➡️", callback_data=f"admin_show_bookings:{offset + limit}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
            
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")])

        # Використовуємо HTML для форматування
        await query.edit_message_text(
            text=text_list,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"Failed to show bookings: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Сталася помилка при читанні бронювань з бази даних.\n"
            "Будь ласка, зверніться до адміністратора або спробуйте пізніше.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")]]
            )
        )

    # Ця функція не є частиною діалогу, тому нічого не повертаємо


# Обробник для повернення в адмін-меню
async def admin_menu_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Повертає адміна до ПОВНОГО головного меню адмін-панелі.
    Працює і з командами (/admin_museum), і з кнопками (Назад).
    """
    keyboard = await get_admin_main_menu_keyboard()
    text = "👋 Вітаємо в адмін-панелі Музею!"

    if update.callback_query:
        # Якщо це натискання кнопки
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=keyboard
            )
        except Exception as e:
            # Помилка (напр., повідомлення те саме) - просто видаляємо та надсилаємо нове
            await update.callback_query.message.delete()
            await update.effective_chat.send_message(
                text=text,
                reply_markup=keyboard
            )
    else:
        # Якщо це команда /admin_museum
        await update.effective_chat.send_message(
            text=text,
            reply_markup=keyboard
        )

    return ConversationHandler.END


# --- Святкові екскурсії (Максим) ---

async def admin_add_holiday_date_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    if user_id not in MUSEUM_ADMIN_IDS:
        await query.message.reply_text(f"⛔ Помилка доступу. Ваш ID: {user_id}")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        "Будь ласка, введіть дату та час <b>святкової екскурсії</b> у чіткому форматі:\n\n"
        "<code>ДД.ММ.РРРР ГГ:ХХ</code>\n\n"
        "Наприклад: <code>25.11.2025 11:00</code>"
    )

    await query.edit_message_text(
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    return States.ADMIN_STATE_ADD_HOLIDAY_DATE


async def admin_add_holiday_date_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in MUSEUM_ADMIN_IDS: return ConversationHandler.END

    date_text = update.message.text.strip()

    try:
        if not re.match(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$", date_text):
            raise ValueError("Невірний формат. Очікується <code>ДД.ММ.РРРР ГГ:ХХ</code>.")

        try:
            parsed_date = datetime.strptime(date_text, '%d.%m.%Y %H:%M')
        except ValueError:
            raise ValueError("Некоректна дата. Можливо, неіснуючий день або місяць?")

        if parsed_date < datetime.now():
            raise ValueError("Дата не може бути у минулому.")

        # --- ВАЛІДАЦІЯ ПРОЙДЕНА ---
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        
        loop = asyncio.get_running_loop()
        dates_data = await loop.run_in_executor(
            None,
            sheets.read_range,
            "MuseumDates!B1:B100"
        )
        
        first_empty_row = 1
        if dates_data:
            first_empty_row = len(dates_data) + 1
        
        cell_ref = f"B{first_empty_row}"
        
        await loop.run_in_executor(
            None,
            sheets.update_cell,
            "MuseumDates",
            cell_ref,
            date_text
        )
        
        museum_service.invalidate_holiday_dates_cache()

        logger.info(f"✅ Admin added new holiday date: {date_text} in {cell_ref}")
        await update.message.reply_text(f"✅ Святкову дату '<b>{date_text}</b>' успішно додано.", parse_mode=ParseMode.HTML)

        await admin_menu_show(update, context)
        return ConversationHandler.END

    except ValueError as e:
        logger.warning(f"Admin holiday date validation failed: {e}")
        await update.message.reply_text(
            f"❌ <b>Помилка:</b> {e}\n\n"
            f"Будь ласка, спробуйте ще раз або натисніть 'Назад'.",
            parse_mode=ParseMode.HTML
        )
        return States.ADMIN_STATE_ADD_HOLIDAY_DATE

    except Exception as e:
        logger.error(f"Failed to add holiday date by admin: {e}")
        await update.message.reply_text(f"❌ Сталася системна помилка при додаванні святкової дати: {e}")
        await admin_menu_show(update, context)
        return ConversationHandler.END


async def admin_del_holiday_date_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in MUSEUM_ADMIN_IDS:
        return ConversationHandler.END

    await query.edit_message_text("⏳ Завантажую список святкових дат...")

    try:
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        loop = asyncio.get_running_loop()

        dates_data = await loop.run_in_executor(
            None,
            sheets.read_range,
            "MuseumDates!B1:B100"
        )

        keyboard = []
        for i, row in enumerate(dates_data):
            if i == 0: continue
            if row:
                date_str = row[0]
                cell_ref = f"B{i + 1}"
                keyboard.append([InlineKeyboardButton(f"❌ {date_str}", callback_data=f"admin_del_holiday_confirm:{cell_ref}")])

        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")])
        await query.edit_message_text("Оберіть святкову дату, яку потрібно видалити:",
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"Failed to show holiday dates for deletion: {e}")
        await query.edit_message_text(f"❌ Помилка: {e}")

    return States.ADMIN_STATE_DEL_HOLIDAY_DATE_CONFIRM


async def admin_del_holiday_date_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in MUSEUM_ADMIN_IDS: return ConversationHandler.END

    cell_to_delete = query.data.split(":")[1]

    keyboard_back = [
        [InlineKeyboardButton("⬅️ Назад до адмін-панелі", callback_data="admin_museum_menu")]
    ]
    reply_markup_back = InlineKeyboardMarkup(keyboard_back)

    date_str = ""
    for row in query.message.reply_markup.inline_keyboard:
        if row[0].callback_data == query.data:
            date_str = row[0].text.replace("❌ ", "")
            break

    try:
        sheets = GoogleSheetsClient(GOOGLE_SHEETS_ID)
        ok = sheets.clear_cell(sheet_name="MuseumDates", cell=cell_to_delete)
        if ok:
            museum_service.invalidate_holiday_dates_cache()

        if ok:
            await query.edit_message_text(
                text=f"✅ Святкову дату '{date_str}' (комірка {cell_to_delete}) видалено.",
                reply_markup=reply_markup_back
            )
        else:
            await query.edit_message_text(
                text=f"❌ Не вдалося очистити святкову дату в Google Sheets. Комірка: {cell_to_delete}",
                reply_markup=reply_markup_back
            )

    except Exception as e:
        logger.error(f"Failed to delete holiday date: {e}")
        await query.edit_message_text(
            text=f"❌ Помилка при видаленні святкової дати: {e}",
            reply_markup=reply_markup_back
        )

    return ConversationHandler.END


async def admin_show_holiday_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує список останніх святкових бронювань з пагінацією."""
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in MUSEUM_ADMIN_IDS: return

    offset = 0
    if query.data and ":" in query.data:
        try:
            offset = int(query.data.split(":")[1])
        except (ValueError, IndexError):
            offset = 0

    limit = 15
    try:
        bookings_data = await museum_service.get_last_holiday_bookings(limit=limit + 1, offset=offset)

        has_next = len(bookings_data) > (limit + 1)
        display_data = bookings_data[:limit + 1] if has_next else bookings_data

        if not display_data or len(display_data) < 2:
            if offset > 0:
                keyboard = []
                nav_buttons = []
                nav_buttons.append(InlineKeyboardButton("⬅️ Попередні 15", callback_data=f"admin_show_holiday_bookings:{max(0, offset - limit)}"))
                keyboard.append(nav_buttons)
                keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")])
                
                await query.edit_message_text(
                    "📋 Більше немає святкових заявок.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await query.edit_message_text(
                    "📋 Наразі немає жодного святкового бронювання.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")]])
                )
            return

        start_num = offset + 1
        end_num = offset + len(display_data) - 1
        text_list = f"📋 <b>Останні святкові заявки на екскурсії ({start_num}-{end_num}):</b>\n\n"
        
        for row in display_data[1:]:
            if row:
                reg_date = html.escape(str(row[0]))
                excursion_date = html.escape(str(row[1])) if len(row) > 1 else "N/A"
                count = html.escape(str(row[2])) if len(row) > 2 else "N/A"
                name = html.escape(str(row[3])) if len(row) > 3 else "N/A"
                phone = html.escape(str(row[4])) if len(row) > 4 else "N/A"

                text_list += (
                    f"▪️ <b>{name}</b> ({phone})\n"
                    f"   На дату: <b>{excursion_date}</b>, {count} осіб.\n"
                    f"   (Заявка від: {reg_date})\n"
                    f"---------------------\n"
                )

        keyboard = []
        nav_buttons = []
        if offset > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Попередні 15", callback_data=f"admin_show_holiday_bookings:{max(0, offset - limit)}"))
        if has_next:
            nav_buttons.append(InlineKeyboardButton("Наступні 15 ➡️", callback_data=f"admin_show_holiday_bookings:{offset + limit}"))
        
        if nav_buttons:
            keyboard.append(nav_buttons)
            
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")])

        # Використовуємо HTML для форматування
        await query.edit_message_text(
            text=text_list,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"Failed to show holiday bookings: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Сталася помилка при читанні святкових бронювань з бази даних.\n"
            "Будь ласка, зверніться до адміністратора або спробуйте пізніше.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")]]
            )
        )
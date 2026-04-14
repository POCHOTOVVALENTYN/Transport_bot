import asyncio
import logging
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler,
                          filters)
from config.settings import MUSEUM_ADMIN_ID, GOOGLE_SHEETS_ID, GENERAL_ADMIN_IDS, BROADCAST_BATCH_SIZE, BROADCAST_PAUSE_SEC
from integrations.google_sheets.client import GoogleSheetsClient
from utils.logger import logger
from bot.states import States
from handlers.command_handlers import get_admin_main_menu_keyboard

from services.user_service import UserService
from services.tickets_service import TicketsService
from services.museum_service import MuseumService


user_service = UserService()
tickets_service = TicketsService()
museum_service = MuseumService()



# Стани для адміна
#(ADMIN_STATE_ADD_DATE, ADMIN_STATE_DEL_DATE_CONFIRM) = range(16, 18)  # Використовуємо нові стани


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

    text = (
        f"⚙️ <b>Панель Керування</b>\n\n"
        f"👥 Всього користувачів: <b>{stats['total_users']}</b>\n"
        f"🔔 Підписано на новини: <b>{stats['subscribed_users']}</b> 🟢\n"  
        f"👋 Вітаю, {update.effective_user.first_name}!"
    )

    keyboard = [
        [InlineKeyboardButton("📢 Зробити розсилку (Новини)", callback_data="admin_broadcast_start")],
        [InlineKeyboardButton("🔄 Синхронізувати БД -> Sheets", callback_data="admin_sync_db")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("🏠 В режим користувача", callback_data="main_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


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
        return by_category.get(key, 0)

    known_total = _cat_count("complaint") + _cat_count("thanks") + _cat_count("suggestion")
    other_count = max(0, feedback_stats["total"] - known_total)

    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всього користувачів: <b>{user_stats['total_users']}</b>\n"
        f"🔔 Підписані на розсилку: <b>{user_stats['subscribed_users']}</b>\n\n"
        f"📩 Всього звернень: <b>{feedback_stats['total']}</b>\n"
        f"🆕 Нових (не синхр.): <b>{feedback_stats['new']}</b>\n"
        f"✅ Синхронізованих: <b>{feedback_stats['synced']}</b>\n\n"
        "📂 Розподіл за категоріями:\n"
        f"• Скарги: <b>{_cat_count('complaint')}</b>\n"
        f"• Подяки: <b>{_cat_count('thanks')}</b>\n"
        f"• Пропозиції: <b>{_cat_count('suggestion')}</b>\n"
        f"• Інше: <b>{other_count}</b>\n"
    )

    back_btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В адмінку", callback_data="general_admin_menu")]])
    await query.edit_message_text(text, reply_markup=back_btn, parse_mode=ParseMode.HTML)


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
            "🤷‍♂️ Немає підписаних користувачів для розсилки.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 В адмінку", callback_data="general_admin_menu")]])
        )
        return ConversationHandler.END

    # 2. Зберігаємо дані для розсилки
    context.user_data['broadcast_msg_id'] = msg.message_id
    context.user_data['broadcast_chat_id'] = msg.chat_id

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

        # Видаляємо повідомлення "Розсилка розпочалась..."
        #await status_msg.delete()

        # Фінальний звіт
        duration = (datetime.now() - start_time).total_seconds()
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"✅ <b>Розсилка завершена!</b>\n\n"
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
        context.user_data.pop('msgs_to_delete', None)

    return ConversationHandler.END


# --- ІСНУЮЧА ФУНКЦІЯ: Меню Музею (Максим) ---
async def admin_museum_menu_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує меню музею"""
    query = update.callback_query
    if query: await query.answer()

    # Перевірка на Максима
    if update.effective_user.id != MUSEUM_ADMIN_ID:
        return ConversationHandler.END

    keyboard = await get_admin_main_menu_keyboard()
    text = "👋 Вітаю, Максиме! Ви в адмін-панелі Музею."

    if query:
        await query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.effective_chat.send_message(text, reply_markup=keyboard)

    # ВАЖЛИВО: Ми завершуємо попередній діалог, щоб очистити стан
    return ConversationHandler.END





# Перевірка, чи є користувач адміном
async def is_admin(update: Update) -> bool:
    is_admin_user = update.effective_user.id == MUSEUM_ADMIN_ID
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
    logger.info(f"📢 Admin attempt by user_id: {user_id}. Expected: {MUSEUM_ADMIN_ID}")  # <-- ЛОГ

    if user_id != MUSEUM_ADMIN_ID:
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
    if update.effective_user.id != MUSEUM_ADMIN_ID: return ConversationHandler.END

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

    if query.from_user.id != MUSEUM_ADMIN_ID:
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
    if query.from_user.id != MUSEUM_ADMIN_ID: return ConversationHandler.END

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
    """Показує список останніх бронювань з 'MuseumBookings'."""
    query = update.callback_query
    await query.answer()
    if query.from_user.id != MUSEUM_ADMIN_ID: return

    try:
        # Читаємо останні 50 бронювань (включно з заголовком) через сервіс
        bookings_data = await museum_service.get_last_bookings(limit=50)

        if not bookings_data or len(bookings_data) < 2: # Якщо є тільки заголовок
            await query.edit_message_text(
                "📋 Наразі немає жодного бронювання.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")]])
            )
            return

        text_list = "📋 **Останні заявки на екскурсії:**\n\n"
        # Пропускаємо заголовок (bookings_data[0]) і беремо дані
        for row in bookings_data[1:]:
            # A: Дата реєстрації, B: Дата екскурсії, C: Кількість, D: ПІБ, E: Телефон
            if row: # Переконуємося, що рядок не пустий
                reg_date = row[0]
                excursion_date = row[1] if len(row) > 1 else "N/A"
                count = row[2] if len(row) > 2 else "N/A"
                name = row[3] if len(row) > 3 else "N/A"
                phone = row[4] if len(row) > 4 else "N/A"

                text_list += (
                    f"▪️ <b>{name}</b> ({phone})\n"
                    f"   На дату: <b>{excursion_date}</b>, {count} осіб.\n"
                    f"   (Заявка від: {reg_date})\n"
                    f"---------------------\n"
                )

        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_museum_menu")]]

        # Використовуємо HTML для форматування
        await query.edit_message_text(
            text=text_list,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"Failed to show bookings: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ Сталася помилка при читанні бронювань.\n"
            "Переконайтеся, будь ласка, що в Google Sheets існує вкладка 'MuseumBookings' "
            "і бот має доступ до таблиці.",
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
    text = "👋 Вітаю, Максиме! Ви в адмін-панелі Музею."

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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from services.lost_items_service import LostItemsService
from utils.logger import logger

lost_items_service = LostItemsService()


async def show_lost_items_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Головний екран розділу 'Загублені речі' з контактами Інфоцентру
    та вибором категорій: '🪪 Знайдені документи' або '🎒 Особисті речі'.
    Callback: lost_items
    """
    query = update.callback_query
    if query:
        await query.answer()

    text = (
        "🔍 <b>Загубили речі в нашому транспорті?</b>\n\n"
        "Забрати знайдені речі та документи можна в <b>Інформаційному центрі</b> КП «ОМЕТ».\n\n"
        "📍 <b>Адреса:</b> м. Одеса, вул. Водопровідна, 1\n"
        "📞 <b>Телефон:</b> <code>048-717-54-54</code>\n"
        "🗓️ <b>Графік роботи:</b> Щоденно з 8:00 до 20:00\n\n"
        "Оберіть категорію для перегляду наявних знахідок:"
    )

    keyboard = [
        [InlineKeyboardButton("🪪 Знайдені документи", callback_data="lost_items_cat:document:0")],
        [InlineKeyboardButton("🎒 Особисті речі", callback_data="lost_items_cat:thing:0")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query and query.message:
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            return
        except Exception:
            pass

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


async def show_lost_items_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Відображає перелік знахідок у вибраній категорії ('document' або 'thing') з пагінацією.
    Callback: lost_items_cat:<category>:<offset>
    """
    query = update.callback_query
    if not query:
        return
    await query.answer()

    parts = query.data.split(":")
    category = parts[1] if len(parts) > 1 else "document"
    offset = int(parts[2]) if len(parts) > 2 else 0
    limit = 6

    category_title = "🪪 Знайдені документи" if category == "document" else "🎒 Знайдені особисті речі"
    result = await lost_items_service.get_active_items(category=category, limit=limit, offset=offset)
    items = result["items"]
    total_count = result["total_count"]
    has_prev = result["has_prev"]
    has_next = result["has_next"]

    if not items:
        empty_text = (
            f"🔍 <b>{category_title}</b>\n\n"
            "Наразі на зберіганні в Інформаційному центрі немає зареєстрованих знахідок у цій категорії. "
            "Якщо ви нещодавно загубили річ, зверніться за телефоном <code>048-717-54-54</code>."
        )
        empty_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ До вибору категорії", callback_data="lost_items")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
        ])
        await query.edit_message_text(text=empty_text, reply_markup=empty_markup, parse_mode=ParseMode.HTML)
        return

    lines = [
        f"🔍 <b>{category_title} на зберіганні</b>\n",
        f"Всього знахідок: <b>{total_count}</b>\n",
        "Для отримання зверніться до Інфоцентру з документом, що посвідчує особу:\n"
    ]

    for index, item in enumerate(items, start=offset + 1):
        lines.append(f"<b>{index}. {item.title}</b>\n")

    message_text = "\n".join(lines)

    keyboard = []
    nav_row = []
    if has_prev:
        prev_offset = max(0, offset - limit)
        nav_row.append(InlineKeyboardButton("⬅️ Попередня", callback_data=f"lost_items_cat:{category}:{prev_offset}"))
    if has_next:
        next_offset = offset + limit
        nav_row.append(InlineKeyboardButton("Наступна ➡️", callback_data=f"lost_items_cat:{category}:{next_offset}"))

    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("⬅️ До вибору категорії", callback_data="lost_items")])
    keyboard.append([InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from services.news_service import NewsService, format_kyiv_time
from utils.logger import logger

news_service = NewsService()


async def clean_media_messages(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Видаляє попередні медіа-повідомлення, збережені в context.user_data"""
    if "media_message_ids" not in context.user_data:
        return

    for msg_id in context.user_data["media_message_ids"]:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as error:
            logger.debug(f"Could not delete media message {msg_id}: {error}")
    del context.user_data["media_message_ids"]


async def news_client_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Відображає список актуальних новин для користувачів бота.
    Callback data: news_client_list:<offset>
    """
    query = update.callback_query
    if query:
        await query.answer()

    chat_id = update.effective_chat.id
    await clean_media_messages(chat_id=chat_id, context=context)

    offset = 0
    if query and query.data and ":" in query.data:
        try:
            offset = int(query.data.split(":")[1])
        except (ValueError, IndexError):
            offset = 0

    limit = 5
    result = await news_service.get_active_news(limit=limit, offset=offset)
    items = result["items"]
    total_count = result["total_count"]
    has_more = result["has_more"]

    if not items:
        empty_text = (
            "📢 <b>Оперативні новини</b>\n\n"
            "Наразі немає активних повідомлень або змін у русі транспорту. "
            "Міський електротранспорт працює у штатному режимі. 🚊"
        )
        empty_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
        ])

        if query and query.message:
            try:
                await query.edit_message_text(empty_text, reply_markup=empty_markup, parse_mode=ParseMode.HTML)
                return
            except Exception:
                pass

        await context.bot.send_message(
            chat_id=chat_id,
            text=empty_text,
            reply_markup=empty_markup,
            parse_mode=ParseMode.HTML
        )
        return

    header_text = (
        "📢 <b>Оперативні новини та зміни руху</b>\n\n"
        f"Знайдено актуальних повідомлень: <b>{total_count}</b>\n"
        "Оберіть новину нижче для детального перегляду:"
    )

    keyboard: list[list[InlineKeyboardButton]] = []

    for news in items:
        created_time = format_kyiv_time(news.created_at)
        preview_text = (news.text or "").strip().replace("\n", " ")
        if len(preview_text) > 32:
            preview_text = preview_text[:30] + ".."
        elif not preview_text:
            preview_text = "📸 Медіаматеріал"

        button_label = f"📅 {created_time}: {preview_text}"
        keyboard.append([
            InlineKeyboardButton(button_label, callback_data=f"news_client_view:{news.id}:{offset}")
        ])

    nav_row: list[InlineKeyboardButton] = []
    if offset > 0:
        prev_offset = max(0, offset - limit)
        nav_row.append(InlineKeyboardButton("⬅️ Попередня", callback_data=f"news_client_list:{prev_offset}"))
    if has_more:
        next_offset = offset + limit
        nav_row.append(InlineKeyboardButton("Наступна ➡️", callback_data=f"news_client_list:{next_offset}"))

    if nav_row:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query and query.message:
        try:
            await query.edit_message_text(header_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            return
        except Exception:
            pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=header_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )


async def news_client_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Відображає детальну картку новини для пасажира.
    Callback data: news_client_view:<news_id>:<offset>
    """
    query = update.callback_query
    if not query:
        return
    await query.answer()

    chat_id = update.effective_chat.id
    await clean_media_messages(chat_id=chat_id, context=context)

    parts = query.data.split(":")
    news_id = int(parts[1]) if len(parts) > 1 else 0
    offset = int(parts[2]) if len(parts) > 2 else 0

    news = await news_service.get_news_by_id(news_id)
    if not news or not news.is_active:
        not_found_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ До новин", callback_data=f"news_client_list:{offset}")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
        ])
        await query.edit_message_text(
            "⚠️ <b>Ця новина застаріла або була прихована модератором.</b>",
            reply_markup=not_found_markup,
            parse_mode=ParseMode.HTML
        )
        return

    created_time = format_kyiv_time(news.created_at)
    content_text = news.text or "<i>(Оголошення без додаткового тексту)</i>"
    detail_message = (
        f"📢 <b>Оперативна новина</b>\n"
        f"📅 Опубліковано: <b>{created_time}</b>\n\n"
        f"{content_text}"
    )

    back_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ До списку новин", callback_data=f"news_client_list:{offset}")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
    ])

    # Якщо новина містить медіа (фото/відео)
    if news.media_type and news.media_file_id:
        try:
            await query.message.delete()
        except Exception:
            pass

        caption = detail_message
        if len(caption) > 1024:
            caption = caption[:1020] + "..."

        if news.media_type == "photo":
            sent_media = await context.bot.send_photo(
                chat_id=chat_id,
                photo=news.media_file_id,
                caption=caption,
                reply_markup=back_markup,
                parse_mode=ParseMode.HTML
            )
            context.user_data["media_message_ids"] = [sent_media.message_id]
            return
        elif news.media_type == "video":
            sent_media = await context.bot.send_video(
                chat_id=chat_id,
                video=news.media_file_id,
                caption=caption,
                reply_markup=back_markup,
                parse_mode=ParseMode.HTML
            )
            context.user_data["media_message_ids"] = [sent_media.message_id]
            return

    # Звичайне текстове повідомлення
    try:
        await query.edit_message_text(
            text=detail_message,
            reply_markup=back_markup,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        await context.bot.send_message(
            chat_id=chat_id,
            text=detail_message,
            reply_markup=back_markup,
            parse_mode=ParseMode.HTML
        )

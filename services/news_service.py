import datetime
import re
from typing import Optional, Any
from zoneinfo import ZoneInfo
from sqlalchemy import select, update, func
from database.db import AsyncSessionLocal, NewsItem
from utils.logger import logger

KYIV_TIMEZONE = ZoneInfo("Europe/Kyiv")


def _split_into_sentences(text_fragment: str) -> list[str]:
    """Розбиває фрагмент тексту на речення, захищаючи типові скорочення від хибного розриву."""
    # Маскуємо крапку у типових скороченнях (включаючи лапки або дужки перед ними)
    masked = re.sub(
        r'([«"\'(\s]|^)(вул|просп|пров|бульв|ім|пл|м|с|р|№)\.',
        r'\1\2@',
        text_fragment,
        flags=re.IGNORECASE
    )
    return [s.replace('@', '.').strip() for s in re.split(r'(?<=[.!?…])\s+', masked) if s.strip()]


def extract_news_title(text: Optional[str], max_chars: int = 140) -> str:
    """
    Автоматично вилучає заголовок для оперативного сповіщення.
    Пріоритет:
    1. Перший рядок (абзац), якщо він є самостійною назвою (20..max_chars).
    2. Якщо перший рядок занадто короткий (< 20 симв., наприклад "Увага!"), поєднує його з 1-м реченням наступного рядка.
    3. Якщо рядок або текст довгий, бере перше речення з маскуванням скорочень (вул., просп., тощо).
    4. Якщо заголовок все одно перевищує max_chars, м'яко скорочує по межі слів з '...'.
    """
    if not text:
        return "Оперативні зміни в роботі електротранспорту"

    clean = re.sub(r'<[^>]+>', '', text).strip()
    if not clean:
        return "Оперативні зміни в роботі електротранспорту"

    # Розбиваємо на непорожні рядки
    lines = [line.strip() for line in clean.split('\n') if line.strip()]
    if not lines:
        return "Оперативні зміни в роботі електротранспорту"

    first_line = lines[0]

    # ПРАВИЛО 1: Перший рядок є готовим заголовком нормальної довжини (20..max_chars)
    if 20 <= len(first_line) <= max_chars:
        line_sentences = _split_into_sentences(first_line)
        if len(line_sentences) > 1 and len(line_sentences[0]) >= 20:
            return line_sentences[0]
        return first_line

    # ПРАВИЛО 2: Перший рядок занадто короткий (< 20 симв., наприклад "Увага!" або "❗️ ВАЖЛИВО")
    if len(first_line) < 20 and len(lines) > 1:
        second_line = lines[1]
        second_sentences = _split_into_sentences(second_line)
        first_sentence = second_sentences[0] if second_sentences else second_line

        combined = f"{first_line} {first_sentence}"
        if len(combined) <= max_chars:
            return combined
        first_line = combined

    # ПРАВИЛО 3: Перший рядок довший за max_chars — беремо перше речення
    sentences = _split_into_sentences(first_line)
    target = sentences[0] if sentences else first_line

    if len(sentences) > 1 and len(target) < 20:
        combined = f"{target} {sentences[1]}"
        if len(combined) <= max_chars:
            target = combined

    if len(target) <= max_chars:
        return target

    # ПРАВИЛО 4: Обрізання по межі цілих слів
    truncated = target[:max_chars - 3]
    last_space = truncated.rfind(' ')
    if last_space > 30:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "..."


def to_kyiv_datetime(dt_value: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """Конвертує UTC час у київський часовий пояс"""
    if dt_value is None:
        return None
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=datetime.timezone.utc)
    return dt_value.astimezone(KYIV_TIMEZONE)


def format_kyiv_time(dt_value: Optional[datetime.datetime]) -> str:
    """Форматує дату та час для відображення в інтерфейсі (ДД.ММ.РРРР ГГ:ХХ)"""
    kyiv_dt = to_kyiv_datetime(dt_value)
    if kyiv_dt is None:
        return "Невідомо"
    return kyiv_dt.strftime("%d.%m.%Y %H:%M")


class NewsService:
    """Сервіс для роботи з оперативними новинами та архівом розсилок"""

    def __init__(self):
        self.session_factory = AsyncSessionLocal

    async def save_broadcast_news(self, params: dict[str, Any]) -> NewsItem:
        """
        Зберігає нове повідомлення розсилки як активну новину.
        RORO: приймає params, повертає об'єкт NewsItem.
        """
        admin_id = params.get("admin_id")
        if not admin_id:
            raise ValueError("admin_id is required to save broadcast news")

        async with self.session_factory() as session:
            news = NewsItem(
                admin_id=admin_id,
                admin_name=params.get("admin_name", "Адміністратор"),
                title=params.get("title"),
                text=params.get("text", ""),
                media_type=params.get("media_type"),
                media_file_id=params.get("media_file_id"),
                is_active=True,
                sent_count=params.get("sent_count", 0),
                blocked_count=params.get("blocked_count", 0),
                expires_at=params.get("expires_at")
            )
            session.add(news)
            await session.commit()
            await session.refresh(news)
            logger.info(f"News created: id={news.id} by admin_id={admin_id}")
            return news

    async def update_broadcast_stats(self, news_id: int, sent_count: int, blocked_count: int) -> None:
        """Оновлює кількість доставлених повідомлень та блокувань після розсилки"""
        async with self.session_factory() as session:
            await session.execute(
                update(NewsItem)
                .where(NewsItem.id == news_id)
                .values(sent_count=sent_count, blocked_count=blocked_count)
            )
            await session.commit()
            logger.info(f"News id={news_id} stats updated: sent={sent_count}, blocked={blocked_count}")

    async def get_active_news(self, limit: int = 5, offset: int = 0) -> dict[str, Any]:
        """
        Отримує перелік актуальних новин для пасажирів (is_active == True).
        RORO: повертає словник з items, total_count, has_more, offset.
        """
        async with self.session_factory() as session:
            count_query = select(func.count(NewsItem.id)).where(NewsItem.is_active.is_(True))
            total_count_res = await session.execute(count_query)
            total_count = total_count_res.scalar() or 0

            if total_count == 0:
                return {
                    "items": [],
                    "total_count": 0,
                    "has_more": False,
                    "offset": offset
                }

            query = (
                select(NewsItem)
                .where(NewsItem.is_active.is_(True))
                .order_by(NewsItem.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(query)
            items = list(result.scalars().all())

            has_more = (offset + len(items)) < total_count
            return {
                "items": items,
                "total_count": total_count,
                "has_more": has_more,
                "offset": offset
            }

    async def get_news_by_id(self, news_id: int) -> Optional[NewsItem]:
        """Отримує новину за її ідентифікатором"""
        async with self.session_factory() as session:
            query = select(NewsItem).where(NewsItem.id == news_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def get_news_archive(self, limit: int = 7, offset: int = 0) -> dict[str, Any]:
        """
        Отримує повний архів новин для адміністраторів (всі записи з пагінацією).
        RORO: повертає словник з items, total_count, offset, limit, has_prev, has_next.
        """
        async with self.session_factory() as session:
            count_query = select(func.count(NewsItem.id))
            total_res = await session.execute(count_query)
            total_count = total_res.scalar() or 0

            if total_count == 0:
                return {
                    "items": [],
                    "total_count": 0,
                    "offset": offset,
                    "limit": limit,
                    "has_prev": False,
                    "has_next": False
                }

            query = (
                select(NewsItem)
                .order_by(NewsItem.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(query)
            items = list(result.scalars().all())

            return {
                "items": items,
                "total_count": total_count,
                "offset": offset,
                "limit": limit,
                "has_prev": offset > 0,
                "has_next": (offset + len(items)) < total_count
            }

    async def toggle_news_active(self, news_id: int) -> Optional[bool]:
        """
        Перемикає статус актуальності новини (True <-> False).
        Повертає новий статус is_active або None, якщо запис не знайдено.
        """
        async with self.session_factory() as session:
            query = select(NewsItem).where(NewsItem.id == news_id)
            result = await session.execute(query)
            news = result.scalar_one_or_none()

            if news is None:
                return None

            new_status = not news.is_active
            news.is_active = new_status
            if new_status:
                # Ручна реактивація знятої/простроченої новини: строк дії більше не обмежує її,
                # інакше найближча автоперевірка одразу знову прибере новину зі списку.
                news.expires_at = None
            await session.commit()
            logger.info(f"News id={news_id} is_active toggled to {new_status}")
            return new_status

    async def deactivate_expired_news(self) -> int:
        """
        Автоматично деактивує новини, строк дії яких сплив (expires_at <= now, is_active=True).
        Повертає кількість деактивованих записів.
        """
        async with self.session_factory() as session:
            now = datetime.datetime.utcnow()
            query = select(NewsItem).where(
                NewsItem.is_active.is_(True),
                NewsItem.expires_at.is_not(None),
                NewsItem.expires_at <= now
            )
            result = await session.execute(query)
            expired_items = list(result.scalars().all())

            if not expired_items:
                return 0

            for item in expired_items:
                item.is_active = False

            await session.commit()
            logger.info(f"Auto-expired {len(expired_items)} news item(s)")
            return len(expired_items)

import datetime
from typing import Optional, Any
from zoneinfo import ZoneInfo
from sqlalchemy import select, update, func
from database.db import AsyncSessionLocal, NewsItem
from utils.logger import logger

KYIV_TIMEZONE = ZoneInfo("Europe/Kyiv")


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

import datetime
from typing import Optional, Any
from zoneinfo import ZoneInfo
from sqlalchemy import select, update, delete, func
from database.db import AsyncSessionLocal, LostItem
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
    """Форматує дату та час (ДД.ММ.РРРР ГГ:ХХ)"""
    kyiv_dt = to_kyiv_datetime(dt_value)
    if kyiv_dt is None:
        return "Невідомо"
    return kyiv_dt.strftime("%d.%m.%Y %H:%M")


def format_kyiv_date(dt_value: Optional[datetime.datetime]) -> str:
    """Форматує лише дату (ДД.ММ.РРРР)"""
    kyiv_dt = to_kyiv_datetime(dt_value)
    if kyiv_dt is None:
        return "Невідомо"
    return kyiv_dt.strftime("%d.%m.%Y")


class LostItemsService:
    """Сервіс для роботи зі знайденими документами та речами"""

    def __init__(self):
        self.session_factory = AsyncSessionLocal

    async def create_lost_item(self, params: dict[str, Any]) -> LostItem:
        """
        Створює новий запис про знайдену річ або документ.
        RORO: приймає params dict, повертає об'єкт LostItem.
        """
        title = (params.get("title") or "").strip()
        if not title:
            raise ValueError("title is required to create lost item")

        category = params.get("category", "thing")
        if category not in ("document", "thing"):
            category = "thing"

        admin_id = params.get("admin_id", 0)

        async with self.session_factory() as session:
            item = LostItem(
                admin_id=admin_id,
                admin_name=params.get("admin_name", "Адміністратор"),
                category=category,
                title=title,
                details=params.get("details"),
                status="active"
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            logger.info(f"LostItem created: id={item.id}, cat={category}, title='{title}'")
            return item

    async def get_active_items(self, category: str, limit: int = 6, offset: int = 0) -> dict[str, Any]:
        """
        Отримує активні речі для пасажирів за категорією ('document' або 'thing').
        RORO: повертає {items, total_count, has_prev, has_next, offset, limit}.
        """
        async with self.session_factory() as session:
            count_query = (
                select(func.count(LostItem.id))
                .where(LostItem.status == "active", LostItem.category == category)
            )
            total_res = await session.execute(count_query)
            total_count = total_res.scalar() or 0

            if total_count == 0:
                return {
                    "items": [],
                    "total_count": 0,
                    "has_prev": False,
                    "has_next": False,
                    "offset": offset,
                    "limit": limit
                }

            query = (
                select(LostItem)
                .where(LostItem.status == "active", LostItem.category == category)
                .order_by(LostItem.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(query)
            items = list(result.scalars().all())

            return {
                "items": items,
                "total_count": total_count,
                "has_prev": offset > 0,
                "has_next": (offset + len(items)) < total_count,
                "offset": offset,
                "limit": limit
            }

    async def get_item_by_id(self, item_id: int) -> Optional[LostItem]:
        """Отримує запис за ID"""
        async with self.session_factory() as session:
            query = select(LostItem).where(LostItem.id == item_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def mark_as_returned(self, item_id: int) -> Optional[bool]:
        """
        Позначає знахідку як повернену власнику (status='returned').
        Повертає True, якщо оновлено, або None, якщо не знайдено.
        """
        async with self.session_factory() as session:
            query = select(LostItem).where(LostItem.id == item_id)
            result = await session.execute(query)
            item = result.scalar_one_or_none()

            if item is None:
                return None

            item.status = "returned"
            item.returned_at = datetime.datetime.now(datetime.timezone.utc)
            await session.commit()
            logger.info(f"LostItem id={item_id} marked as returned")
            return True

    async def get_admin_items(
        self,
        status: str = "active",
        category: Optional[str] = None,
        limit: int = 7,
        offset: int = 0
    ) -> dict[str, Any]:
        """
        Отримує список знахідок для панелі адміністратора з пагінацією.
        """
        async with self.session_factory() as session:
            conditions = [LostItem.status == status]
            if category:
                conditions.append(LostItem.category == category)

            count_query = select(func.count(LostItem.id)).where(*conditions)
            total_res = await session.execute(count_query)
            total_count = total_res.scalar() or 0

            if total_count == 0:
                return {
                    "items": [],
                    "total_count": 0,
                    "has_prev": False,
                    "has_next": False,
                    "offset": offset,
                    "limit": limit
                }

            order_clause = LostItem.returned_at.desc() if status == "returned" else LostItem.created_at.desc()
            query = (
                select(LostItem)
                .where(*conditions)
                .order_by(order_clause)
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(query)
            items = list(result.scalars().all())

            return {
                "items": items,
                "total_count": total_count,
                "has_prev": offset > 0,
                "has_next": (offset + len(items)) < total_count,
                "offset": offset,
                "limit": limit
            }

    async def update_lost_item(
        self,
        item_id: int,
        title: Optional[str] = None,
        details: Optional[str] = None
    ) -> Optional[bool]:
        """
        Оновлює назву та/або деталі вже створеного запису (виправлення помилки без видалення).
        Повертає True, якщо оновлено, або None, якщо запис не знайдено.
        """
        async with self.session_factory() as session:
            query = select(LostItem).where(LostItem.id == item_id)
            result = await session.execute(query)
            item = result.scalar_one_or_none()

            if item is None:
                return None

            if title is not None:
                item.title = title
            if details is not None:
                item.details = details

            await session.commit()
            logger.info(f"LostItem id={item_id} updated (title_changed={title is not None}, details_changed={details is not None})")
            return True

    async def delete_lost_item(self, item_id: int) -> bool:
        """Видаляє запис із бази даних"""
        async with self.session_factory() as session:
            query = select(LostItem).where(LostItem.id == item_id)
            result = await session.execute(query)
            item = result.scalar_one_or_none()

            if item is None:
                return False

            await session.delete(item)
            await session.commit()
            logger.info(f"LostItem id={item_id} deleted from DB")
            return True

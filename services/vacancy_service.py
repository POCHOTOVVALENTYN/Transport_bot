from typing import Optional, Any
from sqlalchemy import select, func
from database.db import AsyncSessionLocal, Vacancy
from utils.logger import logger


class VacancyService:
    """Сервіс для керування вакансіями (розділ 'Про підприємство' → 'Вакансії')."""

    def __init__(self):
        self.session_factory = AsyncSessionLocal

    async def create_vacancy(self, params: dict[str, Any]) -> Vacancy:
        """
        Створює нову вакансію.
        RORO: приймає params dict, повертає об'єкт Vacancy.
        """
        title = (params.get("title") or "").strip()
        if not title:
            raise ValueError("title is required to create vacancy")

        category = params.get("category", "experienced")
        if category not in ("experienced", "trainee"):
            category = "experienced"

        contact_type = params.get("contact_type", "url")
        if contact_type not in ("url", "phone"):
            contact_type = "url"

        contact_value = (params.get("contact_value") or "").strip()
        if not contact_value:
            raise ValueError("contact_value is required to create vacancy")

        async with self.session_factory() as session:
            # Наступний sort_order у межах категорії (щоб нові вакансії йшли в кінець списку)
            max_order_res = await session.execute(
                select(func.max(Vacancy.sort_order)).where(Vacancy.category == category)
            )
            max_order = max_order_res.scalar() or 0

            vacancy = Vacancy(
                admin_id=params.get("admin_id", 0),
                admin_name=params.get("admin_name", "Адміністратор"),
                category=category,
                title=title,
                contact_type=contact_type,
                contact_value=contact_value,
                sort_order=max_order + 1,
                is_active=True
            )
            session.add(vacancy)
            await session.commit()
            await session.refresh(vacancy)
            logger.info(f"Vacancy created: id={vacancy.id}, cat={category}, title='{title}'")
            return vacancy

    async def get_active_vacancies(self, category: str) -> list[Vacancy]:
        """
        Отримує активні вакансії за категорідюю ('experienced' або 'trainee') для клієнтського менюю.
        Впорядковано за sort_order, потім за id.
        """
        async with self.session_factory() as session:
            query = (
                select(Vacancy)
                .where(Vacancy.category == category, Vacancy.is_active == True)  # noqa: E712
                .order_by(Vacancy.sort_order.asc(), Vacancy.id.asc())
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_admin_vacancies(
        self,
        category: Optional[str] = None,
        active_only: bool = True,
        limit: int = 10,
        offset: int = 0
    ) -> dict[str, Any]:
        """
        Отримує список вакансій для адмін-панелі з пагінацією.
        RORO: повертає {items, total_count, has_prev, has_next, offset, limit}.
        """
        async with self.session_factory() as session:
            conditions = []
            if category:
                conditions.append(Vacancy.category == category)
            if active_only:
                conditions.append(Vacancy.is_active == True)  # noqa: E712

            count_query = select(func.count(Vacancy.id)).where(*conditions)
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
                select(Vacancy)
                .where(*conditions)
                .order_by(Vacancy.category.asc(), Vacancy.sort_order.asc(), Vacancy.id.asc())
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

    async def get_vacancy_by_id(self, vacancy_id: int) -> Optional[Vacancy]:
        """Отримує вакансію за ID."""
        async with self.session_factory() as session:
            query = select(Vacancy).where(Vacancy.id == vacancy_id)
            result = await session.execute(query)
            return result.scalar_one_or_none()

    async def deactivate_vacancy(self, vacancy_id: int) -> Optional[bool]:
        """
        Деактивує вакансію (soft-delete: is_active=False). Історія зберігається в БД.
        Повертає True, якщо оновлено, або None, якщо не знайдено.
        """
        async with self.session_factory() as session:
            query = select(Vacancy).where(Vacancy.id == vacancy_id)
            result = await session.execute(query)
            vacancy = result.scalar_one_or_none()

            if vacancy is None:
                return None

            vacancy.is_active = False
            await session.commit()
            logger.info(f"Vacancy id={vacancy_id} deactivated")
            return True

    async def reactivate_vacancy(self, vacancy_id: int) -> Optional[bool]:
        """Повертає раніше деактивовану вакансію в активний списоъ."""
        async with self.session_factory() as session:
            query = select(Vacancy).where(Vacancy.id == vacancy_id)
            result = await session.execute(query)
            vacancy = result.scalar_one_or_none()

            if vacancy is None:
                return None

            vacancy.is_active = True
            await session.commit()
            logger.info(f"Vacancy id={vacancy_id} reactivated")
            return True

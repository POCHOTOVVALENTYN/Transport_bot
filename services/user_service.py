# services/user_service.py
from sqlalchemy import select, func, update
from database.db import AsyncSessionLocal, BotUser
from utils.logger import logger


class UserService:
    async def register_user(self, user_data):
        """Зберігає користувача (якщо новий)"""
        telegram_id = user_data.id
        username = user_data.username
        first_name = user_data.first_name

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
            existing_user = result.scalar_one_or_none()

            if not existing_user:
                # За замовчуванням підписка False (добровільна)
                new_user = BotUser(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                    is_subscribed=False
                )
                session.add(new_user)
                logger.info(f"👤 New user registered: {telegram_id}")
            else:
                existing_user.username = username
                existing_user.first_name = first_name

            await session.commit()

    async def set_subscription(self, telegram_id: int, is_subscribed: bool):
        """Змінює статус підписки користувача"""
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(BotUser)
                .where(BotUser.telegram_id == telegram_id)
                .values(is_subscribed=is_subscribed)
            )
            await session.commit()

    async def get_subscribed_users_ids(self):
        """Повертає ID ТІЛЬКИ підписаних користувачів"""
        async with AsyncSessionLocal() as session:
            # Фільтруємо по is_subscribed == True
            result = await session.execute(select(BotUser.telegram_id).where(BotUser.is_subscribed == True))
            return result.scalars().all()

    async def get_stats(self):
        """Статистика для адміна"""
        async with AsyncSessionLocal() as session:
            total = await session.scalar(select(func.count(BotUser.id)))
            subscribed = await session.scalar(select(func.count(BotUser.id)).where(BotUser.is_subscribed == True))
            return {"total_users": total, "subscribed_users": subscribed}
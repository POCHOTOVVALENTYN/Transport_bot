# services/user_service.py
from sqlalchemy import select, func
from database.db import AsyncSessionLocal, BotUser
from utils.logger import logger


class UserService:
    async def register_user(self, user_data):
        """Зберігає або оновлює користувача в БД при команді /start"""
        telegram_id = user_data.id
        username = user_data.username
        first_name = user_data.first_name

        async with AsyncSessionLocal() as session:
            # Перевіряємо, чи є такий юзер
            result = await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
            existing_user = result.scalar_one_or_none()

            if not existing_user:
                # Створюємо нового
                new_user = BotUser(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name
                )
                session.add(new_user)
                logger.info(f"👤 New user registered: {telegram_id}")
            else:
                # Оновлюємо дані (якщо змінив нікнейм)
                existing_user.username = username
                existing_user.first_name = first_name

            await session.commit()

    async def get_all_users_ids(self):
        """Повертає список ID всіх користувачів для розсилки"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(BotUser.telegram_id))
            return result.scalars().all()

    async def get_stats(self):
        """Повертає статистику: всього юзерів, нових за сьогодні"""
        async with AsyncSessionLocal() as session:
            total = await session.scalar(select(func.count(BotUser.id)))
            return {"total_users": total}
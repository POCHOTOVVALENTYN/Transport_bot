import asyncio
import uuid
import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, DateTime, func, Boolean, BigInteger, select, update, Index, text
from config.settings import DATABASE_URL
from sqlalchemy.exc import OperationalError

Base = declarative_base()

# --- Налаштування підключення ---
# КРИТИЧНО: Використовуємо DATABASE_URL з config/settings.py
# Але перевіряємо, чи він правильний для Docker
print(f"🔗 DATABASE_URL: {DATABASE_URL}")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Створює таблиці, якщо їх немає, з механізмом очікування"""
    retries = 10
    while retries > 0:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_feedbacks_status ON feedbacks(status)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_feedbacks_created_at ON feedbacks(created_at)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_telegram_id ON users(telegram_id)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_is_subscribed ON users(is_subscribed)"))
            print("✅ Database tables initialized successfully")
            return  # Успіх, виходимо
        except (OSError, OperationalError) as e:
            # OSError 111 - це Connection Refused
            retries -= 1
            print(f"⏳ БД ще не готова ({e}). Чекаємо 3 секунди... (Залишилось спроб: {retries})")
            await asyncio.sleep(3)

    # Якщо спроби скінчились
    raise Exception("❌ Не вдалося підключитися до БД після багатьох спроб")


# ================= МОДЕЛІ (ТАБЛИЦІ) =================

# --- 1. Таблиця записів до Музею ---
class MuseumBooking(Base):
    __tablename__ = "museum_bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now())
    excursion_date = Column(String, nullable=False)
    people_count = Column(Integer, nullable=False)
    user_name = Column(String, nullable=False)
    user_phone = Column(String, nullable=False)
    status = Column(String, default="new")


class MuseumHolidayBooking(Base):
    __tablename__ = "museum_holiday_bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now())
    excursion_date = Column(String, nullable=False)
    people_count = Column(Integer, nullable=False)
    user_name = Column(String, nullable=False)
    user_phone = Column(String, nullable=False)
    status = Column(String, default="new")



# --- 2. Таблиця Користувачів (для розсилки та статистики) ---
class BotUser(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    first_name = Column(String, nullable=True)
    username = Column(String, nullable=True)
    joined_at = Column(DateTime, default=func.now())
    is_subscribed = Column(Boolean, default=False)  # Підписка на новини


# --- 3. Єдина таблиця для Зворотного зв'язку (Скарги, Подяки, Пропозиції) ---
class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now())
    ticket_id = Column(String, unique=True)  # Унікальний номер звернення

    category = Column(String)  # "Скарги", "Пропозиції", "Подяки"
    status = Column(String, default="new")  # "new" (в базі), "synced" (в гугл таблиці)

    # Дані користувача
    user_id = Column(BigInteger, nullable=False)
    user_name = Column(String, nullable=True)
    user_phone = Column(String, nullable=True)
    user_email = Column(String, nullable=True)

    # Основний вміст
    text = Column(String, nullable=True)

    # Поля для транспорту (спільні для всіх)
    route = Column(String, nullable=True)
    board_number = Column(String, nullable=True)

    # --- НОВІ ПОЛЯ ДЛЯ ПОДЯК (V2) ---
    thanks_type = Column(String, nullable=True)  # "specific" або "general"
    transport_type = Column(String, nullable=True)  # "tram" або "trolleybus"
    driver_name = Column(String, nullable=True)  # ПІБ водія/кондуктора
    reason = Column(String, nullable=True)  # За що вдячні


# --- Індекси ---
Index("ix_feedbacks_status", Feedback.status)
Index("ix_feedbacks_created_at", Feedback.created_at)
Index("ix_users_telegram_id", BotUser.telegram_id)
Index("ix_users_is_subscribed", BotUser.is_subscribed)


# ================= ГОЛОВНИЙ КЛАС DATABASE =================

class Database:
    def __init__(self):
        self.session_factory = AsyncSessionLocal

    # --- Робота з користувачами ---
    async def add_user(self, telegram_id: int, first_name: str, username: str):
        """Додає користувача, якщо його ще немає в базі."""
        async with self.session_factory() as session:
            result = await session.execute(select(BotUser).where(BotUser.telegram_id == telegram_id))
            user = result.scalar_one_or_none()

            if not user:
                new_user = BotUser(
                    telegram_id=telegram_id,
                    first_name=first_name,
                    username=username,
                    is_subscribed=True  # За замовчуванням підписуємо
                )
                session.add(new_user)
                await session.commit()
                return True
            return False

    # --- Робота зі зворотним зв'язком (Скарги/Подяки/Пропозиції) ---
    async def create_feedback(self, data: dict) -> str:
        """
        Створює запис у таблиці Feedback.
        Повертає згенерований ticket_id.

        :param data: Словник з полями для Feedback
        :return: ticket_id
        """
        # Генеруємо гарний ID: THX-YYYYMMDD-XXXX
        date_str = datetime.datetime.now().strftime("%Y%m%d")
        short_uuid = str(uuid.uuid4())[:5].upper()
        prefix = "FB"  # Feedback

        # Змінюємо префікс в залежності від категорії
        category = data.get('category', 'Інше')
        if category == 'Подяки':
            prefix = "THX"
        elif category == 'Скарги':
            prefix = "CMP"
        elif category == 'Пропозиції':
            prefix = "SUG"

        ticket_id = f"{prefix}-{date_str}-{short_uuid}"

        async with self.session_factory() as session:
            feedback = Feedback(
                ticket_id=ticket_id,
                category=category,
                text=data.get('text'),
                route=data.get('route'),
                board_number=data.get('board_number'),
                user_id=data.get('user_id'),
                user_name=data.get('user_name'),
                user_phone=data.get('user_phone'),
                user_email=data.get('user_email'),
                thanks_type=data.get('thanks_type'),
                transport_type=data.get('transport_type'),
                driver_name=data.get('driver_name'),
                reason=data.get('reason'),
                status="new"
            )
            session.add(feedback)
            await session.commit()
            return ticket_id

    async def get_unsynced_feedbacks(self):
        """Отримує всі записи, які ще не відправлені в Гугл Таблиці."""
        async with self.session_factory() as session:
            result = await session.execute(select(Feedback).where(Feedback.status == "new"))
            return result.scalars().all()

    async def mark_feedback_synced(self, feedback_id: int):
        """Позначає запис як синхронізований."""
        async with self.session_factory() as session:
            await session.execute(
                update(Feedback).where(Feedback.id == feedback_id).values(status="synced")
            )
            await session.commit()

    # --- Робота з музеєм ---
    async def create_museum_booking(self, data: dict):
        async with self.session_factory() as session:
            booking = MuseumBooking(
                excursion_date=data.get('date'),
                people_count=int(data.get('people', 1)),
                user_name=data.get('name'),
                user_phone=data.get('phone'),
                status="new"
            )
            session.add(booking)
            await session.commit()
            return booking.id

    async def create_museum_holiday_booking(self, data: dict):
        async with self.session_factory() as session:
            booking = MuseumHolidayBooking(
                excursion_date=data.get('date'),
                people_count=int(data.get('people', 1)),
                user_name=data.get('name'),
                user_phone=data.get('phone'),
                status="new"
            )
            session.add(booking)
            await session.commit()
            return booking.id
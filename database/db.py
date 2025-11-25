import asyncio
import uuid
import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, DateTime, func, Boolean, BigInteger, select, update
from config.settings import DATABASE_URL

Base = declarative_base()

# --- Налаштування підключення ---
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Створює таблиці, якщо їх немає"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
    username = Column(String, nullable=True)

    # Зміст
    text = Column(String, nullable=True)

    # Специфічні поля (для транспорту)
    route = Column(String, nullable=True)
    board_number = Column(String, nullable=True)


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
        """
        # Генеруємо гарний ID: TICKET-YYYYMMDD-XXXX
        date_str = datetime.datetime.now().strftime("%Y%m%d")
        short_uuid = str(uuid.uuid4())[:5].upper()
        prefix = "FB"  # Feedback

        # Якщо це подяка, можна змінити префікс, але не обов'язково
        if data.get('category') == 'Подяки':
            prefix = "THX"
        elif data.get('category') == 'Скарги':
            prefix = "CMP"

        ticket_id = f"{prefix}-{date_str}-{short_uuid}"

        async with self.session_factory() as session:
            feedback = Feedback(
                ticket_id=ticket_id,
                category=data.get('category', 'Інше'),
                text=data.get('text'),
                route=data.get('route'),
                board_number=data.get('board'),
                user_id=data.get('user_id'),
                user_name=data.get('name'),
                username=data.get('username'),
                user_phone=data.get('phone'),
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
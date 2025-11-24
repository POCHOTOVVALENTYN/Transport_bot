# database/db.py
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, DateTime, func, Boolean
from config.settings import BASE_DIR
from sqlalchemy import Column, Integer, String, DateTime, func, BigInteger # <-- Додали BigInteger
from config.settings import DATABASE_URL


Base = declarative_base()

# --- Опис таблиці записів до Музею ---
class MuseumBooking(Base):
    __tablename__ = "museum_bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now())
    excursion_date = Column(String, nullable=False) # Дата екскурсії
    people_count = Column(Integer, nullable=False)
    user_name = Column(String, nullable=False)
    user_phone = Column(String, nullable=False)
    status = Column(String, default="new") # new, synced_to_sheets

# --- Налаштування підключення ---
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    """Створює таблиці, якщо їх немає"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)



class Complaint(Base):
    __tablename__ = "complaints"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now())
    ticket_id = Column(String, unique=True)
    problem_text = Column(String)
    route = Column(String)
    board_number = Column(String)
    user_contact = Column(String)
    status = Column(String, default="new") # new, synced


# --- 1. Таблиця Користувачів (для розсилки та статистики) ---
class BotUser(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    first_name = Column(String, nullable=True)
    username = Column(String, nullable=True)
    joined_at = Column(DateTime, default=func.now())
    # НОВЕ ПОЛЕ: Підписка на новини
    is_subscribed = Column(Boolean, default=False)


# --- 2. Єдина таблиця для Зворотного зв'язку (Скарги, Подяки, Пропозиції) ---
class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now())
    ticket_id = Column(String, unique=True)

    category = Column(String)  # "complaint", "suggestion", "thanks"
    status = Column(String, default="new")  # "new" (в базі), "synced" (в гугл таблиці)

    # Спільні поля
    text = Column(String, nullable=True)
    user_id = Column(BigInteger, nullable=False)
    user_name = Column(String, nullable=True)
    user_phone = Column(String, nullable=True)
    user_email = Column(String, nullable=True)

    # Специфічні поля (для транспорту)
    route = Column(String, nullable=True)
    board_number = Column(String, nullable=True)
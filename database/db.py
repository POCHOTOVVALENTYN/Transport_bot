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
                # Перевіримо та додамо колонку email_status у таблицю feedbacks, якщо її немає
                try:
                    await conn.execute(text("ALTER TABLE feedbacks ADD COLUMN email_status VARCHAR DEFAULT 'pending'"))
                    print("✅ Migration: added email_status column to feedbacks")
                except Exception:
                    pass
                try:
                    await conn.execute(text("ALTER TABLE feedbacks ADD COLUMN need_response VARCHAR"))
                    print("✅ Migration: added need_response column to feedbacks")
                except Exception:
                    pass
                try:
                    await conn.execute(text("ALTER TABLE feedbacks ADD COLUMN home_address VARCHAR"))
                    print("✅ Migration: added home_address column to feedbacks")
                except Exception:
                    pass
                try:
                    await conn.execute(text("ALTER TABLE museum_holiday_bookings ADD COLUMN participants_details TEXT"))
                    print("✅ Migration: added participants_details column to museum_holiday_bookings")
                except Exception:
                    pass
                try:
                    await conn.execute(text("ALTER TABLE museum_bookings ADD COLUMN participants_details TEXT"))
                    print("✅ Migration: added participants_details column to museum_bookings")
                except Exception:
                    pass
                try:
                    await conn.execute(text("ALTER TABLE news ADD COLUMN expires_at DATETIME"))
                    print("✅ Migration: added expires_at column to news")
                except Exception:
                    pass
                try:
                    # Разова правка: вакансія "Електромонтер тягової підстанції" при сідінгу
                    # отримала чужий (скопійований) URL. Ідемпотентно: спрацює лише поки
                    # значення все ще хибне.
                    fix_res = await conn.execute(
                        text(
                            "UPDATE vacancies SET contact_value = :new_url "
                            "WHERE title = 'Електромонтер тягової підстанції' AND contact_value = :old_url"
                        ),
                        {
                            "new_url": "https://oget.od.ua/jobs/електромонтер-тягової-підстанції",
                            "old_url": "https://oget.od.ua/jobs/слюсар-електрик-з-ремонту-електроуст",
                        }
                    )
                    if fix_res.rowcount:
                        print("✅ Data fix: corrected contact_value for 'Електромонтер тягової підстанції'")
                except Exception:
                    pass
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_feedbacks_status ON feedbacks(status)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_feedbacks_created_at ON feedbacks(created_at)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_telegram_id ON users(telegram_id)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_is_subscribed ON users(is_subscribed)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_news_is_active ON news(is_active)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_news_created_at ON news(created_at)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lost_items_status ON lost_items(status)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lost_items_category ON lost_items(category)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_lost_items_created_at ON lost_items(created_at)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_vacancies_category ON vacancies(category)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_vacancies_is_active ON vacancies(is_active)"))

                # Початкове наповнення знайдених документів, якщо таблиця порожня
                try:
                    lost_count_res = await conn.execute(text("SELECT COUNT(*) FROM lost_items"))
                    lost_count = lost_count_res.scalar() or 0
                    if lost_count == 0:
                        initial_docs = [
                            "Пенсійне посвідчення — Шрамчук Лариса Володимирівна",
                            "Пенсійне посвідчення — Вовчук Людмила Артурівна",
                            "Посвідчення — Сирбул Анастасія Сергіївна",
                            "Пенсійне посвідчення — Мелкунян Наталія Петрівна",
                            "Паспорт — Бойцов Вадим Михайлович",
                            "Пакет документів — Поліщук Олександр",
                            "Пенсійне посвідчення — Жук Роза Василівна",
                            "Пенсійне посвідчення — Сімонов Юрій Ілліч",
                            "Пенсійне посвідчення — Тодорова Лариса Василівна",
                            "Пенсійне посвідчення — Петрова Наталія Михайлівна",
                            "Пенсійне посвідчення — Кара Наталія Миколаївна",
                            "Посвідчення — Стащенко Кіра Олександрівна / Олександр Євгенович"
                        ]
                        for doc in initial_docs:
                            await conn.execute(
                                text(
                                    "INSERT INTO lost_items (admin_id, admin_name, category, title, details, status) "
                                    "VALUES (0, 'Система', 'document', :title, 'Інформаційний центр (вул. Водопровідна, 1)', 'active')"
                                ),
                                {"title": doc}
                            )
                        print(f"✅ Seeding: додано {len(initial_docs)} початкових документів у lost_items")
                except Exception as seed_err:
                    print(f"⚠️ Seeding lost_items warning: {seed_err}")

                # Початкове наповнення вакансій, якщо таблиця порожня (перенесено зі старих хардкоджених словників)
                try:
                    vac_count_res = await conn.execute(text("SELECT COUNT(*) FROM vacancies"))
                    vac_count = vac_count_res.scalar() or 0
                    if vac_count == 0:
                        initial_vacancies = [
                            # (category, title, contact_type, contact_value, sort_order)
                            ("experienced", "Спеціаліст нарядник поїзних бригад", "phone", "+380751705557", 1),
                            ("experienced", "Зварювальник", "url", "https://oget.od.ua/jobs/зварювальник", 2),
                            ("experienced", "Слюсар з ремонту рухомого складу", "url", "https://oget.od.ua/jobs/слюсар-з-ремонту-рухомого-складу", 3),
                            ("experienced", "Електрогазозварник", "url", "https://oget.od.ua/jobs/електрогазозварник", 4),
                            ("experienced", "Електромонтер контактної/кабельної мережі", "url", "https://oget.od.ua/jobs/електромонтер-контактної-та-кабельн", 5),
                            ("experienced", "Електромонтер тягової підстанції", "url", "https://oget.od.ua/jobs/електромонтер-тягової-підстанції", 6),
                            ("experienced", "Слюсар-електрик з ремонту електроустаткування", "url", "https://oget.od.ua/jobs/слюсар-електрик-з-ремонту-електроуст-2", 7),
                            ("trainee", "👩‍💼 Кондуктор", "url", "https://oget.od.ua/jobs/кондуктор", 1),
                            ("trainee", "🧼 Мийник-прибиральник рухомого складу", "url", "https://oget.od.ua/jobs/мийник-прибиральник-рухомого-складу", 2),
                            ("trainee", "🛠️ Монтер колії 3 розряд", "url", "https://oget.od.ua/jobs/монтер-колії-234-розряд", 3),
                        ]
                        for category, title, contact_type, contact_value, sort_order in initial_vacancies:
                            await conn.execute(
                                text(
                                    "INSERT INTO vacancies (admin_id, admin_name, category, title, contact_type, contact_value, sort_order, is_active) "
                                    "VALUES (0, 'Система', :category, :title, :contact_type, :contact_value, :sort_order, 1)"
                                ),
                                {
                                    "category": category,
                                    "title": title,
                                    "contact_type": contact_type,
                                    "contact_value": contact_value,
                                    "sort_order": sort_order,
                                }
                            )
                        print(f"✅ Seeding: додано {len(initial_vacancies)} початкових вакансій у vacancies")
                except Exception as seed_err:
                    print(f"⚠️ Seeding vacancies warning: {seed_err}")
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
    participants_details = Column(String, nullable=True)
    status = Column(String, default="new")


class MuseumHolidayBooking(Base):
    __tablename__ = "museum_holiday_bookings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now())
    excursion_date = Column(String, nullable=False)
    people_count = Column(Integer, nullable=False)
    user_name = Column(String, nullable=False)
    user_phone = Column(String, nullable=False)
    participants_details = Column(String, nullable=True)
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
    email_status = Column(String, default="pending")  # "pending", "sent", "rejected"

    # Дані користувача
    user_id = Column(BigInteger, nullable=False)
    user_name = Column(String, nullable=True)
    user_phone = Column(String, nullable=True)
    user_email = Column(String, nullable=True)

    # Потреба відповіді та адреса
    need_response = Column(String, nullable=True)  # "email", "mail", "no"
    home_address = Column(String, nullable=True)

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


# --- 4. Таблиця Новин та Оголошень (Оперативні новини та розсилки) ---
class NewsItem(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now())
    admin_id = Column(BigInteger, nullable=False)
    admin_name = Column(String, nullable=True)
    text = Column(String, nullable=True)
    media_type = Column(String, nullable=True)  # 'photo', 'video', 'animation', 'document', None
    media_file_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)  # True = актуальна (відображається в клієнтському меню)
    sent_count = Column(Integer, default=0)
    blocked_count = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)  # None = без обмеження строку дії


# --- 5. Таблиця Загублених речей та документів ---
class LostItem(Base):
    __tablename__ = "lost_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now())
    returned_at = Column(DateTime, nullable=True)
    admin_id = Column(BigInteger, nullable=False)
    admin_name = Column(String, nullable=True)
    category = Column(String, nullable=False)  # "document" або "thing"
    title = Column(String, nullable=False)     # ПІБ на документі або назва речі
    details = Column(String, nullable=True)    # Маршрут, примітки тощо
    status = Column(String, default="active")  # "active" (на зберіганні), "returned" (повернуто)


# --- 6. Таблиця Вакансій (керована з адмін-панелі) ---
class Vacancy(Base):
    __tablename__ = "vacancies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now())
    admin_id = Column(BigInteger, nullable=True)
    admin_name = Column(String, nullable=True)
    category = Column(String, nullable=False)      # "experienced" або "trainee"
    title = Column(String, nullable=False)          # Назва вакансії
    contact_type = Column(String, nullable=False, default="url")  # "url" або "phone"
    contact_value = Column(String, nullable=False)  # URL або номер телефону
    sort_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)       # True = відображається пасажирам, False = деактивована (soft-delete)


# --- Індекси ---
Index("ix_feedbacks_status", Feedback.status)
Index("ix_feedbacks_created_at", Feedback.created_at)
Index("ix_users_telegram_id", BotUser.telegram_id)
Index("ix_users_is_subscribed", BotUser.is_subscribed)
Index("ix_news_is_active", NewsItem.is_active)
Index("ix_news_created_at", NewsItem.created_at)
Index("ix_lost_items_status", LostItem.status)
Index("ix_lost_items_category", LostItem.category)
Index("ix_lost_items_created_at", LostItem.created_at)
Index("ix_vacancies_category", Vacancy.category)
Index("ix_vacancies_is_active", Vacancy.is_active)


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
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import uuid
import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, func, Boolean, BigInteger, select, update, Index, text
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
                    await conn.execute(text("ALTER TABLE rental_orders ADD COLUMN user_passport VARCHAR"))
                    print("✅ Migration: added user_passport column to rental_orders")
                except Exception:
                    pass
                try:
                    await conn.execute(text("ALTER TABLE rental_orders ADD COLUMN user_address VARCHAR"))
                    print("✅ Migration: added user_address column to rental_orders")
                except Exception:
                    pass
                try:
                    await conn.execute(text("ALTER TABLE rental_orders ADD COLUMN signer_name VARCHAR"))
                    print("✅ Migration: added signer_name column to rental_orders")
                except Exception:
                    pass
                try:
                    await conn.execute(text("ALTER TABLE rental_orders ADD COLUMN foundation_doc VARCHAR"))
                    print("✅ Migration: added foundation_doc column to rental_orders")
                except Exception:
                    pass
                try:
                    await conn.execute(text("ALTER TABLE rental_orders ADD COLUMN staff_topic_messages_json TEXT DEFAULT '{}'"))
                    print("✅ Migration: added staff_topic_messages_json column to rental_orders")
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
                    await conn.execute(text("ALTER TABLE news ADD COLUMN title VARCHAR"))
                    print("✅ Migration: added title column to news")
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
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_museum_date_capacities_lookup ON museum_date_capacities(excursion_type, excursion_date, is_active)"))

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

                # Початкове наповнення бази маршрутної мережі Wialon (трамвай + тролейбус), якщо таблиця порожня
                try:
                    tp_count_res = await conn.execute(text("SELECT COUNT(*) FROM transit_platforms"))
                    tp_count = tp_count_res.scalar() or 0
                    seed_file = Path(__file__).resolve().parent / "wialon_transit_seed.json"
                    if tp_count == 0 and seed_file.exists():
                        with open(seed_file, "r", encoding="utf-8") as sf:
                            seed_payload = json.load(sf)

                        for d in seed_payload.get("depots", []):
                            await conn.execute(
                                text(
                                    "INSERT INTO transit_depots "
                                    "(code, arm_code, name, transport_type, park_lat, park_lon, gate_out_lat, gate_out_lon, "
                                    "gate_in_lat, gate_in_lon, maneuver_out_min, maneuver_in_min, anchor_stops_json) "
                                    "VALUES (:code, :arm_code, :name, :transport_type, :park_lat, :park_lon, :gate_out_lat, :gate_out_lon, "
                                    ":gate_in_lat, :gate_in_lon, :maneuver_out_min, :maneuver_in_min, :anchor_stops_json)"
                                ),
                                {
                                    "code": d["code"],
                                    "arm_code": d["arm_code"],
                                    "name": d["name"],
                                    "transport_type": d["transport_type"],
                                    "park_lat": d["park_lat"],
                                    "park_lon": d["park_lon"],
                                    "gate_out_lat": d["gate_out_lat"],
                                    "gate_out_lon": d["gate_out_lon"],
                                    "gate_in_lat": d["gate_in_lat"],
                                    "gate_in_lon": d["gate_in_lon"],
                                    "maneuver_out_min": d["maneuver_out_min"],
                                    "maneuver_in_min": d["maneuver_in_min"],
                                    "anchor_stops_json": json.dumps(d.get("anchor_stops", []), ensure_ascii=False),
                                },
                            )

                        for p in seed_payload.get("platforms", []):
                            await conn.execute(
                                text(
                                    "INSERT INTO transit_platforms "
                                    "(stop_id, name, canonical_key, transport_type, lat, lon, routes_json, headings_json, is_terminal, is_turning_loop) "
                                    "VALUES (:stop_id, :name, :canonical_key, :transport_type, :lat, :lon, :routes_json, :headings_json, :is_terminal, :is_turning_loop)"
                                ),
                                {
                                    "stop_id": p["stop_id"],
                                    "name": p["name"],
                                    "canonical_key": p["canonical_key"],
                                    "transport_type": p["transport_type"],
                                    "lat": p["lat"],
                                    "lon": p["lon"],
                                    "routes_json": json.dumps(p.get("routes", []), ensure_ascii=False),
                                    "headings_json": json.dumps(p.get("headings", {}), ensure_ascii=False),
                                    "is_terminal": bool(p.get("is_terminal")),
                                    "is_turning_loop": bool(p.get("is_turning_loop")),
                                },
                            )

                        for l in seed_payload.get("turning_loops", []):
                            await conn.execute(
                                text(
                                    "INSERT INTO transit_turning_loops "
                                    "(loop_id, name, canonical_key, transport_type, lat, lon, loop_class, perimeter_m, turn_min, aliases_json, platform_ids_json) "
                                    "VALUES (:loop_id, :name, :canonical_key, :transport_type, :lat, :lon, :loop_class, :perimeter_m, :turn_min, :aliases_json, :platform_ids_json)"
                                ),
                                {
                                    "loop_id": l["loop_id"],
                                    "name": l["name"],
                                    "canonical_key": l["canonical_key"],
                                    "transport_type": l["transport_type"],
                                    "lat": l["lat"],
                                    "lon": l["lon"],
                                    "loop_class": l["loop_class"],
                                    "perimeter_m": l["perimeter_m"],
                                    "turn_min": l["turn_min"],
                                    "aliases_json": json.dumps(l.get("aliases", []), ensure_ascii=False),
                                    "platform_ids_json": json.dumps(l.get("platform_ids", []), ensure_ascii=False),
                                },
                            )

                        for e in seed_payload.get("directed_edges", []):
                            await conn.execute(
                                text(
                                    "INSERT INTO transit_edges "
                                    "(edge_id, transport_type, from_stop_id, from_name, to_stop_id, to_name, edge_kind, routes_json, "
                                    "distance_m, dep_to_dep_sec, run_sec, dwell_sec, p15_sec, p85_sec, sample_n, source, profiles_json) "
                                    "VALUES (:edge_id, :transport_type, :from_stop_id, :from_name, :to_stop_id, :to_name, :edge_kind, :routes_json, "
                                    ":distance_m, :dep_to_dep_sec, :run_sec, :dwell_sec, :p15_sec, :p85_sec, :sample_n, :source, :profiles_json)"
                                ),
                                {
                                    "edge_id": e["edge_id"],
                                    "transport_type": e["transport_type"],
                                    "from_stop_id": e["from_stop_id"],
                                    "from_name": e["from_name"],
                                    "to_stop_id": e["to_stop_id"],
                                    "to_name": e["to_name"],
                                    "edge_kind": e["edge_kind"],
                                    "routes_json": json.dumps(e.get("routes", []), ensure_ascii=False),
                                    "distance_m": e["distance_m"],
                                    "dep_to_dep_sec": e["dep_to_dep_sec"],
                                    "run_sec": e["run_sec"],
                                    "dwell_sec": e["dwell_sec"],
                                    "p15_sec": e["p15_sec"],
                                    "p85_sec": e["p85_sec"],
                                    "sample_n": e["sample_n"],
                                    "source": e["source"],
                                    "profiles_json": json.dumps(e.get("profiles", {}), ensure_ascii=False),
                                },
                            )

                        for z in seed_payload.get("depot_zero_runs", []):
                            await conn.execute(
                                text(
                                    "INSERT INTO transit_depot_zero_runs "
                                    "(depot_code, transport_type, kind, terminal_name, terminal_key, variant_name, duration_min, distance_km, points_json, source) "
                                    "VALUES (:depot_code, :transport_type, :kind, :terminal_name, :terminal_key, :variant_name, :duration_min, :distance_km, :points_json, :source)"
                                ),
                                {
                                    "depot_code": z["depot_code"],
                                    "transport_type": z["transport_type"],
                                    "kind": z["kind"],
                                    "terminal_name": z["terminal_name"],
                                    "terminal_key": z["terminal_key"],
                                    "variant_name": z["variant_name"],
                                    "duration_min": z["duration_min"],
                                    "distance_km": z["distance_km"],
                                    "points_json": json.dumps(z.get("points", []), ensure_ascii=False),
                                    "source": z["source"],
                                },
                            )
                        print("✅ Seeding: завантажено повну базу маршрутної мережі Wialon (трамвай + тролейбус)")
                except Exception as seed_err:
                    print(f"⚠️ Seeding Wialon transit network warning: {seed_err}")
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


class MuseumDateCapacity(Base):
    __tablename__ = "museum_date_capacities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now())
    excursion_type = Column(String, nullable=False)  # "regular" або "holiday"
    excursion_date = Column(String, nullable=False)  # "ДД.ММ.РРРР ГГ:ХХ"
    max_capacity = Column(Integer, nullable=False)   # Максимальна кількість місць
    is_active = Column(Boolean, default=True)        # True = активна дата



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
    title = Column(String, nullable=True)
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


# --- 7. Таблиці Маршрутної Мережі та Телеметрії Wialon (Оренда Трамваїв і Тролейбусів) ---
class TransitDepot(Base):
    __tablename__ = "transit_depots"

    code = Column(String, primary_key=True)
    arm_code = Column(String, nullable=True)
    name = Column(String, nullable=False)
    transport_type = Column(String, nullable=False)  # "TRAM" або "TROLLEYBUS"
    park_lat = Column(Float, nullable=False)
    park_lon = Column(Float, nullable=False)
    gate_out_lat = Column(Float, nullable=False)
    gate_out_lon = Column(Float, nullable=False)
    gate_in_lat = Column(Float, nullable=False)
    gate_in_lon = Column(Float, nullable=False)
    maneuver_out_min = Column(Float, default=3.0)
    maneuver_in_min = Column(Float, default=3.5)
    anchor_stops_json = Column(Text, nullable=True)


class TransitPlatform(Base):
    __tablename__ = "transit_platforms"

    stop_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    canonical_key = Column(String, nullable=False)
    transport_type = Column(String, nullable=False)  # "TRAM" або "TROLLEYBUS"
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    routes_json = Column(Text, nullable=True)
    headings_json = Column(Text, nullable=True)
    is_terminal = Column(Boolean, default=False)
    is_turning_loop = Column(Boolean, default=False)


class TransitTurningLoop(Base):
    __tablename__ = "transit_turning_loops"

    loop_id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    canonical_key = Column(String, nullable=False)
    transport_type = Column(String, nullable=False)  # "TRAM" або "TROLLEYBUS"
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    loop_class = Column(String, nullable=False)      # "BIDIRECTIONAL", "ONEWAY_A_TO_A", "ONEWAY_B_TO_B", "BLOCK_LOOP", "WYE_TRIANGLE"
    perimeter_m = Column(Float, default=65.0)
    turn_min = Column(Integer, default=2)
    aliases_json = Column(Text, nullable=True)
    platform_ids_json = Column(Text, nullable=True)


class TransitEdge(Base):
    __tablename__ = "transit_edges"

    edge_id = Column(String, primary_key=True)
    transport_type = Column(String, nullable=False)
    from_stop_id = Column(String, nullable=False)
    from_name = Column(String, nullable=False)
    to_stop_id = Column(String, nullable=False)
    to_name = Column(String, nullable=False)
    edge_kind = Column(String, nullable=False)       # "SERVICE", "LOOP_TURN", "SWITCH"
    routes_json = Column(Text, nullable=True)
    distance_m = Column(Float, nullable=False)
    dep_to_dep_sec = Column(Float, nullable=False)
    run_sec = Column(Float, nullable=False)
    dwell_sec = Column(Float, nullable=False)
    p15_sec = Column(Float, nullable=True)
    p85_sec = Column(Float, nullable=True)
    sample_n = Column(Integer, default=0)
    source = Column(String, nullable=False)
    profiles_json = Column(Text, nullable=True)


class TransitDepotZeroRun(Base):
    __tablename__ = "transit_depot_zero_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    depot_code = Column(String, nullable=False)
    transport_type = Column(String, nullable=False)
    kind = Column(String, nullable=False)            # "PULL_OUT" або "PULL_IN"
    terminal_name = Column(String, nullable=False)
    terminal_key = Column(String, nullable=False)
    variant_name = Column(String, nullable=True)
    duration_min = Column(Integer, nullable=False)
    distance_km = Column(Float, nullable=False)
    points_json = Column(Text, nullable=True)
    source = Column(String, nullable=False)


# --- 8. Таблиці Модуля Оренди Електротранспорту (Динамічний пул слотів, Замовлення, Журнал дій) ---
class RentalDateSlot(Base):
    __tablename__ = "rental_date_slots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rental_date = Column(String, nullable=False)           # "ДД.ММ.РРРР"
    transport_type = Column(String, default="ANY")         # "TRAM", "TROLLEYBUS", "ANY"
    slot_time = Column(String, nullable=False)             # "12:00", "15:00"
    status = Column(String, default="free")                # "free", "locked", "booked", "expired"
    locked_by_order_id = Column(Integer, nullable=True)
    added_by_id = Column(BigInteger, nullable=True)
    added_by_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())


class RentalOrder(Base):
    __tablename__ = "rental_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_uid = Column(String, unique=True, nullable=False)        # "RNT-20261029-XXXX"
    contract_number = Column(String, unique=True, nullable=False)  # "2026-0001-О"
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Дані Замовника
    user_id = Column(BigInteger, nullable=False)
    user_full_name = Column(String, nullable=False)
    user_phone = Column(String, nullable=False)
    user_email = Column(String, nullable=True)
    user_tax_id = Column(String, nullable=True)                    # РНОКПП або ЄДРПОУ
    customer_type = Column(String, default="individual")           # "individual", "fop", "company"
    company_name = Column(String, nullable=True)
    user_passport = Column(String, nullable=True)
    user_address = Column(String, nullable=True)
    signer_name = Column(String, nullable=True)
    foundation_doc = Column(String, nullable=True)

    # Параметри транспорту та маршруту (Wialon)
    transport_type = Column(String, nullable=False)                # "TRAM" або "TROLLEYBUS"
    wagon_type = Column(String, nullable=False)                    # "Ретро-трамвай МТВ-82", "Tatra T3", тощо
    depot_code = Column(String, nullable=False)                    # "ТД-1", "ТД-2", "ВРМ", "ТрД"
    route_mode = Column(String, default="custom")                  # "preset" або "custom"
    preset_name = Column(String, nullable=True)
    pickup_stop = Column(String, nullable=False)
    via_loops_json = Column(Text, default="[]")                    # JSON-список проміжних розворотних кілець
    dropoff_stop = Column(String, nullable=False)
    wait_minutes = Column(Integer, default=0)
    extra_services_json = Column(Text, default="[]")               # JSON-список додаткових послуг

    # Точні розрахунки Wialon (Фаза 1 + Фаза 2 + Фаза 3)
    distance_pull_out_km = Column(Float, nullable=False)
    distance_route_km = Column(Float, nullable=False)
    distance_pull_in_km = Column(Float, nullable=False)
    total_distance_km = Column(Float, nullable=False)

    duration_pull_out_min = Column(Integer, nullable=False)
    duration_route_min = Column(Integer, nullable=False)
    duration_pull_in_min = Column(Integer, nullable=False)
    total_duration_min = Column(Integer, nullable=False)

    # Фінансовий розрахунок (IBAN без РРО)
    km_price_uah = Column(Float, default=0.0)
    wait_price_uah = Column(Float, default=0.0)
    extras_price_uah = Column(Float, default=0.0)
    total_price_uah = Column(Float, nullable=False)

    # Сценарій підписання та бронювання слоту
    signing_scenario = Column(String, nullable=False)              # "kep" (+3 дні) або "paper" (+4 дні)
    rental_date = Column(String, nullable=False)                   # "ДД.ММ.РРРР"
    rental_time_slot = Column(String, nullable=True)               # "12:00" або None (якщо очікує слотів Служби руху)
    slot_lock_expires_at = Column(DateTime, nullable=True)         # +36 годин для "paper" або +24 год для "kep"

    # Статус життєвого циклу
    status = Column(String, default="pending_slots")
    # Можливі статуси:
    # "pending_slots"        - очікує додавання слотів Службою руху
    # "awaiting_slot_choice" - слоти додані, клієнт обирає час
    # "awaiting_signature"   - договір та IBAN-рахунок згенеровані, очікується підпис (КЕП або скан з Управління)
    # "signed_uploaded"      - підписаний договір завантажено клієнтом (відправлено юристам та у штаб)
    # "legal_approved"       - погоджено Юридичним відділом та ВУПтаП
    # "paid_confirmed"       - оплата по IBAN підтверджена Бухгалтерією
    # "vehicle_assigned"     - депо призначило бортовий номер та водія (видано посадковий талон)
    # "completed"            - рейс виконано
    # "expired_36h"          - автоматично скасовано через перевищення 36 годин
    # "cancelled"            - скасовано

    # Відмітки підрозділів у спільному чаті
    traffic_approved_by = Column(String, nullable=True)
    traffic_approved_at = Column(DateTime, nullable=True)
    legal_approved_by = Column(String, nullable=True)
    legal_approved_at = Column(DateTime, nullable=True)
    vuptap_approved_by = Column(String, nullable=True)
    vuptap_approved_at = Column(DateTime, nullable=True)
    accounting_approved_by = Column(String, nullable=True)
    accounting_approved_at = Column(DateTime, nullable=True)
    depot_assigned_by = Column(String, nullable=True)
    depot_assigned_at = Column(DateTime, nullable=True)

    # Призначений вагон/тролейбус та водій
    assigned_board_number = Column(String, nullable=True)
    assigned_driver_name = Column(String, nullable=True)
    assigned_driver_phone = Column(String, nullable=True)

    # Прикріплені файли Telegram та ID картки в штабному чаті
    signed_file_id = Column(String, nullable=True)
    signed_file_name = Column(String, nullable=True)
    payment_file_id = Column(String, nullable=True)
    staff_chat_id = Column(BigInteger, nullable=True)
    staff_chat_message_id = Column(BigInteger, nullable=True)
    staff_topic_messages_json = Column(Text, default="{}")
    safety_accepted_at = Column(DateTime, nullable=True)
    reminder_sent = Column(Boolean, default=False)


class RentalAuditLog(Base):
    __tablename__ = "rental_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=func.now())
    actor_id = Column(BigInteger, nullable=False)
    actor_name = Column(String, nullable=False)
    actor_role = Column(String, nullable=False)
    action = Column(String, nullable=False)
    details = Column(Text, nullable=True)


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
Index("ix_museum_date_capacities_type_date", MuseumDateCapacity.excursion_type, MuseumDateCapacity.excursion_date)
Index("ix_museum_date_capacities_is_active", MuseumDateCapacity.is_active)
Index("ix_transit_platforms_key", TransitPlatform.transport_type, TransitPlatform.canonical_key)
Index("ix_transit_loops_type", TransitTurningLoop.transport_type, TransitTurningLoop.canonical_key)
Index("ix_transit_edges_from", TransitEdge.transport_type, TransitEdge.from_stop_id)
Index("ix_transit_edges_to", TransitEdge.transport_type, TransitEdge.to_stop_id)
Index("ix_transit_zero_runs_lookup", TransitDepotZeroRun.depot_code, TransitDepotZeroRun.kind, TransitDepotZeroRun.terminal_key)
Index("ix_rental_slots_lookup", RentalDateSlot.rental_date, RentalDateSlot.transport_type, RentalDateSlot.status)
Index("ix_rental_orders_user", RentalOrder.user_id, RentalOrder.status)
Index("ix_rental_orders_status", RentalOrder.status)
Index("ix_rental_audit_order", RentalAuditLog.order_id, RentalAuditLog.created_at)


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

    # --- Робота з модулем Оренди Електротранспорту ---
    async def add_rental_slots(
        self,
        rental_date: str,
        slot_times: list[str],
        transport_type: str = "ANY",
        added_by_id: int = 0,
        added_by_name: str = "Служба руху",
    ) -> list[str]:
        """Додає вільні часові слоти у динамічний пул на обрану дату."""
        added: list[str] = []
        norm_type = (transport_type or "ANY").upper()
        async with self.session_factory() as session:
            for raw_slot in slot_times:
                slot_time = raw_slot.strip()
                if not slot_time:
                    continue
                existing_res = await session.execute(
                    select(RentalDateSlot).where(
                        RentalDateSlot.rental_date == rental_date,
                        RentalDateSlot.slot_time == slot_time,
                        RentalDateSlot.transport_type.in_([norm_type, "ANY"]),
                    )
                )
                existing_slot = existing_res.scalar_one_or_none()
                if existing_slot:
                    if existing_slot.status in ("expired",):
                        existing_slot.status = "free"
                        existing_slot.locked_by_order_id = None
                        added.append(slot_time)
                    continue

                new_slot = RentalDateSlot(
                    rental_date=rental_date,
                    transport_type=norm_type,
                    slot_time=slot_time,
                    status="free",
                    added_by_id=added_by_id,
                    added_by_name=added_by_name,
                )
                session.add(new_slot)
                added.append(slot_time)
            await session.commit()
        return sorted(added)

    async def get_available_rental_slots(
        self,
        rental_date: str,
        transport_type: str = "ANY",
    ) -> list[str]:
        """Повертає вільні слоти ('free') на вказану дату."""
        norm_type = (transport_type or "ANY").upper()
        allowed_types = [norm_type, "ANY"] if norm_type != "ANY" else ["TRAM", "TROLLEYBUS", "ANY"]
        async with self.session_factory() as session:
            res = await session.execute(
                select(RentalDateSlot.slot_time)
                .where(
                    RentalDateSlot.rental_date == rental_date,
                    RentalDateSlot.status == "free",
                    RentalDateSlot.transport_type.in_(allowed_types),
                )
                .order_by(RentalDateSlot.slot_time.asc())
            )
            slots = list(dict.fromkeys(res.scalars().all()))
            return sorted(slots)

    async def lock_rental_slot(
        self,
        rental_date: str,
        slot_time: str,
        transport_type: str,
        order_id: int,
    ) -> bool:
        """Бронює обраний слот за замовленням, залишаючи інші слоти на цю дату вільними для наступних клієнтів."""
        norm_type = (transport_type or "ANY").upper()
        allowed_types = [norm_type, "ANY"] if norm_type != "ANY" else ["TRAM", "TROLLEYBUS", "ANY"]
        async with self.session_factory() as session:
            res = await session.execute(
                select(RentalDateSlot)
                .where(
                    RentalDateSlot.rental_date == rental_date,
                    RentalDateSlot.slot_time == slot_time,
                    RentalDateSlot.status == "free",
                    RentalDateSlot.transport_type.in_(allowed_types),
                )
                .order_by(RentalDateSlot.id.asc())
            )
            slot_obj = res.scalars().first()
            if not slot_obj:
                return False
            slot_obj.status = "locked"
            slot_obj.locked_by_order_id = order_id
            await session.commit()
            return True

    async def book_rental_slot_by_order(self, order_id: int) -> None:
        """Переводить слот замовлення у статус 'booked' після оплати."""
        async with self.session_factory() as session:
            await session.execute(
                update(RentalDateSlot)
                .where(RentalDateSlot.locked_by_order_id == order_id)
                .values(status="booked")
            )
            await session.commit()

    async def release_rental_slot_by_order(self, order_id: int) -> None:
        """Повертає слот у статус 'free' у разі скасування або тайм-ауту 36 годин."""
        async with self.session_factory() as session:
            await session.execute(
                update(RentalDateSlot)
                .where(RentalDateSlot.locked_by_order_id == order_id)
                .values(status="free", locked_by_order_id=None)
            )
            await session.commit()

    async def get_all_rental_slots_for_date(self, rental_date: str) -> list[RentalDateSlot]:
        """Повертає всі слоти на дату (free, locked, booked) для перегляду та керування майстрами Депо."""
        async with self.session_factory() as session:
            res = await session.execute(
                select(RentalDateSlot)
                .where(RentalDateSlot.rental_date == rental_date)
                .order_by(RentalDateSlot.slot_time.asc())
            )
            return list(res.scalars().all())

    async def get_dates_with_free_slots(self) -> list[str]:
        """Повертає перелік дат, де наявні вільні слоти ('free') для вибору замовниками або видалення в депо."""
        async with self.session_factory() as session:
            res = await session.execute(
                select(RentalDateSlot.rental_date)
                .where(RentalDateSlot.status == "free")
                .distinct()
            )
            dates = [str(d) for d in res.scalars().all() if d]
            return sorted(dates)

    async def delete_rental_slot_by_id(self, slot_id: int) -> bool:
        """Видаляє вільний слот за ідентифікатором. Якщо слот уже заброньовано або заблоковано, повертає False."""
        async with self.session_factory() as session:
            res = await session.execute(
                select(RentalDateSlot).where(RentalDateSlot.id == slot_id)
            )
            slot = res.scalars().first()
            if not slot or slot.status != "free":
                return False
            await session.delete(slot)
            await session.commit()
            return True

    async def create_rental_order(self, data: dict) -> RentalOrder:
        """Створює замовлення оренди, присвоює номер договору №XXXX-О та фіксує запис у журналі дій."""
        now_dt = datetime.datetime.now()
        date_str = now_dt.strftime("%Y%m%d")
        short_uuid = str(uuid.uuid4())[:4].upper()
        order_uid = f"RNT-{date_str}-{short_uuid}"

        async with self.session_factory() as session:
            count_res = await session.execute(select(func.count(RentalOrder.id)))
            seq_num = (count_res.scalar() or 0) + 1
            contract_number = data.get("contract_number") or f"{now_dt.year}-{seq_num:04d}-О"

            via_loops = data.get("via_loops", [])
            extra_services = data.get("extra_services", [])
            signing_scenario = data.get("signing_scenario", "kep")
            rental_time_slot = data.get("rental_time_slot")

            lock_hours = 36 if signing_scenario == "paper" else 24
            slot_lock_expires_at = (
                data.get("slot_lock_expires_at")
                or (now_dt + datetime.timedelta(hours=lock_hours) if rental_time_slot else None)
            )
            initial_status = data.get("status") or (
                "awaiting_signature" if rental_time_slot else "pending_slots"
            )

            order = RentalOrder(
                order_uid=order_uid,
                contract_number=contract_number,
                user_id=int(data["user_id"]),
                user_full_name=str(data.get("user_full_name", "Клієнт")),
                user_phone=str(data.get("user_phone", "")),
                user_email=data.get("user_email"),
                user_tax_id=data.get("user_tax_id"),
                customer_type=str(data.get("customer_type", "individual")),
                company_name=data.get("company_name"),
                user_passport=data.get("user_passport"),
                user_address=data.get("user_address"),
                signer_name=data.get("signer_name"),
                foundation_doc=data.get("foundation_doc"),
                transport_type=str(data.get("transport_type", "TRAM")),
                wagon_type=str(data.get("wagon_type", "Ретро-трамвай МТВ-82")),
                depot_code=str(data.get("depot_code", "ВРМ")),
                route_mode=str(data.get("route_mode", "custom")),
                preset_name=data.get("preset_name"),
                pickup_stop=str(data["pickup_stop"]),
                via_loops_json=json.dumps(via_loops, ensure_ascii=False) if isinstance(via_loops, list) else str(via_loops),
                dropoff_stop=str(data["dropoff_stop"]),
                wait_minutes=int(data.get("wait_minutes", 0)),
                extra_services_json=json.dumps(extra_services, ensure_ascii=False) if isinstance(extra_services, list) else str(extra_services),
                distance_pull_out_km=float(data.get("distance_pull_out_km", 0.0)),
                distance_route_km=float(data.get("distance_route_km", 0.0)),
                distance_pull_in_km=float(data.get("distance_pull_in_km", 0.0)),
                total_distance_km=float(data.get("total_distance_km", 0.0)),
                duration_pull_out_min=int(data.get("duration_pull_out_min", 0)),
                duration_route_min=int(data.get("duration_route_min", 0)),
                duration_pull_in_min=int(data.get("duration_pull_in_min", 0)),
                total_duration_min=int(data.get("total_duration_min", 0)),
                km_price_uah=float(data.get("km_price_uah", 0.0)),
                wait_price_uah=float(data.get("wait_price_uah", 0.0)),
                extras_price_uah=float(data.get("extras_price_uah", 0.0)),
                total_price_uah=float(data.get("total_price_uah", 0.0)),
                signing_scenario=signing_scenario,
                rental_date=str(data["rental_date"]),
                rental_time_slot=rental_time_slot,
                slot_lock_expires_at=slot_lock_expires_at,
                status=initial_status,
                safety_accepted_at=now_dt if data.get("safety_accepted", True) else None,
            )
            session.add(order)
            await session.flush()

            audit = RentalAuditLog(
                order_id=order.id,
                actor_id=int(data["user_id"]),
                actor_name=str(data.get("user_full_name", "Клієнт")),
                actor_role="Клієнт",
                action="CREATED",
                details=(
                    f"Створено замовлення {contract_number} ({order.wagon_type}, "
                    f"дата {order.rental_date}, слот {order.rental_time_slot or 'очікує Службу руху'})"
                ),
            )
            session.add(audit)
            await session.commit()
            await session.refresh(order)

        if rental_time_slot:
            await self.lock_rental_slot(
                rental_date=order.rental_date,
                slot_time=rental_time_slot,
                transport_type=order.transport_type,
                order_id=order.id,
            )
        return order

    async def get_rental_order(self, order_id: int) -> RentalOrder | None:
        async with self.session_factory() as session:
            res = await session.execute(select(RentalOrder).where(RentalOrder.id == order_id))
            return res.scalar_one_or_none()

    async def get_rental_order_by_contract(self, contract_number: str) -> RentalOrder | None:
        async with self.session_factory() as session:
            res = await session.execute(
                select(RentalOrder).where(RentalOrder.contract_number == contract_number)
            )
            return res.scalar_one_or_none()

    async def get_user_active_rental_orders(self, user_id: int) -> list[RentalOrder]:
        """Повертає активні договори та замовлення клієнта для розділу 'Діючі договори та замовлення'."""
        inactive_statuses = ("cancelled", "expired_36h")
        async with self.session_factory() as session:
            res = await session.execute(
                select(RentalOrder)
                .where(
                    RentalOrder.user_id == user_id,
                    RentalOrder.status.notin_(inactive_statuses),
                )
                .order_by(RentalOrder.created_at.desc())
            )
            return list(res.scalars().all())

    async def get_pending_slots_orders_for_date(
        self,
        rental_date: str,
        transport_type: str = "ANY",
    ) -> list[RentalOrder]:
        """Повертає замовлення, які очікують додавання слотів Службою руху на вказану дату."""
        norm_type = (transport_type or "ANY").upper()
        async with self.session_factory() as session:
            stmt = select(RentalOrder).where(
                RentalOrder.rental_date == rental_date,
                RentalOrder.status == "pending_slots",
            )
            if norm_type != "ANY":
                stmt = stmt.where(RentalOrder.transport_type == norm_type)
            res = await session.execute(stmt.order_by(RentalOrder.created_at.asc()))
            return list(res.scalars().all())

    async def update_rental_order_fields(self, order_id: int, values: dict) -> RentalOrder | None:
        """Оновлює поля замовлення оренди та повертає оновлений об'єкт."""
        values_with_ts = dict(values)
        values_with_ts["updated_at"] = datetime.datetime.now()
        async with self.session_factory() as session:
            await session.execute(
                update(RentalOrder).where(RentalOrder.id == order_id).values(**values_with_ts)
            )
            await session.commit()
            res = await session.execute(select(RentalOrder).where(RentalOrder.id == order_id))
            return res.scalar_one_or_none()

    async def add_rental_audit_log(
        self,
        order_id: int,
        actor_id: int,
        actor_name: str,
        actor_role: str,
        action: str,
        details: str = "",
    ) -> RentalAuditLog:
        """Додає запис у деталізований журнал дій за замовленням."""
        async with self.session_factory() as session:
            entry = RentalAuditLog(
                order_id=order_id,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_role=actor_role,
                action=action,
                details=details,
            )
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            return entry

    async def get_rental_audit_logs(self, order_id: int, limit: int = 20) -> list[RentalAuditLog]:
        """Повертає історію дій за замовленням у хронологічному порядку."""
        async with self.session_factory() as session:
            res = await session.execute(
                select(RentalAuditLog)
                .where(RentalAuditLog.order_id == order_id)
                .order_by(RentalAuditLog.created_at.asc(), RentalAuditLog.id.asc())
            )
            logs = list(res.scalars().all())
            return logs[-limit:] if limit and len(logs) > limit else logs

    async def expire_overdue_rental_orders(
        self,
        now_dt: datetime.datetime | None = None,
    ) -> list[RentalOrder]:
        """Автоматично переводить прострочені договори ('awaiting_signature') у 'expired_36h' та звільняє слоти."""
        check_dt = now_dt or datetime.datetime.now()
        expired_orders: list[RentalOrder] = []
        async with self.session_factory() as session:
            res = await session.execute(
                select(RentalOrder).where(
                    RentalOrder.status == "awaiting_signature",
                    RentalOrder.slot_lock_expires_at.isnot(None),
                    RentalOrder.slot_lock_expires_at <= check_dt,
                )
            )
            candidates = list(res.scalars().all())
            for order in candidates:
                order.status = "expired_36h"
                order.updated_at = check_dt
                session.add(
                    RentalAuditLog(
                        order_id=order.id,
                        actor_id=0,
                        actor_name="Система",
                        actor_role="Авто-контроль 36 год",
                        action="EXPIRED_36H",
                        details=f"Перевищено ліміт часу на підписання договору {order.contract_number}. Слот звільнено.",
                    )
                )
                expired_orders.append(order)
            await session.commit()

        for order in expired_orders:
            await self.release_rental_slot_by_order(order.id)
        return expired_orders

    async def get_recent_rental_orders(self, limit: int = 10) -> list[RentalOrder]:
        """Повертає останні замовлення для вибору в аналітичному пульті."""
        async with self.session_factory() as session:
            res = await session.execute(
                select(RentalOrder)
                .order_by(RentalOrder.id.desc())
                .limit(limit)
            )
            return list(res.scalars().all())

    async def get_recent_audit_actions(self, limit: int = 10) -> list[RentalAuditLog]:
        """Повертає останні дії персоналу для перегляду в темі 'Аналітика дій працівників'."""
        async with self.session_factory() as session:
            res = await session.execute(
                select(RentalAuditLog)
                .order_by(RentalAuditLog.id.desc())
                .limit(limit)
            )
            return list(res.scalars().all())

    async def get_rental_period_analytics(self, days: int = 7) -> dict:
        """Розраховує агреговані аналітичні показники роботи модуля оренди за вказаний період (тиждень / місяць)."""
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        async with self.session_factory() as session:
            res = await session.execute(
                select(RentalOrder).where(RentalOrder.created_at >= cutoff)
            )
            orders = list(res.scalars().all())
            total_orders = len(orders)
            completed_orders = sum(1 for o in orders if o.status == "completed")
            cancelled_orders = sum(1 for o in orders if o.status in ("cancelled", "expired_36h"))
            active_orders = total_orders - completed_orders - cancelled_orders
            total_revenue_uah = sum(
                float(o.total_price_uah or 0.0)
                for o in orders
                if o.status in ("completed", "paid_confirmed", "vehicle_assigned")
            )
            vat_uah = round(total_revenue_uah / 6.0, 2)
            without_vat_uah = round(total_revenue_uah - vat_uah, 2)
            total_km = sum(
                float(o.total_distance_km or 0.0)
                for o in orders
                if o.status in ("completed", "vehicle_assigned")
            )
            mtv_count = sum(1 for o in orders if "МТВ" in (o.wagon_type or "") or "retro_mtv" in (o.wagon_type or "").lower())
            open_914_count = sum(1 for o in orders if "914" in (o.wagon_type or "") or "відкритий" in (o.wagon_type or "").lower())

            # Розрахунок середнього часу реакції підрозділів (SLA)
            order_ids = [o.id for o in orders]
            sla_data: dict[str, list[float]] = {
                "vuptap": [],
                "legal": [],
                "accounting": [],
                "depot": [],
            }
            if order_ids:
                logs_res = await session.execute(
                    select(RentalAuditLog)
                    .where(RentalAuditLog.order_id.in_(order_ids))
                    .order_by(RentalAuditLog.created_at.asc())
                )
                order_created_map = {o.id: o.created_at for o in orders if o.created_at}
                for log in logs_res.scalars().all():
                    created_at = order_created_map.get(log.order_id)
                    if not created_at or not log.created_at:
                        continue
                    delta_min = max(0.0, (log.created_at - created_at).total_seconds() / 60.0)
                    role = (log.actor_role or "").lower()
                    if "служба руху" in role or "вуптап" in role or "traffic" in role:
                        sla_data["vuptap"].append(delta_min)
                    elif "юридич" in role or "legal" in role:
                        sla_data["legal"].append(delta_min)
                    elif "бухгалтер" in role or "accounting" in role:
                        sla_data["accounting"].append(delta_min)
                    elif "депо" in role or "depot" in role or "врм" in role:
                        sla_data["depot"].append(delta_min)

            avg_sla = {
                k: round(sum(v) / len(v), 1) if v else None
                for k, v in sla_data.items()
            }

            return {
                "days": days,
                "total_orders": total_orders,
                "completed_orders": completed_orders,
                "cancelled_orders": cancelled_orders,
                "active_orders": active_orders,
                "total_revenue_uah": total_revenue_uah,
                "vat_uah": vat_uah,
                "without_vat_uah": without_vat_uah,
                "total_km": total_km,
                "mtv_count": mtv_count,
                "open_914_count": open_914_count,
                "avg_sla_min": avg_sla,
            }

    async def get_order_timeline_analytics(self, order_id: int) -> dict | None:
        """Повертає деталізований аналітичний хронометраж замовлення з таймлайном дій підрозділів."""
        async with self.session_factory() as session:
            res_ord = await session.execute(
                select(RentalOrder).where(RentalOrder.id == order_id)
            )
            order = res_ord.scalars().first()
            if not order:
                return None
            res_logs = await session.execute(
                select(RentalAuditLog)
                .where(RentalAuditLog.order_id == order_id)
                .order_by(RentalAuditLog.created_at.asc(), RentalAuditLog.id.asc())
            )
            logs = list(res_logs.scalars().all())
            return {
                "order": order,
                "logs": logs,
            }
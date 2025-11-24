import asyncio
import logging
import sys
from unittest.mock import MagicMock, AsyncMock
# Додаємо роботу з БД
from database.db import init_db, MuseumBooking, AsyncSessionLocal
from sqlalchemy import select
import random

# === 1. ЖОРСТКІ МОКИ (Найперші рядки) ===
# Підміняємо всі зовнішні сервіси, щоб код не падав при імпорті
mock_service = MagicMock()
mock_service.get_stop_info_v12 = AsyncMock(return_value={"id": 1, "title": "Mock Stop", "routes": []})
mock_service.append_row = AsyncMock(return_value=True)

sys.modules["services.easyway_service"] = MagicMock()
sys.modules["services.easyway_service"].easyway_service = mock_service
sys.modules["integrations.google_sheets.client"] = MagicMock()
sys.modules["integrations.google_sheets.client"].GoogleSheetsClient = MagicMock()

# === 2. ІМПОРТИ TELEGRAM ===
from aiohttp import web
from telegram import Update, User
from telegram.ext import ApplicationBuilder, MessageHandler, filters

# === 3. ПІДМІНА МЕТОДІВ TELEGRAM (Щоб не ліз в інтернет) ===
from telegram.ext import ExtBot


async def fake_do_post(*args, **kwargs):
    logging.info("🕊️ [MOCK] Бот намагався відправити повідомлення (успішно ігноровано)")
    return True


async def fake_get_me(*args, **kwargs):
    return User(id=123456789, first_name="LoadTestBot", is_bot=True, username="test_bot")


ExtBot._do_post = fake_do_post
ExtBot.get_me = fake_get_me

# Фейковий токен
BOT_TOKEN = "123456789:AAHzWy-FakeTokenForLoadTesting_XVzWi"


# === 4. ВЕБ-СЕРВЕР ===
async def handle_webhook(request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)

        # Викликаємо логіку бота
        if update:
            await application.process_update(update)
            return web.Response(text="OK", status=200)
        else:
            return web.Response(text="Bad Update", status=400)
    except Exception as e:
        logging.exception("❌ ПОМИЛКА В ОБРОБЦІ ЗАПИТУ:")
        return web.Response(text=str(e), status=500)


async def database_stress_handler(update, context):
    """Цей хендлер намагається записати дані в БД при кожному запиті"""
    user_id = update.message.from_user.id

    try:
        async with AsyncSessionLocal() as session:
            # Імітація: перевіряємо, чи є вже такий юзер (читання)
            # (У реальному боті тут було б набагато більше логіки)
            stmt = select(MuseumBooking).where(MuseumBooking.user_phone == str(user_id))
            await session.execute(stmt)

            # Імітація: створюємо новий запис (запис - найважча операція для SQLite)
            new_booking = MuseumBooking(
                user_name=f"Test User {user_id}",
                user_phone=str(user_id),
                people_count=random.randint(1, 5),
                excursion_date="2023-10-10",
                status="new"
            )
            session.add(new_booking)
            await session.commit()

        await update.message.reply_text(f"Booking created for {user_id}")

    except Exception as e:
        # Логуємо помилку, щоб бачити "database is locked"
        logging.error(f"🔥 DB ERROR: {e}")
        # Важливо: кидаємо помилку далі, щоб Locust зарахував це як Failure
        raise e


async def main():
    global application
    print("⏳ Запуск сервера...")

    # !!! ІНІЦІАЛІЗАЦІЯ БД !!!
    print("📁 Ініціалізація SQLite...")
    await init_db()

    try:
        application = ApplicationBuilder().token(BOT_TOKEN).build()

        # !!! ВИКОРИСТОВУЄМО НОВИЙ ХЕНДЛЕР !!!
        application.add_handler(MessageHandler(filters.TEXT, database_stress_handler))

        # Далі все без змін...
        await application.initialize()
        await application.start()

        # (Код запуску веб-сервера aiohttp залишається тим самим...)
        app = web.Application()
        app.router.add_post("/webhook", handle_webhook)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", 8001)
        await site.start()

        print("\n" + "=" * 60)
        print("✅ СЕРВЕР ГОТОВИЙ ДО STRESS TEST (DB WRITE)!")
        print("💀 Зараз ми спробуємо 'покласти' SQLite")
        print("=" * 60 + "\n")

        await asyncio.Event().wait()

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Сервер зупинено.")
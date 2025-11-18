# main.py
import asyncio
from config.settings import TELEGRAM_BOT_TOKEN
from bot.bot import TransportBot
from utils.logger import logger
from handlers.accessible_transport_handlers import load_easyway_route_ids
from database.db import init_db




async def main():
    """Головна функція запуску бота"""

    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN не встановлено в .env")
        return

    logger.info("🚀 Запуск Telegram бота...")
    bot = TransportBot(TELEGRAM_BOT_TOKEN)

    # Ініціалізація Бази Даних
    logger.info("📂 Ініціалізація бази даних SQLite...")
    await init_db()

    # Завантажуємо маршрути з EasyWay
    logger.info("--- [MAIN] Викликаю load_easyway_route_ids ---")
    try:
        await load_easyway_route_ids(bot.app)
        logger.info("--- [MAIN] load_easyway_route_ids ЗАВЕРШЕНО ---")
    except Exception as e:
        logger.error(f"--- [MAIN] КРИТИЧНА ПОМИЛКА: {e} ---", exc_info=True)
        logger.error("--- [MAIN] Бот не буде запущений. ---")
        return

    # Запускаємо бота
    try:
        await bot.app.initialize()
        await bot.app.updater.start_polling()
        await bot.app.start()

        logger.info("✅ Бот успішно запущений. Натисніть Ctrl+C для зупинки.")
        await asyncio.Event().wait()

    except (KeyboardInterrupt, SystemExit):
        logger.info("ℹ️ Отримано сигнал зупинки. Завершення роботи...")
    except Exception as e:
        logger.error(f"❌ Критична помилка: {e}", exc_info=True)
    finally:
        if bot.app.updater and bot.app.updater.running:
            await bot.app.updater.stop()
        if bot.app.running:
            await bot.app.stop()

        await bot.app.shutdown()
        logger.info("✅ Бот зупинено.")


if __name__ == "__main__":
    asyncio.run(main())
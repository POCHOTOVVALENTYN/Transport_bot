import logging
import asyncio  # <-- Імпортуємо asyncio
from config.settings import TELEGRAM_BOT_TOKEN, LOG_LEVEL
from bot.bot import TransportBot
from services.gtfs_cache_service import gtfs_cache

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger(__name__)


async def main():
    """Головна функція запуску бота"""

    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN не встановлено в .env")
        return

    try:
        logger.info("ℹ️ Завантаження GTFS-кешу...")
        # Це синхронна функція, вона виконається до запуску бота
        gtfs_cache.load_all_data()
        logger.info("✅ GTFS-кеш успішно завантажено.")
    except Exception as e:
        logger.error(f"❌ КРИТИЧНА ПОМИЛКА: Не вдалося завантажити GTFS-кеш. {e}", exc_info=True)
        return

    logger.info("🚀 Запуск Telegram бота...")
    bot = TransportBot(TELEGRAM_BOT_TOKEN)

    # --- ПОЧАТОК НОВОЇ ЛОГІКИ ЗАПУСКУ ---
    # Ми не викликаємо bot.start(), а керуємо bot.app напряму
    try:
        # 1. Ініціалізуємо додаток
        await bot.app.initialize()
        # 2. Запускаємо polling у фоновому режимі
        await bot.app.updater.start_polling()
        # 3. Запускаємо сам додаток
        await bot.app.start()

        logger.info("✅ Бот успішно запущений. Натисніть Ctrl+C для зупинки.")

        # 4. Тримаємо програму "живою"
        await asyncio.Event().wait()

    except (KeyboardInterrupt, SystemExit):
        logger.info("ℹ️ Отримано сигнал зупинки. Завершення роботи...")
    finally:
        # 5. Коректно зупиняємо все
        if bot.app.updater and bot.app.updater.is_running:
            await bot.app.updater.stop()
        if bot.app.running:
            await bot.app.stop()
        await bot.app.shutdown()
        logger.info("✅ Бот зупинено.")
    # --- КІНЕЦЬ НОВОЇ ЛОГІКИ ЗАПУСКУ ---


if __name__ == "__main__":
    asyncio.run(main())
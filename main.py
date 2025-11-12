# main.py
import logging
import asyncio
from config.settings import TELEGRAM_BOT_TOKEN, LOG_LEVEL
from bot.bot import TransportBot

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger(__name__)

async def main():
    """Головна функція запуску бота"""

    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN не встановлено в .env")
        return

    # Блок 'try...except' для gtfs_cache повністю видалено

    logger.info("🚀 Запуск Telegram бота...")
    bot = TransportBot(TELEGRAM_BOT_TOKEN)

    try:
        await bot.app.initialize()
        await bot.app.updater.start_polling()
        await bot.app.start()
        logger.info("✅ Бот успішно запущений. Натисніть Ctrl+C для зупинки.")
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("ℹ️ Отримано сигнал зупинки. Завершення роботи...")
    finally:
        if bot.app.updater and bot.app.updater.is_running:
            await bot.app.updater.stop()
        if bot.app.running:
            await bot.app.stop()
        await bot.app.shutdown()
        logger.info("✅ Бот зупинено.")

if __name__ == "__main__":
    asyncio.run(main())
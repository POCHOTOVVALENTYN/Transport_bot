import logging
from config.settings import TELEGRAM_BOT_TOKEN, LOG_LEVEL
from bot.bot import TransportBot
# --- ПОЧАТОК ВИПРАВЛЕННЯ ---
# 1. Імпортуємо наш новий кеш
from services.gtfs_cache_service import gtfs_cache
# --- КІНЕЦЬ ВИПРАВЛЕННЯ ---

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger(__name__)


async def main():
    """Головна функція запуску бота"""

    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN не встановлено в .env")
        return

    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
    # 2. Викликаємо завантаження кешу (це синхронна функція)
    try:
        logger.info("ℹ️ Завантаження GTFS-кешу...")
        gtfs_cache.load_all_data()
        logger.info("✅ GTFS-кеш успішно завантажено.")
    except Exception as e:
        logger.error(f"❌ КРИТИЧНА ПОМИЛКА: Не вдалося завантажити GTFS-кеш. {e}", exc_info=True)
        # УВАГА: В робочому режимі тут можна зупинити бота,
        # оскільки пошук інклюзивного транспорту не буде працювати.
        # return
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---


    logger.info("🚀 Запуск Telegram бота...")

    bot = TransportBot(TELEGRAM_BOT_TOKEN)
    await bot.start()


if __name__ == "__main__":
    # --- ПОЧАТОК ВИПРАВЛЕННЯ ---
    # 3. Використовуємо async-версію запуску
    import asyncio
    asyncio.run(main())
    # --- КІНЕЦЬ ВИПРАВЛЕННЯ ---
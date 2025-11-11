import logging
from config.settings import TELEGRAM_BOT_TOKEN, LOG_LEVEL
from bot.bot import TransportBot
from services.cache_service import load_stops_cache

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger(__name__)


async def main():
    """Головна функція запуску бота"""

    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN не встановлено в .env")
        return

    # Це синхронна функція, вона виконається до запуску бота
    try:
        stops_cache = load_stops_cache()
        if not stops_cache["routes"]:
            logger.warning("⚠️ Увага: Кеш зупинок порожній. Функція пошуку не буде працювати.")
    except Exception as e:
        logger.error(f"❌ Не вдалося завантажити кеш зупинок. Помилка: {e}")
        stops_cache = {"routes": {}}  # Створюємо порожній кеш, щоб бот не впав

    logger.info("🚀 Запуск Telegram бота...")

    bot = TransportBot(TELEGRAM_BOT_TOKEN, stops_cache)
    await bot.start()


if __name__ == "__main__":
    bot = TransportBot(TELEGRAM_BOT_TOKEN)
    bot.start()

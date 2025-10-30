
import logging
from config.settings import TELEGRAM_BOT_TOKEN, LOG_LEVEL
from bot.bot import TransportBot

logging.basicConfig(level=getattr(logging, LOG_LEVEL))
logger = logging.getLogger(__name__)


async def main():
    """Головна функція запуску бота"""

    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN не встановлено в .env")
        return

    logger.info("🚀 Запуск Telegram бота...")

    bot = TransportBot(TELEGRAM_BOT_TOKEN)
    await bot.start()


if __name__ == "__main__":
    bot = TransportBot(TELEGRAM_BOT_TOKEN)
    bot.start()

# main.py
import asyncio
from config.settings import TELEGRAM_BOT_TOKEN
from bot.bot import TransportBot
from utils.logger import logger
# --- ДОДАЄМО ІМПОРТ ---
from handlers.accessible_transport_handlers import load_easyway_route_ids


async def main():
    """Головна функція запуску бота"""

    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN не встановлено в .env")
        return

    logger.info("🚀 Запуск Telegram бота...")
    bot = TransportBot(TELEGRAM_BOT_TOKEN)

    # --- ПОЧАТОК НОВОГО БЛОКУ ---
    # Викликаємо завантаження маршрутів ПРЯМО ТУТ, до запуску бота
    logger.info("--- [MAIN] Викликаю load_easyway_route_ids ---")
    try:
        # Ми передаємо об'єкт 'application' (bot.app) у функцію
        await load_easyway_route_ids(bot.app)
        logger.info("--- [MAIN] load_easyway_route_ids ЗАВЕРШЕНО ---")
    except Exception as e:
        logger.error(f"--- [MAIN] КРИТИЧНА ПОМИЛКА під час load_easyway_route_ids: {e} ---", exc_info=True)
        logger.error("--- [MAIN] Бот не буде запущений через помилку завантаження маршрутів. ---")
        return  # Зупиняємо виконання, якщо маршрути не завантажились
    # --- КІНЕЦЬ НОВОГО БЛОКУ ---

    # Тепер запускаємо бота, як у вашій робочій версії
    try:
        await bot.app.initialize()
        await bot.app.updater.start_polling()
        await bot.app.start()

        logger.info("✅ Бот успішно запущений. Натисніть Ctrl+C для зупинки.")
        await asyncio.Event().wait()

    except (KeyboardInterrupt, SystemExit):
        logger.info("ℹ️ Отримано сигнал зупинки. Завершення роботи...")
    except Exception as e:
        logger.error(f"❌ Критична помилка в main (після запуску): {e}", exc_info=True)
    finally:
        if bot.app.updater and bot.app.updater.is_running:
            await bot.app.updater.stop()
        if bot.app.running:
            await bot.app.stop()

        await bot.app.shutdown()
        logger.info("✅ Бот зупинено.")


if __name__ == "__main__":
    asyncio.run(main())
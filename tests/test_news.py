import asyncio
import os
import sys
import uuid

# Встановлюємо тестовий SQLite для локального тестування
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test_news.db"

# Додаємо корінь проєкту в python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import init_db
from services.news_service import NewsService, format_kyiv_time
from handlers.command_handlers import get_main_menu_keyboard

news_service = NewsService()


async def run_news_tests() -> None:
    print("🧪 [TEST] Ініціалізація бази даних...")
    await init_db()
    print("   ✅ Таблиці та індекси успішно ініціалізовано")

    unique_marker = uuid.uuid4().hex[:8]
    test_text_1 = f"Тестова новина 1 [{unique_marker}]: Ремонт колії на вул. Преображенській"
    test_text_2 = f"Тестова новина 2 [{unique_marker}]: Зміна руху трамваю №5"

    print("🧪 [TEST 1] Збереження розсилки у новини (save_broadcast_news)")
    news_1 = await news_service.save_broadcast_news({
        "admin_id": 12345678,
        "admin_name": "Адмін Валентин",
        "text": test_text_1,
        "media_type": None,
        "media_file_id": None,
        "sent_count": 0,
        "blocked_count": 0
    })
    assert news_1.id is not None
    assert news_1.is_active is True
    assert news_1.text == test_text_1
    print(f"   ✅ Новину #{news_1.id} створено з is_active=True")

    print("🧪 [TEST 2] Оновлення статистики розсилки (update_broadcast_stats)")
    await news_service.update_broadcast_stats(news_id=news_1.id, sent_count=150, blocked_count=3)
    updated_news_1 = await news_service.get_news_by_id(news_1.id)
    assert updated_news_1 is not None
    assert updated_news_1.sent_count == 150
    assert updated_news_1.blocked_count == 3
    print(f"   ✅ Статистика оновлена: sent=150, blocked=3")

    print("🧪 [TEST 3] Створення другої новини з фото")
    news_2 = await news_service.save_broadcast_news({
        "admin_id": 87654321,
        "admin_name": "Адмін Тетяна",
        "text": test_text_2,
        "media_type": "photo",
        "media_file_id": "test_file_id_abc123",
        "sent_count": 200,
        "blocked_count": 1
    })
    assert news_2.id is not None
    assert news_2.media_type == "photo"
    assert news_2.media_file_id == "test_file_id_abc123"
    print(f"   ✅ Новину #{news_2.id} з фото успішно створено")

    print("🧪 [TEST 4] Отримання активних новин для пасажирів (get_active_news)")
    active_result = await news_service.get_active_news(limit=10, offset=0)
    active_ids = [item.id for item in active_result["items"]]
    assert news_1.id in active_ids
    assert news_2.id in active_ids
    print(f"   ✅ Обидві новини присутні у списку активних новин ({len(active_ids)} шт)")

    print("🧪 [TEST 5] Перемикання статусу актуальності на Неактивна (toggle_news_active)")
    new_status = await news_service.toggle_news_active(news_1.id)
    assert new_status is False
    check_news_1 = await news_service.get_news_by_id(news_1.id)
    assert check_news_1.is_active is False

    active_result_after_toggle = await news_service.get_active_news(limit=10, offset=0)
    active_ids_after = [item.id for item in active_result_after_toggle["items"]]
    assert news_1.id not in active_ids_after, "Неактивна новина не повинна бути у списку пасажирів!"
    assert news_2.id in active_ids_after
    print("   ✅ Новина #1 успішно прихована від пасажирів після зміни статусу")

    print("🧪 [TEST 6] Перевірка адмінського архіву (get_news_archive)")
    archive_result = await news_service.get_news_archive(limit=10, offset=0)
    archive_ids = [item.id for item in archive_result["items"]]
    assert news_1.id in archive_ids, "В архіві адміна мають бути ВСІ новини, включаючи неактивні"
    assert news_2.id in archive_ids
    print(f"   ✅ Архів містить усі новини (всього: {archive_result['total_count']})")

    print("🧪 [TEST 7] Повернення новини в актуальні (toggle_news_active -> True)")
    new_status_back = await news_service.toggle_news_active(news_1.id)
    assert new_status_back is True
    active_result_restored = await news_service.get_active_news(limit=10, offset=0)
    restored_ids = [item.id for item in active_result_restored["items"]]
    assert news_1.id in restored_ids, "Новина має знову з'явитися у списку пасажирів"
    print("   ✅ Новина #1 успішно відновлена в активних новинах")

    print("🧪 [TEST 8] Перевірка кнопки '📢 Оперативні новини' у головному меню")
    keyboard = await get_main_menu_keyboard(user_id=12345)
    all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
    news_btn = next((b for b in all_buttons if b.callback_data == "news_client_list:0"), None)
    assert news_btn is not None, "Кнопка '📢 Оперативні новини' повинна бути у головному меню!"
    assert "Оперативні новини" in news_btn.text
    print(f"   ✅ Кнопка знайдена: '{news_btn.text}' (callback_data='{news_btn.callback_data}')")

    print("\n🎉 УСІ 8 ТЕСТІВ УСПІШНО ПРОЙДЕНО БЕЗ ПОМИЛОК!")


if __name__ == "__main__":
    asyncio.run(run_news_tests())

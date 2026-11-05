import asyncio
import os
import sys
import uuid

# Встановлюємо тестовий SQLite для локального тестування
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test_news.db"

# Додаємо корінь проєкту в python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import init_db
from services.news_service import NewsService, format_kyiv_time, extract_news_title
from handlers.command_handlers import get_main_menu_keyboard
from handlers.news_handlers import build_news_broadcast_alert
from config.messages import NEWS_BROADCAST_ALERT, format_news_broadcast_alert

news_service = NewsService()


async def run_news_tests() -> None:
    print("🧪 [TEST] Ініціалізація бази даних...")
    await init_db()
    print("   ✅ Таблиці та індекси успішно ініціалізовано")

    unique_marker = uuid.uuid4().hex[:8]
    test_title_1 = f"Ремонт колії на вул. Преображенській [{unique_marker}]"
    test_text_1 = f"Детальний опис ремонту колії на вул. Преображенській: рух тимчасово змінено."
    test_title_2 = f"Зміна руху трамваю №5 [{unique_marker}]"
    test_text_2 = f"Трамвай №5 прямуватиме через парк Шевченка."

    print("🧪 [TEST 1] Збереження розсилки у новини з заголовком (save_broadcast_news)")
    news_1 = await news_service.save_broadcast_news({
        "admin_id": 12345678,
        "admin_name": "Адмін Валентин",
        "title": test_title_1,
        "text": test_text_1,
        "media_type": None,
        "media_file_id": None,
        "sent_count": 0,
        "blocked_count": 0
    })
    assert news_1.id is not None
    assert news_1.is_active is True
    assert news_1.title == test_title_1
    assert news_1.text == test_text_1
    print(f"   ✅ Новину #{news_1.id} створено з title='{news_1.title}' та is_active=True")

    print("🧪 [TEST 2] Оновлення статистики розсилки (update_broadcast_stats)")
    await news_service.update_broadcast_stats(news_id=news_1.id, sent_count=150, blocked_count=3)
    updated_news_1 = await news_service.get_news_by_id(news_1.id)
    assert updated_news_1 is not None
    assert updated_news_1.sent_count == 150
    assert updated_news_1.blocked_count == 3
    print(f"   ✅ Статистика оновлена: sent=150, blocked=3")

    print("🧪 [TEST 3] Створення другої новини з фото та заголовком")
    news_2 = await news_service.save_broadcast_news({
        "admin_id": 87654321,
        "admin_name": "Адмін Тетяна",
        "title": test_title_2,
        "text": test_text_2,
        "media_type": "photo",
        "media_file_id": "test_file_id_abc123",
        "sent_count": 200,
        "blocked_count": 1
    })
    assert news_2.id is not None
    assert news_2.title == test_title_2
    assert news_2.media_type == "photo"
    assert news_2.media_file_id == "test_file_id_abc123"
    print(f"   ✅ Новину #{news_2.id} з фото та title='{news_2.title}' успішно створено")

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

    print("🧪 [TEST 9] Перевірка формування сповіщення (build_news_broadcast_alert) з фокусом на заголовку")
    custom_title = "Тимчасове перекриття вул. Рішельєвської"
    alert_payload = build_news_broadcast_alert(title=custom_title, news_id=42)
    assert "text" in alert_payload
    assert "reply_markup" in alert_payload
    assert custom_title in alert_payload["text"]
    assert "«📢 Оперативні новини»" in alert_payload["text"]

    # Перевірка відсутності шапки та попередження про автовидалення
    assert "ОПЕРАТИВНА ІНФОРМАЦІЯ | КП «ОМЕТ»" not in alert_payload["text"]
    assert "автоматично видалиться через 5 хвилин" not in alert_payload["text"]

    # Кнопки: має бути лише одна кнопка "Зрозуміло", без кнопки "Читати новину" чи інших
    alert_buttons = [btn for row in alert_payload["reply_markup"].inline_keyboard for btn in row]
    assert len(alert_buttons) == 1, "Сповіщення має містити рівно 1 кнопку: '🗑 Зрозуміло'!"

    dismiss_btn = alert_buttons[0]
    assert dismiss_btn.text == "🗑 Зрозуміло"
    assert dismiss_btn.callback_data == "delete_message"
    print("   ✅ Сповіщення починається із заголовка, не містить зайвих шапок і містить лише кнопку '🗑 Зрозуміло'")

    print("🧪 [TEST 10] Перевірка дефолтного сповіщення без заголовка")
    default_payload = build_news_broadcast_alert()
    assert "Оперативні зміни в роботі електротранспорту" in default_payload["text"]
    assert "ОПЕРАТИВНА ІНФОРМАЦІЯ | КП «ОМЕТ»" not in default_payload["text"]
    assert "автоматично видалиться через 5 хвилин" not in default_payload["text"]
    default_buttons = [btn for row in default_payload["reply_markup"].inline_keyboard for btn in row]
    assert len(default_buttons) == 1
    assert default_buttons[0].callback_data == "delete_message"
    print("   ✅ Дефолтне сповіщення успішно сформовано без зайвих блоків")

    print("🧪 [TEST 11] Перевірка автоматичного вилучення заголовка (extract_news_title)")
    # Порожній або відсутній текст
    assert extract_news_title(None) == "Оперативні зміни в роботі електротранспорту"
    assert extract_news_title("") == "Оперативні зміни в роботі електротранспорту"

    # Реальний кейс: перший рядок без крапки + другий абзац з «вул.
    user_example = (
        "🚋 6 листопада 2026 року тимчасово зміниться рух трамваїв № 1 та № 7\n\n"
        "У зв’язку з технічними роботами ДТЕК рух трамваїв на ділянці «вул. Чорноморського козацтва — завод «Центроліт»» буде тимчасово призупинено.\n\n"
        "🔹 Трамвай № 1 тимчасово не курсуватиме.\n"
        "🔹 Трамвай № 7 курсуватиме за скороченим маршрутом «11-та станція Люстдорфської дороги — Херсонський сквер».\n\n"
        "Про відновлення руху за звичними маршрутами повідомимо додатково."
    )
    extracted_user = extract_news_title(user_example)
    assert extracted_user == "🚋 6 листопада 2026 року тимчасово зміниться рух трамваїв № 1 та № 7", f"Отримано: '{extracted_user}'"
    print("   ✅ Реальний приклад із заголовком без крапки та «вул. опрацьовано на 100% правильно")

    # Короткий текст
    short_text = "Тимчасово змінено маршрут тролейбуса №9."
    assert extract_news_title(short_text) == short_text

    # Перше коротке + друге речення (не розриваючи вул.)
    multi_sent = "Увага! Тимчасово призупинено рух трамваїв №1 та №7 через аварію на вул. Чорноморського козацтва. Вагони курсують до Лузанівки."
    extracted = extract_news_title(multi_sent)
    assert extracted.startswith("Увага! Тимчасово призупинено рух трамваїв №1 та №7")
    assert "вул. Чорноморського козацтва" in extracted
    assert len(extracted) <= 140

    # Дуже довге перше речення
    long_sent = "Попередження про сильний вітер та падіння гілок на контактну мережу в Приморському районі міста Одеси, у зв'язку з чим рух тролейбусів номер 7 тимчасово скеровано іншим маршрутом через залізничний вокзал."
    extracted_long = extract_news_title(long_sent)
    assert len(extracted_long) <= 140
    assert extracted_long.endswith("...")
    print("   ✅ Автоматичне зчитування заголовків з 1-2 речень працює бездоганно")

    print("\n🎉 УСІ 11 ТЕСТІВ УСПІШНО ПРОЙДЕНО БЕЗ ПОМИЛОК!")


def test_news_suite():
    asyncio.run(run_news_tests())


if __name__ == "__main__":
    asyncio.run(run_news_tests())


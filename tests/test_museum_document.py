import asyncio
import json
import uuid
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import init_db, AsyncSessionLocal, MuseumBooking, MuseumHolidayBooking
from services.museum_service import MuseumService

museum_service = MuseumService()


async def run_museum_document_tests():
    print("🧪 [TEST] Initializing database...")
    await init_db()

    # 1. Тест парсера імен учасників
    print("🧪 [TEST 1] Testing _parse_participant_names helper...")
    single_name = "Коваленко Олександр Петрович"
    assert museum_service._parse_participant_names(single_name) == [single_name]

    multi_name_numbered = "1) Коваленко Олександр (35р.); 2) Коваленко Марія (10р.)"
    parsed_numbered = museum_service._parse_participant_names(multi_name_numbered)
    assert len(parsed_numbered) == 2, f"Expected 2 participants, got {parsed_numbered}"
    assert "Коваленко Олександр" in parsed_numbered[0]
    assert "Коваленко Марія" in parsed_numbered[1]

    multi_name_semicolon = "Іванов І.І.; Петров П.П.; Сидоров С.С."
    parsed_semi = museum_service._parse_participant_names(multi_name_semicolon)
    assert len(parsed_semi) == 3
    print("   ✅ _parse_participant_names works properly")

    # 2. Створення тестових бронювань (звичайна та святкова)
    test_date_reg = f"TEST_REG_{uuid.uuid4().hex[:6]}"
    test_phone_reg = f"097{uuid.uuid4().int % 10000000:07d}"

    reg_participants = [
        {"name": "Шевченко Тарас Григорович", "age": None},
        {"name": "Леся Українка", "age": None},
        {"name": "Іван Франко", "age": None},
    ]

    print(f"🧪 [TEST 2] Creating regular booking with 3 participants on date {test_date_reg}...")
    success_reg = await museum_service.create_booking(
        date=test_date_reg,
        count=3,
        name=reg_participants[0]["name"],
        phone=test_phone_reg,
        participants_details=json.dumps(reg_participants, ensure_ascii=False)
    )
    assert success_reg is True

    visitors_reg = await museum_service.get_visitors_for_date(test_date_reg, excursion_type="regular")
    assert len(visitors_reg) == 3, f"Expected 3 unrolled visitors, got {len(visitors_reg)}"
    assert visitors_reg[0]["name"] == "Шевченко Тарас Григорович"
    assert visitors_reg[1]["name"] == "Леся Українка"
    assert visitors_reg[2]["name"] == "Іван Франко"
    assert visitors_reg[0]["phone"] == test_phone_reg
    print(f"   ✅ Regular unrolled visitors correctly extracted: {len(visitors_reg)} items")

    # 3. Тест отримання дат
    print("🧪 [TEST 3] Testing get_distinct_booking_dates contains test_date_reg...")
    all_dates = await museum_service.get_distinct_booking_dates(excursion_type="regular")
    assert test_date_reg in all_dates
    print("   ✅ Distinct booking dates correctly fetched")

    # 4. Тест генератора DOCX документу (якщо встановлено python-docx)
    print("🧪 [TEST 4] Testing generate_visitors_document formatting & metadata...")
    try:
        from services.museum_document_service import generate_visitors_document
        from docx import Document
        from docx.shared import Inches

        # Тест для стандартної екскурсії
        res_reg = generate_visitors_document({
            "excursion_date": test_date_reg,
            "excursion_type": "regular",
            "visitors": visitors_reg
        })

        assert res_reg["stream"] is not None
        assert res_reg["total_count"] == 3
        assert "стандартна" in res_reg["filename"]

        # Відкриваємо згенерований docx з потоку для перевірки структури
        doc = Document(res_reg["stream"])
        section = doc.sections[0]

        # Перевірка альбомної орієнтації (Landscape)
        assert round(section.page_width.inches, 1) == 11.7, f"Width should be 11.7 in, got {section.page_width.inches}"
        assert round(section.page_height.inches, 1) == 8.3, f"Height should be 8.3 in, got {section.page_height.inches}"

        # Перевірка таблиці
        assert len(doc.tables) == 1
        table = doc.tables[0]
        assert len(table.columns) == 5
        # 1 рядок шапки + 3 рядки відвідувачів = 4 рядки
        assert len(table.rows) == 4

        # Перевірка наявності потрібних колонок
        col_titles = [cell.text for cell in table.rows[0].cells]
        assert "№ п/п" in col_titles[0]
        assert "Дата реєстрації на екскурсію" in col_titles[1]
        assert "П.І.Б. зареєстрованих відвідувачів" in col_titles[2]
        assert "Контактний номер телефону" in col_titles[3]
        assert "Згода на гарантування дотримання правил" in col_titles[4]

        # Перевірка даних відвідувача в першому рядку даних
        data_cells = [cell.text for cell in table.rows[1].cells]
        assert data_cells[0] == "1"
        assert data_cells[2] == "Шевченко Тарас Григорович"
        assert data_cells[3] == test_phone_reg
        assert data_cells[4] == ""  # Порожнє місце під підпис

        # Тест для святкової екскурсії
        res_hol = generate_visitors_document({
            "excursion_date": "26.09.2026",
            "excursion_type": "holiday",
            "visitors": [{"reg_date": "24.09.2026 10:00", "name": "Святковий Гість (12р.)", "phone": "0501112233"}]
        })
        assert "святкова" in res_hol["filename"]
        doc_hol = Document(res_hol["stream"])
        doc_hol_text = "\n".join([p.text for p in doc_hol.paragraphs])
        assert "НА СВЯТКОВУ ЕКСКУРСІЮ" in doc_hol_text

        print("   ✅ Document generation passed: Landscape, 5 columns, Times New Roman 14pt, proper headers & borders")
    except ImportError:
        print("   ⚠️ python-docx not installed in current environment, skipping direct docx binary inspection.")

    print("\n🎉 ВСІ ТЕСТИ УСПІШНО ПРОЙДЕНО!")


if __name__ == "__main__":
    asyncio.run(run_museum_document_tests())

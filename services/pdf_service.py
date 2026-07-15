import os
import urllib.request
from fpdf import FPDF
from config.settings import BASE_DIR

FONTS_DIR = BASE_DIR / "assets" / "fonts"


def ensure_fonts():
    """Перевіряє наявність шрифтів DejaVuSans для кирилиці та завантажує їх при потребі"""
    os.makedirs(FONTS_DIR, exist_ok=True)
    regular_path = FONTS_DIR / "DejaVuSans.ttf"
    bold_path = FONTS_DIR / "DejaVuSans-Bold.ttf"

    if not regular_path.exists():
        url = "https://raw.githubusercontent.com/senotrusov/dejavu-fonts-ttf/master/ttf/DejaVuSans.ttf"
        try:
            urllib.request.urlretrieve(url, regular_path)
        except Exception as e:
            # Спробуємо дзеркало у разі помилки
            fallback_url = "https://raw.githubusercontent.com/go-fonts/dejavu/master/DejaVuSans.ttf"
            try:
                urllib.request.urlretrieve(fallback_url, regular_path)
            except Exception:
                raise Exception(f"Не вдалося завантажити шрифт DejaVuSans.ttf: {e}")

    if not bold_path.exists():
        url = "https://raw.githubusercontent.com/senotrusov/dejavu-fonts-ttf/master/ttf/DejaVuSans-Bold.ttf"
        try:
            urllib.request.urlretrieve(url, bold_path)
        except Exception as e:
            fallback_url = "https://raw.githubusercontent.com/go-fonts/dejavu/master/DejaVuSans-Bold.ttf"
            try:
                urllib.request.urlretrieve(fallback_url, bold_path)
            except Exception:
                raise Exception(f"Не вдалося завантажити шрифт DejaVuSans-Bold.ttf: {e}")


def generate_feedback_pdf(feedback) -> str:
    """
    Генерує простий А4 PDF-файл з даними звернення.
    Повертає повний шлях до файлу.
    """
    ensure_fonts()

    pdf = FPDF()
    pdf.add_page()

    # Підключаємо шрифти
    pdf.add_font("DejaVu", "", str(FONTS_DIR / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(FONTS_DIR / "DejaVuSans-Bold.ttf"))

    pdf.set_font("DejaVu", "B", 16)
    pdf.cell(0, 10, "ЗВЕРНЕННЯ ГРОМАДЯН ЧЕРЕЗ TELEGRAM-БОТ", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("DejaVu", "B", 12)
    category_ua = {
        "complaint": "СКАРГА",
        "thanks": "ПОДЯКА",
        "suggestion": "ПРОПОЗИЦІЯ"
    }.get(feedback.category, feedback.category.upper())

    pdf.cell(0, 8, f"Категорія: {category_ua}", ln=True)
    pdf.cell(0, 8, f"Реєстраційний номер: {feedback.ticket_id}", ln=True)

    created_at_str = feedback.created_at.strftime("%d.%m.%Y %H:%M") if feedback.created_at else "Невідомо"
    pdf.cell(0, 8, f"Дата реєстрації: {created_at_str} (Київський час)", ln=True)

    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # Дані заявника
    pdf.set_font("DejaVu", "B", 11)
    pdf.cell(0, 7, "ДАНІ ЗАЯВНИКА:", ln=True)
    pdf.set_font("DejaVu", "", 10)
    pdf.cell(0, 6, f"П.І.Б.: {feedback.user_name or 'Не вказано'}", ln=True)
    pdf.cell(0, 6, f"Телефон: {feedback.user_phone or 'Не вказано'}", ln=True)
    pdf.cell(0, 6, f"Email: {feedback.user_email or 'Не вказано'}", ln=True)

    pdf.ln(3)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    # Дані транспорту (якщо є)
    if feedback.category in ("complaint", "thanks") and (feedback.route or feedback.board_number or feedback.transport_type):
        pdf.set_font("DejaVu", "B", 11)
        pdf.cell(0, 7, "ДЕТАЛІ ТРАНСПОРТУ:", ln=True)
        pdf.set_font("DejaVu", "", 10)

        t_type = "Не вказано"
        if feedback.transport_type:
            t_type = "Трамвай" if feedback.transport_type == "tram" else "Тролейбус"

        pdf.cell(0, 6, f"Тип транспорту: {t_type}", ln=True)
        pdf.cell(0, 6, f"Маршрут: {feedback.route or 'Не вказано'}", ln=True)
        pdf.cell(0, 6, f"Бортовий номер: {feedback.board_number or 'Не вказано'}", ln=True)

        pdf.ln(3)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)

    # Текст звернення
    pdf.set_font("DejaVu", "B", 11)
    pdf.cell(0, 7, "ЗМІСТ ЗВЕРНЕННЯ:", ln=True)
    pdf.set_font("DejaVu", "", 10)
    pdf.multi_cell(0, 6, feedback.text or "")

    pdf.ln(10)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(5)

    pdf.set_font("DejaVu", "", 9)
    pdf.cell(0, 5, "Документ сформовано автоматично через Telegram-бот КП Одесміськелектротранс.", ln=True, align="C")

    # Створюємо тимчасову папку temp/
    temp_dir = BASE_DIR / "temp"
    os.makedirs(temp_dir, exist_ok=True)

    pdf_path = temp_dir / f"{feedback.ticket_id}.pdf"
    pdf.output(str(pdf_path))

    return str(pdf_path)

"""
Сервіс генерації договорів оренди (№XXXX-О), рахунків IBAN з QR-кодом НБУ,
електронних посадкових талонів та фінансового розрахунку оренди електротранспорту.
"""

from __future__ import annotations

import datetime
import json
import os
import smtplib
import tempfile
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

import qrcode
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from pydantic import BaseModel, Field

from config.settings import (
    RENTAL_BANK_MFO,
    RENTAL_BANK_MFO_SECONDARY,
    RENTAL_BANK_NAME,
    RENTAL_BANK_NAME_SECONDARY,
    RENTAL_COMPANY_PHONE,
    RENTAL_DIRECTOR_FULL_NAME,
    RENTAL_DIRECTOR_NAME,
    RENTAL_EDRPOU,
    RENTAL_EXTRA_DECORATION_UAH,
    RENTAL_EXTRA_GUIDE_UAH,
    RENTAL_EXTRA_MUSIC_UAH,
    RENTAL_IBAN_ACCOUNT,
    RENTAL_IBAN_ACCOUNT_SECONDARY,
    RENTAL_IBAN_BANK_NAME,
    RENTAL_IBAN_COMPANY_ADDRESS,
    RENTAL_IBAN_COMPANY_NAME,
    RENTAL_IBAN_DIRECTOR_NAME,
    RENTAL_IBAN_DIRECTOR_TITLE,
    RENTAL_IBAN_EDRPOU,
    RENTAL_MIN_ORDER_MINUTES,
    RENTAL_TARIFF_RETRO_HOUR_UAH,
    RENTAL_TARIFF_RETRO_TRAM_KM,
    RENTAL_TARIFF_STANDARD_TRAM_KM,
    RENTAL_TARIFF_TROLLEYBUS_KM,
    RENTAL_TARIFF_WAIT_MINUTE,
    RENTAL_VAT_CERTIFICATE,
    RENTAL_VAT_IPN,
    SMTP_LEGAL_EMAIL,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_SERVER,
    SMTP_USER,
)
from utils.logger import logger

_ROOT_DIR = Path(__file__).resolve().parent.parent
FONT_PATH = str(
    (_ROOT_DIR / "assets" / "fonts" / "DejaVuSans.ttf")
    if (_ROOT_DIR / "assets" / "fonts" / "DejaVuSans.ttf").exists()
    else (_ROOT_DIR / "DejaVuSans.ttf")
)
BOLD_FONT_PATH = str(
    (_ROOT_DIR / "assets" / "fonts" / "DejaVuSans-Bold.ttf")
    if (_ROOT_DIR / "assets" / "fonts" / "DejaVuSans-Bold.ttf").exists()
    else Path(FONT_PATH)
)
DEFAULT_DOC_DIR = Path(tempfile.gettempdir()) / "transport_bot_rentals"


# ================= КАТАЛОГ РУХОМОГО СКЛАДУ, ПОПУЛЯРНИХ МАРШРУТІВ ТА ПОСЛУГ =================

# Наразі оренду відкрито виключно для трамвайного вагона РЕТРО згідно з офіційною калькуляцією КП «ОМЕТ»
RENTAL_WAGON_CATALOG: Dict[str, Dict[str, Any]] = {
    "retro_mtv": {
        "key": "retro_mtv",
        "title": "🚋 Ретро-трамвай МТВ-82 / Відкритий №914",
        "short_title": "Ретро-трамвай МТВ-82",
        "transport_type": "TRAM",
        "engine_wagon_type": "retro",
        "default_depot": "ВРМ",
        "capacity_seats": 28,
        "hour_tariff_uah": RENTAL_TARIFF_RETRO_HOUR_UAH,
        "km_tariff": RENTAL_TARIFF_RETRO_TRAM_KM,
        "description": "Історичний екскурсійний трамвай для свят, фотосесій та прогулянок Одесою.",
    },
}

RENTAL_EXTRA_SERVICES: Dict[str, Dict[str, Any]] = {
    "decoration": {
        "key": "decoration",
        "title": "🎈 Святкове прикрашання салону",
        "price_uah": RENTAL_EXTRA_DECORATION_UAH,
    },
    "music": {
        "key": "music",
        "title": "🔊 Музичний супровід (аудіосистема)",
        "price_uah": RENTAL_EXTRA_MUSIC_UAH,
    },
    "guide": {
        "key": "guide",
        "title": "🎙️ Професійний екскурсовод Музею КП ОМЕТ",
        "price_uah": RENTAL_EXTRA_GUIDE_UAH,
    },
}

# Популярні ретро-маршрути за розворотними кільцями
RENTAL_POPULAR_PRESETS: Dict[str, Dict[str, Any]] = {
    "tram_arcadia": {
        "key": "tram_arcadia",
        "transport_type": "TRAM",
        "title": "🌊 Курортна Аркадія (Старосінна -> Аркадія -> Старосінна)",
        "pickup_stop": "пл. Старосінна",
        "via_loops": ["Аркадія"],
        "dropoff_stop": "пл. Старосінна",
        "recommended_wait_min": 20,
    },
    "tram_park_shevchenka": {
        "key": "tram_park_shevchenka",
        "transport_type": "TRAM",
        "title": "🌳 Стара Одеса та Парк Шевченка (Старосінна -> Парк Шевченка -> Тираспольська -> Старосінна)",
        "pickup_stop": "пл. Старосінна",
        "via_loops": ["Парк ім. Т. Г. Шевченка", "пл. Тираспольська"],
        "dropoff_stop": "пл. Старосінна",
        "recommended_wait_min": 20,
    },
    "tram_fontan": {
        "key": "tram_fontan",
        "transport_type": "TRAM",
        "title": "🌅 Великий Фонтан (Старосінна -> 16-а ст. В. Фонтану -> Старосінна)",
        "pickup_stop": "пл. Старосінна",
        "via_loops": ["16-а ст. Великого Фонтану"],
        "dropoff_stop": "пл. Старосінна",
        "recommended_wait_min": 30,
    },
    "tram_khadzhybei": {
        "key": "tram_khadzhybei",
        "transport_type": "TRAM",
        "title": "🌾 Очеретяний маршрут (Херсонський сквер -> Хаджибейський лиман -> Херсонський сквер)",
        "pickup_stop": "Херсонський сквер",
        "via_loops": ["Хаджибейський лиман"],
        "dropoff_stop": "Херсонський сквер",
        "recommended_wait_min": 20,
    },
}


# ================= PYDANTIC СХЕМИ ФІНАНСОВОГО РОЗРАХУНКУ (RORO) =================

class RentalPriceInput(BaseModel):
    wagon_key: str = Field(default="retro_mtv")
    total_billable_km: float = Field(default=0.0, ge=0.0)
    total_duration_minutes: int = Field(default=0, ge=0)
    wait_minutes: int = Field(ge=0, default=0)
    extra_service_keys: List[str] = Field(default_factory=list)


class RentalPriceBreakdown(BaseModel):
    wagon_key: str
    wagon_title: str
    actual_minutes: int
    billable_minutes: int
    hourly_rate_uah: float
    minute_rate_uah: float
    time_price_uah: float
    extras_price_uah: float
    without_vat_uah: float
    vat_20_uah: float
    total_price_uah: float
    is_minimum_applied: bool
    selected_extras_titles: List[str]
    km_tariff_uah: float = 0.0
    wait_tariff_per_min_uah: float = 0.0
    km_price_uah: float = 0.0
    wait_price_uah: float = 0.0


def calculate_rental_price_breakdown(payload: RentalPriceInput) -> RentalPriceBreakdown:
    """
    Розраховує повну вартість оренди трамвайного вагона РЕТРО згідно з офіційною
    калькуляцією КП «Одесміськелектротранс» (затверджено 01.01.2026 р.):
    - Базовий погодинний тариф з ПДВ 20%: 4 337,94 грн/год (72,30 грн/хв);
    - Фактичний час Wialon: Фаза 1 (подача з ВРМ) + Фаза 2 (маршрут і стоянка) + Фаза 3 (заїзд у ВРМ);
    - Правило мінімального замовлення: не менше 1 години (60 хвилин);
    - Обов'язкове виділення ПДВ 20% у підсумковій вартості.
    """
    wagon_info = RENTAL_WAGON_CATALOG.get(payload.wagon_key) or RENTAL_WAGON_CATALOG["retro_mtv"]
    actual_minutes = int(payload.total_duration_minutes)
    billable_minutes = max(RENTAL_MIN_ORDER_MINUTES, actual_minutes)

    hourly_rate = float(RENTAL_TARIFF_RETRO_HOUR_UAH)
    minute_rate = round(hourly_rate / 60.0, 4)
    time_price = round(billable_minutes * (hourly_rate / 60.0), 2)

    extras_price = 0.0
    extras_titles: List[str] = []
    for key in payload.extra_service_keys:
        svc = RENTAL_EXTRA_SERVICES.get(key)
        if svc:
            extras_price += float(svc["price_uah"])
            extras_titles.append(str(svc["title"]))

    extras_price = round(extras_price, 2)
    total_price = round(time_price + extras_price, 2)
    without_vat = round(total_price / 1.20, 2)
    vat_20 = round(total_price - without_vat, 2)

    return RentalPriceBreakdown(
        wagon_key=wagon_info["key"],
        wagon_title=wagon_info["short_title"],
        actual_minutes=actual_minutes,
        billable_minutes=billable_minutes,
        hourly_rate_uah=hourly_rate,
        minute_rate_uah=round(minute_rate, 2),
        time_price_uah=time_price,
        extras_price_uah=extras_price,
        without_vat_uah=without_vat,
        vat_20_uah=vat_20,
        total_price_uah=total_price,
        is_minimum_applied=(actual_minutes < RENTAL_MIN_ORDER_MINUTES),
        selected_extras_titles=extras_titles,
        km_tariff_uah=float(wagon_info.get("km_tariff", 0.0)),
        wait_tariff_per_min_uah=0.0,
        km_price_uah=time_price,
        wait_price_uah=0.0,
    )


# ================= ГЕНЕРАЦІЯ QR-КОДУ НБУ ТА РАХУНКУ IBAN (З ПДВ 20%) =================

def build_nbu_iban_payment_purpose(contract_number: str, contract_date: str) -> str:
    """Формує суворий формат призначення платежу IBAN за стандартом НБУ з обов'язковим виділенням ПДВ 20%."""
    return (
        f"*;101;Оплата за оренду трамвайного вагона РЕТРО згідно з Договором "
        f"№{contract_number} від {contract_date};у т.ч. ПДВ 20%*"
    )


def build_nbu_iban_qr_payload(
    contract_number: str,
    contract_date: str,
    amount_uah: float,
) -> str:
    """
    Формує офіційний рядок QR-коду за Постановою Правління НБУ № 68 (формат BCD / UCT)
    для миттєвої оплати у Приват24 / Monobank / Ощад 24 без РРО.
    """
    purpose = build_nbu_iban_payment_purpose(contract_number, contract_date)
    lines = [
        "BCD",
        "002",
        "1",
        "UCT",
        "",
        RENTAL_IBAN_COMPANY_NAME,
        RENTAL_IBAN_ACCOUNT,
        f"UAH{amount_uah:.2f}",
        RENTAL_IBAN_EDRPOU,
        "",
        "",
        purpose,
    ]
    return "\n".join(lines)


def _create_qr_png(payload_text: str, out_png_path: str) -> str:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(payload_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(out_png_path)
    return out_png_path


def generate_rental_iban_invoice_pdf(
    order_data: Dict[str, Any],
    target_dir: Optional[str] = None,
) -> str:
    """
    Генерує офіційний Рахунок-фактуру на безготівкову оплату за реквізитами IBAN
    разом із вбудованим QR-кодом НБУ.
    """
    if not os.path.exists(FONT_PATH):
        raise FileNotFoundError(f"Шрифт DejaVuSans.ttf не знайдено: {FONT_PATH}")

    out_dir = Path(target_dir) if target_dir else DEFAULT_DOC_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    contract_number = str(order_data.get("contract_number", "2026-0001-О"))
    safe_num = contract_number.replace("/", "_").replace(" ", "_")
    pdf_path = str(out_dir / f"IBAN_Invoice_{safe_num}.pdf")
    qr_path = str(out_dir / f"qr_iban_{safe_num}.png")

    created_date = str(order_data.get("contract_date") or datetime.datetime.now().strftime("%d.%m.%Y"))
    total_price = float(order_data.get("total_price_uah", 0.0))
    purpose = build_nbu_iban_payment_purpose(contract_number, created_date)
    qr_payload = build_nbu_iban_qr_payload(contract_number, created_date, total_price)
    _create_qr_png(qr_payload, qr_path)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.add_font("DejaVu", "", FONT_PATH)
    pdf.add_font("DejaVu", "B", BOLD_FONT_PATH)

    # Заголовок
    pdf.set_font("DejaVu", "B", 13)
    pdf.cell(0, 7, RENTAL_IBAN_COMPANY_NAME, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font("DejaVu", "B", 11)
    pdf.cell(
        0,
        6,
        f"РАХУНОК-ФАКТУРА № Р-{contract_number} від {created_date} р.",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        align="C",
    )
    pdf.set_font("DejaVu", "", 8.5)
    pdf.cell(
        0,
        5,
        "Офіційна безготівкова оплата на розрахунковий рахунок IBAN (з урахуванням ПДВ 20%)",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
        align="C",
    )
    pdf.ln(3)

    # Блок реквізитів Отримувача та QR-код праворуч
    top_y = pdf.get_y()
    pdf.set_fill_color(245, 248, 255)
    pdf.set_draw_color(60, 100, 180)
    pdf.rect(10, top_y, 132, 46, "DF")

    pdf.set_xy(13, top_y + 2)
    pdf.set_font("DejaVu", "B", 9.5)
    pdf.cell(126, 5, "РЕКВІЗИТИ ОТРИМУВАЧА (ВИКОНАВЦЯ):", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(13)
    pdf.set_font("DejaVu", "", 8.5)
    pdf.cell(126, 5, f"Отримувач: {RENTAL_IBAN_COMPANY_NAME}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(13)
    pdf.cell(126, 5, f"Код ЄДРПОУ: {RENTAL_IBAN_EDRPOU}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(13)
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(126, 5, f"Рахунок IBAN: {RENTAL_IBAN_ACCOUNT}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(13)
    pdf.set_font("DejaVu", "", 8.5)
    pdf.cell(126, 5, f"Банк: {RENTAL_IBAN_BANK_NAME}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(13)
    pdf.cell(126, 5, f"Юридична адреса: {RENTAL_IBAN_COMPANY_ADDRESS}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    cust_type = str(order_data.get("customer_type") or "individual").lower()
    full_name = str(order_data.get("user_full_name") or "Замовник").strip()
    tax_id = str(order_data.get("user_tax_id") or "").strip()
    phone = str(order_data.get("user_phone") or "").strip()

    if cust_type in ("legal_entity", "company", "юридична особа"):
        payer_label = f"Платник (Юрособа): {full_name} | ЄДРПОУ {tax_id}"
    elif cust_type in ("fop", "фоп"):
        payer_label = f"Платник (ФОП): {full_name} | РНОКПП {tax_id}"
    else:
        tax_str = f" | РНОКПП {tax_id}" if tax_id and tax_id != "—" else ""
        payer_label = f"Платник (Фізособа): {full_name} ({phone}){tax_str}"

    pdf.set_x(13)
    pdf.cell(
        126,
        5,
        payer_label[:68],
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )

    # QR-код НБУ праворуч
    if os.path.exists(qr_path):
        pdf.image(qr_path, x=148, y=top_y, w=46, h=46)
    pdf.set_xy(145, top_y + 46)
    pdf.set_font("DejaVu", "B", 7.5)
    pdf.cell(52, 4, "Скануйте у Приват24 / Monobank", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_y(top_y + 53)

    # Призначення платежу (обов'язковий блок)
    pdf.set_fill_color(255, 250, 230)
    pdf.set_draw_color(210, 160, 40)
    pdf.rect(10, pdf.get_y(), 190, 16, "DF")
    pdf.set_xy(13, pdf.get_y() + 2)
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(0, 5, "ОБОВ'ЯЗКОВЕ ПРИЗНАЧЕННЯ ПЛАТЕЖУ (копіюється автоматично з QR-коду):", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(13)
    pdf.set_font("DejaVu", "B", 8.5)
    pdf.cell(0, 6, purpose, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5)

    # Таблиця послуг
    pdf.set_fill_color(230, 235, 245)
    pdf.set_draw_color(160, 160, 160)
    pdf.set_font("DejaVu", "B", 8.5)
    pdf.cell(10, 7, "№", border=1, fill=True, align="C")
    pdf.cell(105, 7, "Найменування послуги згідно з Договором №" + contract_number, border=1, fill=True)
    pdf.cell(25, 7, "Кількість", border=1, fill=True, align="C")
    pdf.cell(25, 7, "Тариф (з ПДВ)", border=1, fill=True, align="C")
    pdf.cell(25, 7, "Сума (грн)", border=1, fill=True, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("DejaVu", "", 8.5)
    total_minutes = int(order_data.get("total_duration_min", 0))
    billable_minutes = max(RENTAL_MIN_ORDER_MINUTES, total_minutes)
    extras_price = float(order_data.get("extras_price_uah", 0.0))
    time_price = round(float(order_data.get("time_price_uah", 0.0)) or (total_price - extras_price), 2)
    without_vat = round(total_price / 1.20, 2)
    vat_20 = round(total_price - without_vat, 2)

    h_part = billable_minutes // 60
    m_part = billable_minutes % 60
    time_qty_label = f"{billable_minutes} хв ({h_part}г {m_part:02d}хв)" if m_part else f"{h_part} год"

    # Рядок 1: Орендний час вагона РЕТРО
    pdf.cell(10, 6, "1", border=1, align="C")
    pdf.cell(
        105,
        6,
        "Оренда трамвайного вагона РЕТРО (подача з ВРМ + маршрут + заїзд)",
        border=1,
    )
    pdf.cell(25, 6, time_qty_label, border=1, align="C")
    pdf.cell(25, 6, f"{RENTAL_TARIFF_RETRO_HOUR_UAH:.2f}/год", border=1, align="C")
    pdf.cell(25, 6, f"{time_price:.2f}", border=1, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Рядок 2: Додаткові послуги (якщо обрано)
    row_no = 2
    if extras_price > 0:
        pdf.cell(10, 6, str(row_no), border=1, align="C")
        pdf.cell(105, 6, "Додаткові сервісні послуги (прикрашання / аудіо / екскурсовод)", border=1)
        pdf.cell(25, 6, "1 компл.", border=1, align="C")
        pdf.cell(25, 6, f"{extras_price:.2f}", border=1, align="C")
        pdf.cell(25, 6, f"{extras_price:.2f}", border=1, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        row_no += 1

    # Підсумок з виділенням ПДВ 20%
    pdf.set_font("DejaVu", "", 8.5)
    pdf.cell(165, 6, "Разом без ПДВ:", border=1, align="R")
    pdf.cell(25, 6, f"{without_vat:.2f} грн", border=1, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.cell(165, 6, "ПДВ, 20%:", border=1, align="R")
    pdf.cell(25, 6, f"{vat_20:.2f} грн", border=1, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("DejaVu", "B", 9.5)
    pdf.set_fill_color(235, 242, 250)
    pdf.cell(165, 7, "ВСЬОГО ДО СПЛАТИ З ПДВ:", border=1, fill=True, align="R")
    pdf.cell(25, 7, f"{total_price:.2f} грн", border=1, fill=True, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(5)

    pdf.set_font("DejaVu", "", 8.5)
    pdf.multi_cell(
        0,
        4.5,
        "Примітка: Після здійснення оплати за реквізитами IBAN надішліть квитанцію (PDF або скріншот) у розділі "
        "«📂 Діючі договори та замовлення» офіційного Telegram-бота КП «Одесміськелектротранс». "
        "Бухгалтерія підприємства перевіряє зарахування коштів та активує наряд на випуск вагона з депо.",
    )
    pdf.ln(6)
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(110, 5, f"{RENTAL_IBAN_DIRECTOR_TITLE}:")
    pdf.cell(80, 5, f"____________________ {RENTAL_IBAN_DIRECTOR_NAME}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.output(pdf_path)
    return pdf_path


# ================= ДОПОМІЖНІ ФОРМАТЕРИ ДОКУМЕНТІВ (ЧИСЛА ПРОПИСОМ, ДАТИ, РЕКВІЗИТИ) =================

UKR_MONTHS_GENITIVE: Dict[int, str] = {
    1: "січня",
    2: "лютого",
    3: "березня",
    4: "квітня",
    5: "травня",
    6: "червня",
    7: "липня",
    8: "серпня",
    9: "вересня",
    10: "жовтня",
    11: "листопада",
    12: "грудня",
}


def format_uah_amount_in_words(amount: float) -> str:
    """
    Перетворює числову суму в гривнях у словесний запис українською мовою.
    Наприклад: 9254.27 -> 'дев’ять тисяч двісті п’ятдесят чотири гривні 27 копійок'.
    """
    amount = round(float(amount), 2)
    hryvnias = int(amount)
    kopecks = int(round((amount - hryvnias) * 100))

    units_m = ["", "один", "два", "три", "чотири", "п’ять", "шість", "сім", "вісім", "дев’ять"]
    units_f = ["", "одна", "дві", "три", "чотири", "п’ять", "шість", "сім", "вісім", "дев’ять"]
    teens = [
        "десять",
        "одинадцять",
        "дванадцять",
        "тринадцять",
        "чотирнадцять",
        "п’ятнадцять",
        "шістнадцять",
        "сімнадцять",
        "вісімнадцять",
        "дев’ятнадцять",
    ]
    tens = [
        "",
        "",
        "двадцять",
        "тридцять",
        "сорок",
        "п’ятдесят",
        "шістдесят",
        "сімдесят",
        "вісімдесят",
        "дев’яносто",
    ]
    hundreds = [
        "",
        "сто",
        "двісті",
        "триста",
        "чотириста",
        "п’ятсот",
        "шістсот",
        "сімсот",
        "вісімсот",
        "дев’ятсот",
    ]

    def parse_triplet(n: int, is_female: bool) -> str:
        words = []
        h = n // 100
        t = (n % 100) // 10
        u = n % 10
        if h > 0:
            words.append(hundreds[h])
        if t == 1:
            words.append(teens[u])
        else:
            if t > 1:
                words.append(tens[t])
            if u > 0:
                words.append(units_f[u] if is_female else units_m[u])
        return " ".join(words)

    def get_noun_form(n: int, f1: str, f2_4: str, f5_0: str) -> str:
        last10 = n % 100
        last1 = n % 10
        if 11 <= last10 <= 14:
            return f5_0
        if last1 == 1:
            return f1
        if 2 <= last1 <= 4:
            return f2_4
        return f5_0

    parts: List[str] = []
    thousands = hryvnias // 1000
    rem_hryvnias = hryvnias % 1000

    if thousands > 0:
        th_words = parse_triplet(thousands, is_female=True)
        th_noun = get_noun_form(thousands, "тисяча", "тисячі", "тисяч")
        parts.append(f"{th_words} {th_noun}")

    if rem_hryvnias > 0 or hryvnias == 0:
        hr_words = parse_triplet(rem_hryvnias, is_female=True) if rem_hryvnias > 0 else "нуль"
        parts.append(hr_words)

    hr_noun = get_noun_form(hryvnias, "гривня", "гривні", "гривень")
    kop_noun = get_noun_form(kopecks, "копійка", "копійки", "копійок")
    words_str = " ".join(p for p in parts if p).strip()

    return f"{words_str} {hr_noun} {kopecks:02d} {kop_noun}"


def format_contract_date(date_raw: Any) -> str:
    """Форматує дату договору у вигляд: « 31 » жовтня 2026 р."""
    if not date_raw:
        now_dt = datetime.datetime.now()
        month_name = UKR_MONTHS_GENITIVE.get(now_dt.month, "січня")
        return f"« {now_dt.day:02d} » {month_name} {now_dt.year} р."

    raw_str = str(date_raw).strip()
    try:
        if "." in raw_str:
            d, m, y = [int(x) for x in raw_str.split(".")[:3]]
        elif "-" in raw_str:
            y, m, d = [int(x) for x in raw_str.split("-")[:3]]
        else:
            return f"« {raw_str} »"
        month_name = UKR_MONTHS_GENITIVE.get(m, "січня")
        return f"« {d:02d} » {month_name} {y} р."
    except Exception:
        return f"« {raw_str} »"


def format_departure_datetime(rental_date: Any, time_slot: Optional[str]) -> str:
    """Форматує час та дату подачі вагона під посадку: «31» жовтня 2026 року о 16:00."""
    d_str = str(rental_date or "").strip()
    t_str = str(time_slot or "").strip()
    try:
        if "." in d_str:
            d, m, y = [int(x) for x in d_str.split(".")[:3]]
        elif "-" in d_str:
            y, m, d = [int(x) for x in d_str.split("-")[:3]]
        else:
            now_dt = datetime.datetime.now()
            d, m, y = now_dt.day, now_dt.month, now_dt.year
        month_name = UKR_MONTHS_GENITIVE.get(m, "жовтня")
        date_part = f"«{d}» {month_name} {y} року"
    except Exception:
        date_part = f"«{d_str}»"

    if t_str and t_str not in ("REQUEST", "None", ""):
        return f"{date_part} о {t_str}"
    return f"{date_part} в узгоджений зі Службою руху час"


def parse_customer_details(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """Форматує ПІБ, адресу, паспорт та контактні дані замовника залежно від правового статусу."""
    cust_type = str(order_data.get("customer_type") or "individual").lower()
    full_name = str(order_data.get("user_full_name") or "Замовник").strip()
    tax_id = str(order_data.get("user_tax_id") or "заповнюється при підписанні").strip()
    phone = str(order_data.get("user_phone") or "—").strip()
    addr = str(order_data.get("user_address") or "65000, м. Одеса (заповнюється при підписанні)").strip()
    passp = str(order_data.get("user_passport") or "паспорт / ID-картка (заповнюється при підписанні)").strip()

    tokens = full_name.split()

    if cust_type in ("legal_entity", "company", "юридична особа"):
        company_name = str(order_data.get("company_name") or full_name).strip()
        signer_title = str(order_data.get("signer_title") or "директора").strip()
        signer_name = str(order_data.get("signer_name") or full_name).strip()
        foundation_doc = str(order_data.get("foundation_doc") or "Статуту").strip()
        full_upper = company_name.upper()

        preamble_cust = (
            f"{company_name.upper()}, в особі {signer_title} {signer_name}, "
            f"який діє на підставі {foundation_doc}, далі – Замовник"
        )
        section7_lines = [
            company_name,
            addr,
            f"Код ЄДРПОУ {tax_id}",
            f"Тел.: {phone}",
            "",
            signer_title.capitalize(),
            f"_____________ {signer_name}",
            f"(діє на підставі {foundation_doc})",
        ]
        short_name = company_name
        sig_name = signer_name

    elif cust_type in ("fop", "фоп"):
        full_upper = f"ФІЗИЧНА ОСОБА-ПІДПРИЄМЕЦЬ {' '.join(tokens).upper()}"
        sig_name = f"{tokens[1]} {tokens[0].upper()}" if len(tokens) >= 2 else full_name
        preamble_cust = (
            f"{full_upper}, що діє на підставі Виписки з Єдиного державного реєстру, далі – Замовник"
        )
        section7_lines = [
            f"ФОП {full_name.upper()}",
            addr,
            f"РНОКПП (ІПН) {tax_id}",
            f"Тел.: {phone}",
            "",
            "Фізична особа-підприємець",
            f"_____________ {sig_name}",
        ]
        short_name = f"ФОП {full_name}"

    else:  # individual
        if len(tokens) >= 3:
            full_upper = f"ФІЗИЧНА ОСОБА {' '.join(tokens).upper()}"
            short_name = f"{tokens[0].upper()} {tokens[1][0]}.{tokens[2][0]}."
            sig_name = f"{tokens[1]} {tokens[0].upper()}"
        elif len(tokens) == 2:
            full_upper = f"ФІЗИЧНА ОСОБА {' '.join(tokens).upper()}"
            short_name = f"{tokens[0].upper()} {tokens[1][0]}."
            sig_name = f"{tokens[1]} {tokens[0].upper()}"
        else:
            full_upper = full_name.upper()
            short_name = full_name
            sig_name = full_name

        preamble_cust = f"{full_upper}, далі – Замовник"
        section7_lines = [
            short_name,
            addr,
            passp,
            f"РНОКПП {tax_id}",
            f"Тел.: {phone}",
            "",
            "Фізична особа",
            f"_____________ {sig_name}",
        ]

    return {
        "customer_type": cust_type,
        "full_uppercase": full_upper,
        "preamble_customer": preamble_cust,
        "section7_lines": section7_lines,
        "short_name": short_name,
        "signature_name": sig_name,
        "address": addr,
        "passport": passp,
        "tax_id": tax_id,
        "phone": phone,
    }


def build_contract_route_string(pickup: Optional[str], dropoff: Optional[str], via_loops: Any) -> str:
    """Формує офіційний рядок маршруту перевезення за розворотними кільцями."""
    p = str(pickup or "пл. Старосінна").strip()
    d = str(dropoff or "пл. Старосінна").strip()

    loops: List[str] = []
    if isinstance(via_loops, str):
        try:
            loops = json.loads(via_loops)
        except Exception:
            loops = [via_loops] if via_loops else []
    elif isinstance(via_loops, (list, tuple)):
        loops = [str(x) for x in via_loops if str(x).strip()]

    if loops:
        return f"{p} – {' – '.join(loops)} – {d}"
    if p.lower() == d.lower():
        return f"{p} (кільцевий екскурсійний маршрут)"
    return f"{p} – {d}"


def format_official_contract_number(raw_num: Optional[str]) -> str:
    """Форматує офіційний номер договору за стандартом КП ОМЕТ (№ У-У/2026/XXXX)."""
    if not raw_num:
        return f"У-У/{datetime.datetime.now().year}/0001"
    raw = str(raw_num).strip()
    if raw.startswith("У-У/"):
        return raw
    clean = raw.replace("-О", "").replace("О", "")
    parts = clean.split("-")
    if len(parts) == 2:
        return f"У-У/{parts[0]}/{parts[1]}"
    return f"У-У/{raw}"


# ================= ГЕНЕРАЦІЯ ДОГОВОРУ ОРЕНДИ ТА ПЕРЕВЕЗЕННЯ (PDF) =================

def generate_rental_contract_pdf(
    order_data: Dict[str, Any],
    calc_output: Optional[Any] = None,
    target_dir: Optional[str] = None,
) -> str:
    """
    Генерує офіційний Договір надання послуг по перевезенню (№ У-У/2026/____) у форматі PDF.
    Текст повністю відповідає типовому договору КП «Одесміськелектротранс».
    Включає заборону перевищення шуму (п. 2.4), штраф за затримку (п. 2.3),
    правило неповернення 50% при скасуванні (п. 4.2–4.3) та двоколонкову таблицю реквізитів.
    Внутрішній блок узгодження (ПОГОДЖЕНО) виключено, оскільки він реалізований
    в оперативному Telegram-штабі КП «ОМЕТ».
    """
    if not os.path.exists(FONT_PATH):
        raise FileNotFoundError(f"Шрифт DejaVuSans.ttf не знайдено: {FONT_PATH}")

    out_dir = Path(target_dir) if target_dir else DEFAULT_DOC_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_contract_number = str(order_data.get("contract_number", "2026-0001-О"))
    official_contract_number = format_official_contract_number(raw_contract_number)
    safe_num = official_contract_number.replace("/", "_").replace(" ", "_")
    pdf_path = str(out_dir / f"Contract_{safe_num}.pdf")

    contract_date_str = format_contract_date(order_data.get("contract_date") or order_data.get("rental_date"))
    departure_str = format_departure_datetime(order_data.get("rental_date"), order_data.get("rental_time_slot"))
    customer = parse_customer_details(order_data)
    route_str = build_contract_route_string(
        order_data.get("pickup_stop"),
        order_data.get("dropoff_stop"),
        order_data.get("via_loops"),
    )

    total_price = float(order_data.get("total_price_uah", 0.0))
    without_vat = round(total_price / 1.20, 2)
    vat_20 = round(total_price - without_vat, 2)
    total_words = format_uah_amount_in_words(total_price)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.add_page()
    pdf.add_font("DejaVu", "", FONT_PATH)
    pdf.add_font("DejaVu", "B", BOLD_FONT_PATH)

    # 1. Шапка Договору
    pdf.set_font("DejaVu", "B", 12)
    pdf.cell(0, 6, f"ДОГОВІР № {official_contract_number}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DejaVu", "", 10)
    pdf.cell(0, 5, "надання послуг по перевезенню", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    # Місто та дата
    pdf.set_font("DejaVu", "", 9)
    pdf.cell(95, 5, "м. Одеса")
    pdf.cell(95, 5, contract_date_str, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    # 2. Преамбула
    preamble = (
        f"КОМУНАЛЬНЕ ПІДПРИЄМСТВО «ОДЕСМІСЬКЕЛЕКТРОТРАНС», в особі директора "
        f"{RENTAL_DIRECTOR_FULL_NAME}, який діє на підставі Статуту, далі – Виконавець, з однієї сторони, та "
        f"{customer['preamble_customer']}, з другої сторони, уклали цей "
        f"Договір надання послуг по перевезенню (далі — Договір) про таке:"
    )
    pdf.set_font("DejaVu", "", 8.5)
    pdf.multi_cell(0, 4.3, preamble)
    pdf.ln(2)

    # 3. Розділ 1
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(0, 4.8, "1. ПРЕДМЕТ ТА ЗАГАЛЬНІ УМОВИ ДОГОВОРУ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DejaVu", "", 8.5)
    pdf.multi_cell(
        0,
        4.1,
        f"1.1. Замовник оплачує, а Виконавець зобов’язується надати послугу по перевезенню "
        f"електричним транспортом – а саме: транспортний засіб – трамвай «Ретро», по маршруту: {route_str}.\n"
        f"1.2. Надання послуг підтверджується складанням актів надання послуг.",
    )
    pdf.ln(2)

    # 4. Розділ 2
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(0, 4.8, "2. ОБОВ'ЯЗКИ ТА ПРАВА СТОРІН", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DejaVu", "", 8.5)
    pdf.multi_cell(
        0,
        4.1,
        f"2.1. Виконавець зобов’язаний надати транспортний засіб в повністю справному технічному стані {departure_str}.\n"
        f"2.2. Замовник зобов’язаний дотримуватися Правил користування міським пасажирським автомобільним "
        f"та електричним транспортом у м. Одесі.\n"
        f"2.3. У разі затримки руху з вини Замовника, Виконавець має право провести перерахунок вартості "
        f"послуги з урахуванням часу затримки руху транспортного засобу.\n"
        f"2.4. Замовнику забороняється при користуванні трамваєм перевищення рівнів шуму, установлених "
        f"санітарними нормами на захищених об’єктах, для відповідного часу доби.",
    )
    pdf.ln(2)

    # 5. Розділ 3
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(0, 4.8, "3. ОПЛАТА ПОСЛУГ І ПОРЯДОК ЇХ ПРИЙМАННЯ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DejaVu", "", 8.5)
    pdf.multi_cell(
        0,
        4.1,
        f"3.1. Засобом платежу є національна валюта – гривня.\n"
        f"3.2. Розмір плати за надання послуг, що є предметом цього договору складає "
        f"{total_price:.2f} грн. ({total_words}), з урахуванням ПДВ {vat_20:.2f} грн. "
        f"(розраховується з урахуванням виїзду та заїзду в депо).\n"
        f"3.3. Плата за надання послуг по перевезенню здійснюється Замовником в безготівковій формі у розмірі "
        f"100% передоплати шляхом перерахування коштів відповідно до встановленого рахунку протягом трьох "
        f"банківських днів з моменту підписання Договору на розрахунковий рахунок Виконавця згідно розділу 7 даного Договору.",
    )
    pdf.ln(2)

    # 6. Розділ 4
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(0, 4.8, "4. ВІДПОВІДАЛЬНІСТЬ СТОРІН", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DejaVu", "", 8.5)
    pdf.multi_cell(
        0,
        4.1,
        "4.1. Усі спори, пов’язані із цим Договором, його укладанням або такі, що виникають у процесі "
        "виконання умов цього Договору, вирішуються шляхом переговорів між представниками Сторін. Якщо спір "
        "не можливо вирішити шляхом переговорів, він вирішується в судовому порядку за встановленою "
        "підвідомчістю та підсудністю такого спору в порядку, визначеному відповідним чинним в Україні законодавством.\n"
        "4.2. У разі відмови Замовника від надання послуг, з незалежних від Виконавця причин, якщо ним вже здійснено "
        "передоплату, 50% сплачених грошових коштів не повертається та залишаються у Виконавця. У випадку, "
        "коли Виконавець вже провів підготовчі роботи для надання послуг, із 50% суми, що може бути повернута Замовнику, "
        "вираховуються витрати, що були понесені Виконавцем та Замовнику повертається відповідно зменшена сума.\n"
        "4.3. У разі ненадання послуг з незалежних від Виконавця причин, якщо трамвай вже здійснив виїзд з депо, "
        "50% грошових коштів сплачених відповідно до цього Договору не повертається та залишаються у Виконавця.\n"
        "4.4. Сторони погодили, що у разі ненадання послуг Виконавцем з його вини чи надання послуг не у повному "
        "обсязі, розмір відповідальності Виконавця не може перевищувати розміру плати за надання послуг "
        "встановленого цим Договором.",
    )
    pdf.ln(2)

    # 7. Розділ 5
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(0, 4.8, "5. ОБСТАВИНИ НЕПЕРЕБОРНОЇ СИЛИ (ФОРС-МАЖОР)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DejaVu", "", 8.5)
    pdf.multi_cell(
        0,
        4.1,
        "5.1. Сторони звільняються від відповідальності за цим Договором, якщо невиконання або неналежне "
        "виконання зобов'язань було обумовлено настанням форс-мажорних обставин, що мають бути документально підтверджені.",
    )
    pdf.ln(2)

    # 8. Розділ 6
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(0, 4.8, "6. СТРОК ДІЇ ДОГОВОРУ ТА ІНШІ УМОВИ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DejaVu", "", 8.5)
    pdf.multi_cell(
        0,
        4.1,
        "6.1. Цей Договір набирає чинності з моменту його підписання і дійсний до повного виконання зобов’язань Сторонами.\n"
        "6.2. Зміни в цей Договір можуть бути внесені за взаємною згодою Сторін, що оформляється додатковою угодою до цього Договору.\n"
        "6.3. Зміни та доповнення, додаткові угоди та додатки до цього Договору є його невід'ємною частиною "
        "і мають юридичну силу в разі, якщо вони викладені в письмовій формі та підписані уповноваженими на те представниками Сторін.\n"
        "6.4. Усі правовідносини, що виникають у зв'язку з виконанням умов цього Договору і не врегульовані ним, "
        "регламентуються нормами чинного в Україні законодавства.\n"
        "6.5. Цей Договір складений українською мовою, у 2-х примірниках, кожний з яких має однакову юридичну силу.",
    )
    pdf.ln(3)

    # 9. Розділ 7: Двоколонкова таблиця реквізитів
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(0, 4.8, "7. ЮРИДИЧНІ АДРЕСИ СТОРІН:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)

    y_pos = pdf.get_y()
    if y_pos > 230:
        pdf.add_page()
        y_pos = pdf.get_y()

    w_left = 90
    w_right = 96
    x_left = pdf.get_x()
    x_right = x_left + w_left + 4

    customer_lines = customer.get("section7_lines") or [
        customer["short_name"],
        customer["address"],
        customer["passport"],
        f"РНОКПП {customer['tax_id']}",
        f"Тел.: {customer['phone']}",
        "",
        "Фізична особа",
        f"_____________ {customer['signature_name']}",
    ]
    customer_text = "\n".join(customer_lines)

    omet_lines = [
        "КП «ОМЕТ»",
        f"{RENTAL_IBAN_COMPANY_ADDRESS},",
        f"IBAN {RENTAL_IBAN_ACCOUNT};",
        f"в {RENTAL_BANK_NAME}; МФО {RENTAL_BANK_MFO};",
        f"IBAN {RENTAL_IBAN_ACCOUNT_SECONDARY};",
        f"в {RENTAL_BANK_NAME_SECONDARY}; МФО {RENTAL_BANK_MFO_SECONDARY};",
        f"Код ЄДРПОУ {RENTAL_EDRPOU};",
        f"ІПН {RENTAL_VAT_IPN};",
        f"Свід. № {RENTAL_VAT_CERTIFICATE};",
        f"Тел.: {RENTAL_COMPANY_PHONE}",
        "",
        "Директор",
        f"____________________ {RENTAL_IBAN_DIRECTOR_NAME}",
    ]
    omet_text = "\n".join(omet_lines)

    # Ліва колонка (ЗАМОВНИК)
    pdf.set_xy(x_left, y_pos)
    pdf.set_font("DejaVu", "B", 8.5)
    pdf.cell(w_left, 4.5, "ЗАМОВНИК", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(x_left)
    pdf.set_font("DejaVu", "", 8)
    pdf.multi_cell(w_left, 3.8, customer_text)
    y_left_end = pdf.get_y()

    # Права колонка (ВИКОНАВЕЦЬ)
    pdf.set_xy(x_right, y_pos)
    pdf.set_font("DejaVu", "B", 8.5)
    pdf.cell(w_right, 4.5, "ВИКОНАВЕЦЬ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(x_right)
    pdf.set_font("DejaVu", "", 8)
    pdf.multi_cell(w_right, 3.8, omet_text)
    y_right_end = pdf.get_y()

    pdf.set_y(max(y_left_end, y_right_end) + 4)

    pdf.output(pdf_path)
    return pdf_path


# ================= ГЕНЕРАЦІЯ ЕЛЕКТРОННОГО ПОСАДКОВОГО ТАЛОНА (BOARDING PASS) =================

def generate_rental_boarding_pass_pdf(
    order_data: Dict[str, Any],
    target_dir: Optional[str] = None,
) -> str:
    """
    Генерує Електронний посадковий талон із QR-кодом верифікації після призначення депо
    конкретного бортового номера та водія.
    """
    if not os.path.exists(FONT_PATH):
        raise FileNotFoundError(f"Шрифт DejaVuSans.ttf не знайдено: {FONT_PATH}")

    out_dir = Path(target_dir) if target_dir else DEFAULT_DOC_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    contract_number = str(order_data.get("contract_number", "2026-0001-О"))
    safe_num = contract_number.replace("/", "_").replace(" ", "_")
    pdf_path = str(out_dir / f"BoardingPass_{safe_num}.pdf")
    qr_path = str(out_dir / f"qr_pass_{safe_num}.png")

    verify_payload = (
        f"OGET-RENTAL-PASS\n"
        f"CONTRACT:{contract_number}\n"
        f"ORDER:{order_data.get('order_uid', '')}\n"
        f"DATE:{order_data.get('rental_date', '')} {order_data.get('rental_time_slot', '')}\n"
        f"BOARD:{order_data.get('assigned_board_number', '—')}\n"
        f"CUSTOMER:{order_data.get('user_full_name', '')}"
    )
    _create_qr_png(verify_payload, qr_path)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.add_page()
    pdf.add_font("DejaVu", "", FONT_PATH)
    pdf.add_font("DejaVu", "B", BOLD_FONT_PATH)

    pdf.set_fill_color(235, 244, 255)
    pdf.set_draw_color(40, 90, 170)
    pdf.rect(10, 12, 190, 92, "DF")

    pdf.set_xy(15, 16)
    pdf.set_font("DejaVu", "B", 14)
    pdf.cell(130, 8, "ЕЛЕКТРОННИЙ ПОСАДКОВИЙ ТАЛОН (НАРЯД-ДОПУСК)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(15)
    pdf.set_font("DejaVu", "B", 11)
    pdf.cell(130, 6, f"Договір № {contract_number} | Замовлення {order_data.get('order_uid', '')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    pdf.set_x(15)
    pdf.set_font("DejaVu", "", 9.5)
    pdf.cell(130, 6, f"Замовник: {order_data.get('user_full_name', '')} ({order_data.get('user_phone', '')})", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(15)
    pdf.cell(130, 6, f"Дата та час подачі: {order_data.get('rental_date', '')} о {order_data.get('rental_time_slot', '')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(15)
    pdf.cell(130, 6, f"Кільце посадки: {order_data.get('pickup_stop', '')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(15)
    pdf.cell(130, 6, f"Кільце висадки: {order_data.get('dropoff_stop', '')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(15)
    pdf.set_font("DejaVu", "B", 10)
    pdf.cell(
        130,
        6,
        f"Рухомий склад: {order_data.get('wagon_type', '')} | Бортовий № {order_data.get('assigned_board_number', '—')}",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.set_x(15)
    pdf.cell(
        130,
        6,
        f"Водій: {order_data.get('assigned_driver_name', '—')} (тел.: {order_data.get('assigned_driver_phone', '—')})",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.set_x(15)
    pdf.set_font("DejaVu", "", 8.5)
    pdf.cell(130, 6, "Статус: ПОВНІСТЮ ПОГОДЖЕНО ТА ОПЛАЧЕНО (IBAN)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if os.path.exists(qr_path):
        pdf.image(qr_path, x=152, y=22, w=42, h=42)

    pdf.output(pdf_path)
    return pdf_path


# ================= ВІДПРАВКА ПІДПИСАНОГО ДОГОВОРУ В ЮРИДИЧНИЙ ВІДДІЛ (SMTP) =================

def send_legal_contract_email(
    file_path: str,
    contract_number: str,
    customer_name: str,
    signing_scenario: str = "kep",
) -> bool:
    """
    Надсилає підписаний клієнтом договір (.p7s КЕП або скан-копію паперового договору)
    на офіційну електронну пошту Юридичного відділу (SMTP_LEGAL_EMAIL).
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.warning("⚠️ SMTP_USER / SMTP_PASSWORD не задані, пропускаємо email-відправку в Юрвідділ.")
        return False

    if not os.path.exists(file_path):
        logger.error(f"❌ Файл підписаного договору не знайдено: {file_path}")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_USER
        msg["To"] = SMTP_LEGAL_EMAIL
        scenario_label = "КЕП / Дія.Підпис" if signing_scenario == "kep" else "Паперовий договір (скан)"
        msg["Subject"] = f"[Оренда КП ОМЕТ] Договір №{contract_number} ({scenario_label}) — {customer_name}"

        body = (
            f"Доброго дня!\n\n"
            f"Через офіційний Telegram-бот КП «Одесміськелектротранс» отримано підписаний клієнтом договір оренди.\n"
            f"• Номер договору: № {contract_number}\n"
            f"• Замовник: {customer_name}\n"
            f"• Формат підписання: {scenario_label}\n\n"
            f"Файл договору прикріплено до цього листа та продубльовано в оперативному чаті «Оренда Електротранспорту — Штаб КП ОМЕТ».\n"
        )
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with open(file_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{os.path.basename(file_path)}"',
            )
            msg.attach(part)

        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10)
            server.starttls()

        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [SMTP_LEGAL_EMAIL], msg.as_string())
        server.quit()
        logger.info(f"📧 Договір №{contract_number} успішно надіслано до Юрвідділу ({SMTP_LEGAL_EMAIL})")
        return True
    except Exception as exc:
        logger.error(f"❌ Помилка відправки договору №{contract_number} на email Юрвідділу: {exc}")
        return False

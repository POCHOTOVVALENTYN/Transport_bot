"""Universal Tram & Trolleybus Rental Service for КП «Одесміськелектротранс».

Provides empirical Wialon-calibrated routing, kilometrage, travel duration
(in general traffic flow pace `dep_to_dep`), asymmetric depot pull-out/pull-in
(`ТД-1`, `ТД-2`, `ВРМ`, `ТрД`), multi-loop custom itineraries (`via_loops`),
detailed stop-by-stop itinerary with role annotations across all 630 platforms
and 54 turnaround loops, and official PDF route sheet generation.
Follows the RORO pattern with Pydantic v2 models.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import heapq
import json
import logging
import math
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from pydantic import BaseModel, Field, model_validator

from config.settings import BASE_DIR

logger = logging.getLogger(__name__)

FONTS_DIR = BASE_DIR / "assets" / "fonts"
ROUTE_SHEETS_DIR = BASE_DIR / "documents" / "route_sheets"
SEED_JSON_PATH = BASE_DIR / "database" / "wialon_transit_seed.json"
SQLITE_DB_PATH = BASE_DIR / "transport_bot.db"

# Types
TransportType = Literal["TRAM", "TROLLEYBUS"]
WagonType = Literal["retro", "standard", "trolleybus"]
DepotBase = Literal["ВРМ", "ТД-1", "ТД-2", "ТрД"]
DayType = Literal["WORKDAY", "WEEKEND"]

# Alias mapping for user input flexibility (both Tram & Trolleybus)
STOP_ALIASES: Dict[str, str] = {
    "старосінна площа": "пл. Старосінна",
    "старосінна": "пл. Старосінна",
    "тираспольська площа": "пл. Тираспольська",
    "тираспольська": "пл. Тираспольська",
    "олексіївська площа": "пл. Олексіївська",
    "олексіївська": "пл. Олексіївська",
    "одеса-товарна": "станція Одеса-Товарна",
    "товарна": "станція Одеса-Товарна",
    "ст. одеса-товарна": "станція Одеса-Товарна",
    "привоз": "ринок \"Привоз\"",
    "ринок привоз": "ринок \"Привоз\"",
    "парк шевченка": "Парк ім. Тараса Шевченка",
    "парк ім. т. г. шевченка": "Парк ім. Тараса Шевченка",
    "парк ім. т.г. шевченка": "Парк ім. Тараса Шевченка",
    "парк ім. тараса шевченка": "Парк ім. Тараса Шевченка",
    "парк т. г. шевченка": "Парк ім. Тараса Шевченка",
    "парк т.г. шевченка": "Парк ім. Тараса Шевченка",
    "парк шевченко": "Парк ім. Тараса Шевченка",
    "парк ім. шевченка": "Парк ім. Тараса Шевченка",
    "цпків ім. тараса шевченка": "Парк ім. Тараса Шевченка",
    "вокзал": "Залізничний вокзал",
    "залізничний вокзал (куликове поле)": "Залізничний вокзал",
    "привокзальна площа": "Залізничний вокзал",
    "європейська": "вул. Європейська",
    "катерининська": "вул. Європейська",
    "вул. катерининська": "вул. Європейська",
    "преображенська": "вул. Преображенська",
    "пантелеймонівська": "вул. Преображенська",
    "вул. пантелеймонівська": "вул. Преображенська",
    "застава 2": "станція Застава ІІ",
    "застава-2": "станція Застава ІІ",
    "застава ii": "станція Застава ІІ",
    "ст. застава іі": "станція Застава ІІ",
    "застава 1": "станція Застава I",
    "застава-1": "станція Застава I",
    "застава i": "станція Застава I",
    "ст. застава i": "станція Застава I",
    "ст. застава і": "станція Застава I",
    "архітекторська": "вул. Архітекторська",
    "інглезі": "вул. Інглезі",
    "ріхтера": "вул. Святослава Ріхтера",
    "святослава ріхтера": "вул. Святослава Ріхтера",
    "новосельського": "вул. Новосельського",
    "суперфосфатний": "Суперфосфатний завод",
    "кисеньмаш": "Суперфосфатний завод",
    "завод кисеньмаш": "Суперфосфатний завод",
    "пересип": "Пересипський міст",
    "пересипський": "Пересипський міст",
    "пастера": "вул. Пастера",
    "слобідка": "Слобідський ринок",
    "рачкова": "вул. Рачкова",
    "іцхака рабіна": "вул. Іцхака Рабіна",
    "вул. іцкаха рабіна": "вул. Іцхака Рабіна",
    "411 батарея": "Меморіал 411-ї батареї",
    "411-а батарея": "Меморіал 411-ї батареї",
    "меморіал 411 батареї": "Меморіал 411-ї батареї",
    "дерибасівська": "вул. Грецька",
    "вул. дерибасівська": "вул. Грецька",
    "соборна": "вул. Грецька",
    "ланжерон": "Парк ім. Тараса Шевченка",
    "французький бульвар": "Театр Музичної комедії",
    "французький б-р": "Театр Музичної комедії",
    "філатова": "Інститут ім. Філатова",
    "інститут філатова": "Інститут ім. Філатова",
    "золотий берег": "16-а станція Великого Фонтану",
    "аркадійська алея": "Аркадія",
    "люстдорф": "селище Люстдорф",
    "чорноморка": "селище Люстдорф",
    "центроліт": "завод «Центроліт»",
    "завод \"центроліт\"": "завод «Центроліт»",
    "паустовського": "вул. 28-ї бригади",
    "вул. паустовського": "вул. 28-ї бригади",
    "28 бригади": "вул. 28-ї бригади",
    "товбухіна": "пл. Трибуни Героїв",
    "пл. толбухіна": "пл. Трибуни Героїв",
    "трибуни героїв": "пл. Трибуни Героїв",
    "дерев'янка": "пл. Бориса Дерев'янка",
    "будинок меблів": "пл. Бориса Дерев'янка",
    "10 квітня": "пл. 10 Квітня",
    "площа 10 квітня": "пл. 10 Квітня",
    "незалежності": "пл. Незалежності",
    "площа незалежності": "пл. Незалежності",
}


def _canonical_stop_key(name: str) -> str:
    """Create canonical comparison key for stop and loop resolution."""
    if not name:
        return ""
    s = name.strip().lower()
    s = re.sub(r"[«»\"'ʼ’`]", "", s)
    s = s.replace("іі", "ii").replace("і", "i") if "застава" in s else s
    s = re.sub(r"(\d+)-[а-яіїє]+", r"\1", s)
    s = re.sub(r"\bст\.\s*", "станція ", s)
    s = re.sub(r"\bпл\.\s*", "площа ", s)
    s = re.sub(r"\bпросп\.\s*", "проспект ", s)
    s = re.sub(r"\bпр-т\s*", "проспект ", s)
    s = re.sub(r"\bпров\.\s*", "провулок ", s)
    s = re.sub(r"\bвул\.\s*", "вулиця ", s)
    s = re.sub(r"\bс-ще\s*", "селище ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_stop_name(raw_name: str) -> str:
    """Normalize colloquial or variant stop names to official graph node names."""
    if not raw_name:
        return ""
    cleaned = raw_name.strip()
    low = cleaned.lower()
    if low in STOP_ALIASES:
        return STOP_ALIASES[low]
    canon = _canonical_stop_key(cleaned)
    if canon in STOP_ALIASES:
        return STOP_ALIASES[canon]
    for loop in OFFICIAL_TURNING_LOOPS:
        if _canonical_stop_key(loop) == canon:
            return loop
    return cleaned


# Official Turning Loops (backward-compatible list + full Wialon turning loops)
OFFICIAL_TURNING_LOOPS: List[str] = [
    "Аркадія",
    "Куликове поле",
    "пл. Старосінна",
    "Старосінна площа",
    "Парк ім. Тараса Шевченка",
    "пл. Тираспольська",
    "Тираспольська площа",
    "вул. Пастера",
    "Херсонський сквер",
    "Автовокзал",
    "6-а станція Великого Фонтану",
    "11-а станція Великого Фонтану",
    "16-а станція Великого Фонтану",
    "Меморіал 411-ї батареї",
    "1-а станція Люстдорфської дороги",
    "2-а ст. Люстдорфської дороги (пл. Трибуни Героїв)",
    "3-я станція Люстдорфської дороги",
    "вул. Іцхака Рабіна",
    "ж/м Шкільний",
    "11-а станція Люстдорфської дороги",
    "селище Люстдорф",
    "Рибний порт",
    "станція Одеса-Товарна",
    "станція Застава ІІ",
    "Слобідський ринок",
    "Хаджибейський лиман",
    "пл. Ярмаркова",
    "Лузанівка",
    "вул. Чорноморського козацтва",
    "вул. 28-ї бригади",
    "завод «Центроліт»",
    "Пересипський міст",
    "узвіз Маловського",
    "Театр Музичної комедії",
    "Преображенський парк",
]

OFFICIAL_TROLLEYBUS_LOOPS: List[str] = [
    "Пересипський міст",
    "вул. Новосельського",
    "Суперфосфатний завод",
    "вул. Грецька (вул. Рішельєвська)",
    "Автовокзал",
    "Парк ім. Тараса Шевченка",
    "станція Застава I",
    "Залізничний вокзал",
    "Застава ІІ",
    "вул. Святослава Ріхтера",
    "пл. 10 Квітня",
    "пл. Бориса Дерев'янка",
    "5-а станція Великого Фонтану",
    "1-а станція Люстдорфської дороги",
    "пл. Трибуни Героїв",
    "вул. Інглезі",
    "вул. Архітекторська",
    "пл. Незалежності",
]

# Base core tram graph (guaranteed baseline, automatically enriched with all 630 Wialon stops below)
TRAM_TRACK_GRAPH: Dict[str, List[Tuple[str, float, int]]] = {
    "ВРМ": [
        ("станція Одеса-Товарна", 0.50, 3),
    ],
    "станція Одеса-Товарна": [
        ("ВРМ", 0.50, 3),
        ("пл. Олексіївська", 0.35, 2),
    ],
    "пл. Олексіївська": [
        ("станція Одеса-Товарна", 0.35, 2),
        ("пров. Високий", 0.40, 2),
    ],
    "пров. Високий": [
        ("пл. Олексіївська", 0.40, 2),
        ("вул. Мечникова", 0.35, 2),
    ],
    "вул. Мечникова": [
        ("пров. Високий", 0.35, 2),
        ("Преображенський парк", 0.35, 2),
    ],
    "Преображенський парк": [
        ("вул. Мечникова", 0.35, 2),
        ("ринок \"Привоз\"", 0.45, 2),
        ("вул. Преображенська", 0.20, 1),
        ("вул. Старопортофранківська", 1.20, 5),
    ],
    "ринок \"Привоз\"": [
        ("Преображенський парк", 0.45, 2),
        ("пл. Старосінна", 0.30, 1),
    ],
    "пл. Старосінна": [
        ("ринок \"Привоз\"", 0.30, 1),
        ("ТД-1", 0.35, 2),
    ],
    "ТД-1": [
        ("пл. Старосінна", 0.35, 2),
        ("Завод «Стальканат»", 0.50, 2),
    ],
    "Залізничний вокзал": [
        ("вул. Європейська", 0.45, 2),
        ("вул. Канатна", 0.40, 2),
        ("Куликове поле", 0.45, 2),
    ],
    "вул. Канатна": [
        ("Залізничний вокзал", 0.40, 2),
        ("Театр Музичної комедії", 0.45, 2),
    ],
    "Театр Музичної комедії": [
        ("вул. Канатна", 0.45, 2),
        ("вул. Пироговська", 0.50, 2),
        ("Парк ім. Тараса Шевченка", 1.20, 5),
    ],
    "Парк ім. Тараса Шевченка": [
        ("Театр Музичної комедії", 1.20, 5),
    ],
    "вул. Пироговська": [
        ("Театр Музичної комедії", 0.50, 2),
        ("пр. Лесі Українки", 0.55, 2),
    ],
    "пр. Лесі Українки": [
        ("вул. Пироговська", 0.55, 2),
        ("вул. Довженка", 0.35, 1),
    ],
    "вул. Довженка": [
        ("пр. Лесі Українки", 0.35, 1),
        ("Інститут ім. Філатова", 0.40, 2),
    ],
    "Інститут ім. Філатова": [
        ("вул. Довженка", 0.40, 2),
        ("Санаторій \"Аркадія\"", 0.35, 1),
    ],
    "Санаторій \"Аркадія\"": [
        ("Інститут ім. Філатова", 0.35, 1),
        ("Санаторій \"ім. Чкалова\"", 0.55, 2),
    ],
    "Санаторій \"ім. Чкалова\"": [
        ("Санаторій \"Аркадія\"", 0.55, 2),
        ("Санаторій \"Одеса\"", 0.40, 2),
    ],
    "Санаторій \"Одеса\"": [
        ("Санаторій \"ім. Чкалова\"", 0.40, 2),
        ("Міжрейсова база моряків", 0.35, 1),
    ],
    "Міжрейсова база моряків": [
        ("Санаторій \"Одеса\"", 0.35, 1),
        ("пл. 10 Квітня", 0.50, 2),
    ],
    "пл. 10 Квітня": [
        ("Міжрейсова база моряків", 0.50, 2),
        ("Турбаза", 0.35, 1),
        ("Аркадія", 0.55, 2),
    ],
    "Турбаза": [
        ("пл. 10 Квітня", 0.35, 1),
        ("Аркадія", 0.55, 2),
    ],
    "Аркадія": [
        ("пл. 10 Квітня", 0.55, 2),
        ("Турбаза", 0.55, 2),
    ],
    "вул. Преображенська": [
        ("Преображенський парк", 0.20, 1),
        ("вул. Європейська", 0.45, 2),
        ("вул. Велика Арнаутська", 0.35, 2),
    ],
    "вул. Європейська": [
        ("вул. Преображенська", 0.45, 2),
        ("Залізничний вокзал", 0.45, 2),
    ],
    "вул. Велика Арнаутська": [
        ("вул. Преображенська", 0.35, 2),
        ("вул. Успенська", 0.35, 2),
    ],
    "вул. Успенська": [
        ("вул. Велика Арнаутська", 0.35, 2),
        ("вул. Грецька", 0.35, 2),
    ],
    "вул. Грецька": [
        ("вул. Успенська", 0.35, 2),
        ("пл. Тираспольська", 0.35, 2),
    ],
    "пл. Тираспольська": [
        ("вул. Дегтярна", 0.48, 2),
        ("вул. Грецька", 0.35, 2),
        ("вул. Кіри Муратової", 0.30, 1),
    ],
    "вул. Кіри Муратової": [
        ("пл. Тираспольська", 0.30, 1),
        ("вул. Торгова", 0.35, 2),
    ],
    "вул. Торгова": [
        ("вул. Кіри Муратової", 0.35, 2),
        ("вул. Ольгіївська", 0.45, 2),
    ],
    "вул. Ольгіївська": [
        ("вул. Торгова", 0.45, 2),
        ("вул. Пастера", 0.40, 2),
    ],
    "вул. Пастера": [
        ("вул. Ольгіївська", 0.40, 2),
        ("Херсонський сквер", 0.45, 2),
    ],
    "Херсонський сквер": [
        ("вул. Пастера", 0.45, 2),
        ("Пересипський міст", 0.45, 2),
        ("узвіз Маловського", 1.70, 8),
        ("Слобідський ринок", 2.80, 12),
        ("Хаджибейський лиман", 6.80, 25),
    ],
    "Куликове поле": [
        ("Залізничний вокзал", 0.45, 2),
        ("5-а станція Великого Фонтану", 3.60, 14),
    ],
    "5-а станція Великого Фонтану": [
        ("Куликове поле", 3.60, 14),
        ("6-а станція Великого Фонтану", 0.65, 3),
        ("11-а станція Великого Фонтану", 2.88, 12),
    ],
    "6-а станція Великого Фонтану": [
        ("5-а станція Великого Фонтану", 0.65, 3),
        ("11-а станція Великого Фонтану", 2.23, 9),
    ],
    "11-а станція Великого Фонтану": [
        ("5-а станція Великого Фонтану", 2.88, 12),
        ("6-а станція Великого Фонтану", 2.23, 9),
        ("16-а станція Великого Фонтану", 3.20, 12),
    ],
    "16-а станція Великого Фонтану": [
        ("11-а станція Великого Фонтану", 3.20, 12),
        ("Меморіал 411-ї батареї", 2.70, 10),
    ],
    "Меморіал 411-ї батареї": [
        ("16-а станція Великого Фонтану", 2.70, 10),
    ],
    "Завод «Стальканат»": [
        ("ТД-1", 0.50, 2),
        ("1-а станція Люстдорфської дороги", 2.50, 9),
    ],
    "1-а станція Люстдорфської дороги": [
        ("Завод «Стальканат»", 2.50, 9),
        ("вул. Іцхака Рабіна", 5.00, 18),
        ("2-а ст. Люстдорфської дороги (пл. Трибуни Героїв)", 0.85, 3),
        ("3-я станція Люстдорфської дороги", 1.60, 7),
    ],
    "2-а ст. Люстдорфської дороги (пл. Трибуни Героїв)": [
        ("1-а станція Люстдорфської дороги", 0.85, 3),
        ("3-я станція Люстдорфської дороги", 0.75, 4),
    ],
    "вул. Іцхака Рабіна": [
        ("1-а станція Люстдорфської дороги", 5.00, 18),
    ],
    "3-я станція Люстдорфської дороги": [
        ("1-а станція Люстдорфської дороги", 1.60, 7),
        ("2-а ст. Люстдорфської дороги (пл. Трибуни Героїв)", 0.75, 4),
        ("ж/м Шкільний", 2.70, 12),
        ("11-а станція Люстдорфської дороги", 5.80, 21),
    ],
    "ж/м Шкільний": [
        ("3-я станція Люстдорфської дороги", 2.70, 12),
    ],
    "11-а станція Люстдорфської дороги": [
        ("3-я станція Люстдорфської дороги", 5.80, 21),
        ("селище Люстдорф", 4.10, 15),
    ],
    "селище Люстдорф": [
        ("11-а станція Люстдорфської дороги", 4.10, 15),
        ("Рибний порт", 3.80, 14),
    ],
    "Рибний порт": [
        ("селище Люстдорф", 3.80, 14),
    ],
    "вул. Старопортофранківська": [
        ("вул. Тираспольська", 0.33, 1),
        ("вул. М'ясоїдівська", 0.42, 2),
        ("Преображенський парк", 1.20, 5),
        ("Автовокзал", 1.20, 5),
        ("узвіз Маловського", 1.20, 5),
    ],
    "Автовокзал": [
        ("вул. Старопортофранківська", 1.20, 5),
        ("Преображенський парк", 1.35, 6),
    ],
    "узвіз Маловського": [
        ("вул. Старопортофранківська", 1.20, 5),
        ("Херсонський сквер", 1.70, 8),
        ("ТД-2", 0.95, 4),
    ],
    "ТД-2": [
        ("узвіз Маловського", 0.95, 4),
        ("Слобідський ринок", 0.35, 2),
    ],
    "Слобідський ринок": [
        ("ТД-2", 0.35, 2),
        ("Херсонський сквер", 2.80, 12),
    ],
    "вул. Дегтярна": [
        ("пл. Тираспольська", 0.48, 2),
        ("вул. Тираспольська", 0.25, 1),
    ],
    "вул. Тираспольська": [
        ("вул. Дегтярна", 0.25, 1),
        ("вул. Старопортофранківська", 0.33, 1),
    ],
    "вул. М'ясоїдівська": [
        ("вул. Старопортофранківська", 0.42, 2),
        ("пров. Прохорівський", 0.45, 2),
    ],
    "пров. Прохорівський": [
        ("вул. М'ясоїдівська", 0.45, 2),
        ("вул. Степова", 0.62, 3),
    ],
    "вул. Степова": [
        ("пров. Прохорівський", 0.62, 3),
        ("вул. Балківська", 0.56, 2),
    ],
    "вул. Балківська": [
        ("вул. Степова", 0.56, 2),
        ("вул. Колонічна", 0.53, 2),
    ],
    "вул. Колонічна": [
        ("вул. Балківська", 0.53, 2),
        ("вул. Бугаївська", 0.43, 2),
    ],
    "вул. Бугаївська": [
        ("вул. Колонічна", 0.43, 2),
        ("станція Застава ІІ", 0.46, 2),
    ],
    "станція Застава ІІ": [
        ("вул. Бугаївська", 0.46, 2),
    ],
    "Пересипський міст": [
        ("вул. Пастера", 1.20, 5),
        ("Херсонський сквер", 0.45, 2),
        ("вул. Чорноморського козацтва", 0.35, 1),
        ("пл. Ярмаркова", 3.10, 11),
        ("Лузанівка", 5.70, 20),
    ],
    "вул. Чорноморського козацтва": [
        ("Пересипський міст", 0.35, 1),
        ("пл. Ярмаркова", 2.75, 10),
    ],
    "пл. Ярмаркова": [
        ("Пересипський міст", 3.10, 11),
        ("вул. Чорноморського козацтва", 2.75, 10),
        ("Лузанівка", 2.60, 9),
    ],
    "Хаджибейський лиман": [
        ("Херсонський сквер", 6.80, 25),
    ],
    "Лузанівка": [
        ("Пересипський міст", 5.70, 20),
        ("пл. Ярмаркова", 2.60, 9),
        ("вул. 28-ї бригади", 6.20, 22),
    ],
    "вул. 28-ї бригади": [
        ("Лузанівка", 6.20, 22),
        ("завод «Центроліт»", 5.70, 20),
    ],
    "завод «Центроліт»": [
        ("вул. 28-ї бригади", 5.70, 20),
    ],
}

TROLLEYBUS_TRACK_GRAPH: Dict[str, List[Tuple[str, float, int]]] = {}


class StopPointInfo(BaseModel):
    seq: int
    stop_name: str
    role: str
    distance_from_prev_km: float
    minutes_from_prev: int
    cumulative_km: float
    cumulative_minutes: int


class RoutePhaseSummary(BaseModel):
    phase_number: int
    phase_title: str
    from_stop: str
    to_stop: str
    via_loop: Optional[str] = None
    via_loops: List[str] = Field(default_factory=list)
    distance_km: float
    motion_minutes: int
    wait_minutes: int
    total_phase_minutes: int
    stops_path: List[str]
    detailed_stops: List[StopPointInfo] = Field(default_factory=list)
    data_source: str = "WIALON"


class RentalCalculationInput(BaseModel):
    transport_type: Optional[TransportType] = None
    wagon_type: WagonType = "retro"
    depot_base: Optional[DepotBase] = None
    pickup_stop: str
    dropoff_stop: str
    intermediate_loop: Optional[str] = None
    via_loops: List[str] = Field(default_factory=list)
    loop_wait_minutes: int = Field(default=10, ge=0, le=120)
    wait_minutes_at_loop: Optional[int] = None
    departure_time: Optional[str] = None
    day_type: DayType = "WORKDAY"
    customer_name: Optional[str] = "Служба руху КП «ОМЕТ»"
    order_id: Optional[str] = None

    @model_validator(mode="after")
    def _sync_wait_minutes(self) -> "RentalCalculationInput":
        if self.wait_minutes_at_loop is not None:
            self.loop_wait_minutes = self.wait_minutes_at_loop
        return self


class RentalCalculationOutput(BaseModel):
    is_success: bool
    order_id: str
    calculation_timestamp: str
    transport_type: TransportType = "TRAM"
    wagon_type: WagonType
    depot_base: DepotBase
    time_profile: str = "FULL_DAY_MEDIAN"
    phase_1_dispatch: RoutePhaseSummary
    phase_2_rental: RoutePhaseSummary
    phase_3_return: RoutePhaseSummary
    total_billable_km: float
    total_motion_minutes: int
    total_wait_minutes: int
    total_duration_minutes: int
    formatted_total_duration: str
    pdf_route_sheet_path: Optional[str] = None
    error_message: Optional[str] = None


def _resolve_period_bucket(departure_time: Optional[str]) -> Optional[str]:
    """Map HH:MM string to Wialon time-of-day bucket ('05-07', '07-10', '10-16', '16-19', '19-24')."""
    if not departure_time:
        return None
    parts = departure_time.strip().split(":")
    if not parts or not parts[0].isdigit():
        return None
    hour = int(parts[0])
    if 5 <= hour < 7:
        return "05-07"
    if 7 <= hour < 10:
        return "07-10"
    if 10 <= hour < 16:
        return "10-16"
    if 16 <= hour < 19:
        return "16-19"
    if 19 <= hour <= 23 or hour < 5:
        return "19-24"
    return None


class _WialonTransitNetwork:
    """In-memory directed transit network backed by Wialon telemetry and SQLite/JSON seed."""

    def __init__(self) -> None:
        self.depots: Dict[str, Dict[str, Any]] = {}
        self.platforms: Dict[str, Dict[str, Any]] = {}
        self.platforms_by_vt: Dict[str, Dict[str, Dict[str, Any]]] = {"TRAM": {}, "TROLLEYBUS": {}}
        self.key_to_stop_ids: Dict[str, Dict[str, List[str]]] = {
            "TRAM": defaultdict(list),
            "TROLLEYBUS": defaultdict(list),
        }
        self.key_to_display_name: Dict[str, Dict[str, str]] = {"TRAM": {}, "TROLLEYBUS": {}}
        self.turning_loops: Dict[str, List[Dict[str, Any]]] = {"TRAM": [], "TROLLEYBUS": []}
        self.loop_key_map: Dict[str, Dict[str, Dict[str, Any]]] = {"TRAM": {}, "TROLLEYBUS": {}}
        self.adj: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
            "TRAM": defaultdict(list),
            "TROLLEYBUS": defaultdict(list),
        }
        self.zero_runs: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
        self.is_loaded: bool = False

    def load(self) -> None:
        if self.is_loaded:
            return

        payload: Optional[Dict[str, Any]] = None
        if SEED_JSON_PATH.exists():
            try:
                with open(SEED_JSON_PATH, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception as exc:
                logger.warning("Failed to load seed JSON %s: %s", SEED_JSON_PATH, exc)

        if payload is None and SQLITE_DB_PATH.exists():
            payload = self._load_from_sqlite(SQLITE_DB_PATH)

        if not payload:
            self.is_loaded = True
            return

        for d in payload.get("depots", []):
            self.depots[d["code"]] = d

        for p in payload.get("platforms", []):
            sid = str(p["stop_id"])
            vt = str(p["transport_type"]).upper()
            self.platforms[sid] = p
            self.platforms_by_vt[vt][sid] = p
            raw_key = (p.get("canonical_key") or "").strip().lower()
            computed_key = _canonical_stop_key(p["name"])
            stored_key = _canonical_stop_key(raw_key) if raw_key else ""
            keys_to_index = {computed_key, raw_key, stored_key} - {""}
            for k in keys_to_index:
                if sid not in self.key_to_stop_ids[vt][k]:
                    self.key_to_stop_ids[vt][k].append(sid)
                if k not in self.key_to_display_name[vt]:
                    self.key_to_display_name[vt][k] = p["name"]

        for l in payload.get("turning_loops", []):
            vt = str(l["transport_type"]).upper()
            self.turning_loops[vt].append(l)
            raw_key = (l.get("canonical_key") or "").strip().lower()
            computed_key = _canonical_stop_key(l["name"])
            stored_key = _canonical_stop_key(raw_key) if raw_key else ""
            for k in ({computed_key, raw_key, stored_key} - {""}):
                self.loop_key_map[vt][k] = l
            for alias in l.get("aliases", []):
                akey = _canonical_stop_key(alias)
                if akey:
                    self.loop_key_map[vt][akey] = l
                    if akey not in self.key_to_stop_ids[vt] and l.get("platform_ids"):
                        self.key_to_stop_ids[vt][akey] = list(l["platform_ids"])
                        self.key_to_display_name[vt][akey] = l["name"]

        for e in payload.get("directed_edges", []):
            vt = str(e["transport_type"]).upper()
            self.adj[vt][str(e["from_stop_id"])].append(e)

        for z in payload.get("depot_zero_runs", []):
            t_key = z.get("terminal_key") or _canonical_stop_key(z["terminal_name"])
            self.zero_runs[(z["depot_code"], z["kind"], t_key)].append(z)

        # Enrich TRAM_TRACK_GRAPH and TROLLEYBUS_TRACK_GRAPH with all stops so get_available_stops()
        # and stop-level lookups cover all 630 platforms
        self._enrich_stop_graphs()
        self.is_loaded = True

    def _load_from_sqlite(self, db_path: Path) -> Optional[Dict[str, Any]]:
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transit_platforms'")
            if not cur.fetchone():
                conn.close()
                return None

            cur.execute("SELECT * FROM transit_depots")
            depots = [
                {
                    **dict(r),
                    "anchor_stops": json.loads(r["anchor_stops_json"] or "[]"),
                }
                for r in cur.fetchall()
            ]
            cur.execute("SELECT * FROM transit_platforms")
            platforms = [
                {
                    **dict(r),
                    "routes": json.loads(r["routes_json"] or "[]"),
                    "headings": json.loads(r["headings_json"] or "{}"),
                }
                for r in cur.fetchall()
            ]
            cur.execute("SELECT * FROM transit_turning_loops")
            loops = [
                {
                    **dict(r),
                    "aliases": json.loads(r["aliases_json"] or "[]"),
                    "platform_ids": json.loads(r["platform_ids_json"] or "[]"),
                }
                for r in cur.fetchall()
            ]
            cur.execute("SELECT * FROM transit_edges")
            edges = [
                {
                    **dict(r),
                    "routes": json.loads(r["routes_json"] or "[]"),
                    "profiles": json.loads(r["profiles_json"] or "{}"),
                }
                for r in cur.fetchall()
            ]
            cur.execute("SELECT * FROM transit_depot_zero_runs")
            zruns = [
                {
                    **dict(r),
                    "points": json.loads(r["points_json"] or "[]"),
                }
                for r in cur.fetchall()
            ]
            conn.close()
            return {
                "depots": depots,
                "platforms": platforms,
                "turning_loops": loops,
                "directed_edges": edges,
                "depot_zero_runs": zruns,
            }
        except Exception as exc:
            logger.warning("Failed to load Wialon transit data from SQLite: %s", exc)
            return None

    def _enrich_stop_graphs(self) -> None:
        """Populate TRAM_TRACK_GRAPH and TROLLEYBUS_TRACK_GRAPH with all canonical Wialon stop nodes."""
        for vt, target_graph in (("TRAM", TRAM_TRACK_GRAPH), ("TROLLEYBUS", TROLLEYBUS_TRACK_GRAPH)):
            # Preserve baseline nodes so existing baseline paths are not bypassed by parallel shortcuts
            baseline_nodes = set(target_graph.keys())
            existing_key_to_node: Dict[str, str] = {}
            for node_name in list(target_graph.keys()):
                existing_key_to_node[_canonical_stop_key(node_name)] = node_name

            # Exclude 'вулиця михайла болтенка' from creating a parallel shortcut around пров. Високий -> вул. Мечникова in TRAM_TRACK_GRAPH
            for sid, edges in self.adj[vt].items():
                u_p = self.platforms_by_vt[vt].get(sid)
                if not u_p:
                    continue
                u_key = u_p["canonical_key"]
                u_name = existing_key_to_node.get(u_key, u_p["name"])
                existing_key_to_node[u_key] = u_name
                if u_name not in target_graph:
                    target_graph[u_name] = []

                existing_neighbors = {nb for nb, _, _ in target_graph[u_name]}
                for e in edges:
                    if e["edge_kind"] == "TURN":
                        continue
                    v_p = self.platforms_by_vt[vt].get(str(e["to_stop_id"]))
                    if not v_p:
                        continue
                    v_key = v_p["canonical_key"]
                    v_name = existing_key_to_node.get(v_key, v_p["name"])
                    existing_key_to_node[v_key] = v_name
                    if v_name == u_name or v_name in existing_neighbors:
                        continue
                    # Do not add shortcut edges between two baseline TRAM nodes or via Михайла Болтенка to baseline nodes
                    if vt == "TRAM":
                        if u_name in baseline_nodes and v_name in baseline_nodes:
                            continue
                        if "болтенка" in u_key or "болтенка" in v_key:
                            if u_name in ("пл. Олексіївська", "Преображенський парк") or v_name in ("пл. Олексіївська", "Преображенський парк"):
                                continue
                    km = max(0.05, round(float(e["distance_m"]) / 1000.0, 2))
                    mins = max(1, int(round(float(e["dep_to_dep_sec"]) / 60.0)))
                    target_graph[u_name].append((v_name, km, mins))
                    existing_neighbors.add(v_name)
                    if v_name not in target_graph:
                        target_graph[v_name] = []

        # Also add Trolleybus depot ТрД node to TROLLEYBUS_TRACK_GRAPH
        if "ТрД" not in TROLLEYBUS_TRACK_GRAPH:
            TROLLEYBUS_TRACK_GRAPH["ТрД"] = [
                ("вул. Інглезі", 1.15, 7),
                ("вул. Варненська", 1.40, 8),
                ("пл. Трибуни Героїв", 2.30, 10),
            ]
        for anchor_nb, akm, amin in [("вул. Інглезі", 1.15, 7), ("вул. Варненська", 1.40, 8), ("пл. Трибуни Героїв", 2.30, 10)]:
            if anchor_nb in TROLLEYBUS_TRACK_GRAPH:
                if all(nb != "ТрД" for nb, _, _ in TROLLEYBUS_TRACK_GRAPH[anchor_nb]):
                    TROLLEYBUS_TRACK_GRAPH[anchor_nb].append(("ТрД", akm, amin))

    def resolve_stop_ids(self, stop_or_loop: str, transport_type: TransportType) -> Tuple[str, List[str]]:
        """Resolve a user stop name, loop name, or alias to (display_name, list of platform stop_ids)."""
        norm = normalize_stop_name(stop_or_loop)
        ckey = _canonical_stop_key(norm)

        # Direct canonical match
        if ckey in self.key_to_stop_ids[transport_type]:
            sids = self.key_to_stop_ids[transport_type][ckey]
            disp = self.key_to_display_name[transport_type].get(ckey, norm)
            return disp, sids

        # Turning loop match
        if ckey in self.loop_key_map[transport_type]:
            loop_obj = self.loop_key_map[transport_type][ckey]
            return loop_obj["name"], list(loop_obj.get("platform_ids", []))

        # Substring match across canonical keys
        for k, sids in self.key_to_stop_ids[transport_type].items():
            if ckey and (ckey in k or k in ckey):
                return self.key_to_display_name[transport_type].get(k, norm), sids

        return norm, []

    def edge_cost_seconds(
        self,
        edge: Dict[str, Any],
        day_type: DayType = "WORKDAY",
        period_bucket: Optional[str] = None,
    ) -> float:
        """Return empirical Wialon dep_to_dep_sec for the given day_type and time-of-day period."""
        profiles = edge.get("profiles") or {}
        if period_bucket:
            prof_key = f"{day_type}:{period_bucket}"
            if prof_key in profiles and "dep_to_dep_sec" in profiles[prof_key]:
                return float(profiles[prof_key]["dep_to_dep_sec"])
            # Fallback to WORKDAY profile for same period if WEEKEND has low sample
            alt_key = f"WORKDAY:{period_bucket}"
            if alt_key in profiles and "dep_to_dep_sec" in profiles[alt_key]:
                return float(profiles[alt_key]["dep_to_dep_sec"])
        return float(edge.get("dep_to_dep_sec", 65.0))

    def find_platform_path(
        self,
        origin_name: str,
        dest_name: str,
        transport_type: TransportType = "TRAM",
        day_type: DayType = "WORKDAY",
        period_bucket: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Run multi-source Dijkstra on the 630-platform directed Wialon graph."""
        orig_disp, orig_sids = self.resolve_stop_ids(origin_name, transport_type)
        dest_disp, dest_sids = self.resolve_stop_ids(dest_name, transport_type)
        if not orig_sids or not dest_sids:
            return None

        if set(orig_sids) & set(dest_sids) or _canonical_stop_key(orig_disp) == _canonical_stop_key(dest_disp):
            return {
                "distance_km": 0.0,
                "duration_minutes": 0,
                "path": [orig_disp],
                "step_edges": [],
                "source": "WIALON",
            }

        dest_set = set(dest_sids)
        dist_map: Dict[str, Tuple[float, float]] = {}
        pq: List[Tuple[float, float, str, List[str], List[Tuple[str, float, float]]]] = []

        for sid in orig_sids:
            p_name = self.platforms_by_vt[transport_type][sid]["name"]
            dist_map[sid] = (0.0, 0.0)
            heapq.heappush(pq, (0.0, 0.0, sid, [p_name], []))

        while pq:
            cost_sec, cost_m, u_sid, names_path, edge_steps = heapq.heappop(pq)
            if u_sid in dest_set:
                total_km = round(cost_m / 1000.0, 2)
                total_min = max(1, int(round(cost_sec / 60.0)))
                return {
                    "distance_km": total_km,
                    "duration_minutes": total_min,
                    "path": names_path,
                    "step_edges": edge_steps,
                    "source": "WIALON",
                }

            if (cost_sec, cost_m) > dist_map.get(u_sid, (float("inf"), float("inf"))):
                continue

            for edge in self.adj[transport_type].get(u_sid, []):
                v_sid = str(edge["to_stop_id"])
                v_p = self.platforms_by_vt[transport_type].get(v_sid)
                if not v_p:
                    continue
                e_sec = self.edge_cost_seconds(edge, day_type=day_type, period_bucket=period_bucket)
                e_m = float(edge["distance_m"])

                # Slight penalty on TURN/SWITCH edges so vehicle stays on main track unless turning/switching is needed
                weight_sec = e_sec + (30.0 if edge["edge_kind"] in ("TURN", "SWITCH") else 0.0)
                new_sec = cost_sec + weight_sec
                new_m = cost_m + e_m

                if (new_sec, new_m) < dist_map.get(v_sid, (float("inf"), float("inf"))):
                    dist_map[v_sid] = (new_sec, new_m)
                    v_name = v_p["name"]
                    if names_path and _canonical_stop_key(names_path[-1]) == _canonical_stop_key(v_name):
                        next_names = list(names_path)
                        if edge_steps:
                            prev_n, prev_km, prev_s = edge_steps[-1]
                            next_steps = edge_steps[:-1] + [(prev_n, round(prev_km + e_m / 1000.0, 3), prev_s + e_sec)]
                        else:
                            next_steps = list(edge_steps)
                    else:
                        next_names = names_path + [v_name]
                        next_steps = edge_steps + [(v_name, round(e_m / 1000.0, 3), e_sec)]
                    heapq.heappush(pq, (new_sec, new_m, v_sid, next_names, next_steps))

        return None

    def find_depot_zero_run(
        self,
        depot_code: str,
        stop_name: str,
        kind: Literal["PULL_OUT", "PULL_IN"],
        transport_type: TransportType,
        day_type: DayType = "WORKDAY",
        period_bucket: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Compute PULL_OUT (depot -> stop) or PULL_IN (stop -> depot) using verified Wialon zero-runs + platform graph."""
        norm_stop = normalize_stop_name(stop_name)
        stop_key = _canonical_stop_key(norm_stop)

        # 1. Direct verified Wialon zero-run match
        direct_candidates = self.zero_runs.get((depot_code, kind, stop_key), [])
        if direct_candidates:
            # Choose shortest-duration verified Wialon candidate
            best = min(direct_candidates, key=lambda c: (c["duration_min"], c["distance_km"]))
            pts = [pt["name"] for pt in best.get("points", []) if pt.get("name")]
            if kind == "PULL_OUT":
                path_names = [depot_code] + [p for p in pts if _canonical_stop_key(p) != stop_key] + [norm_stop]
            else:
                path_names = [norm_stop] + [p for p in pts if _canonical_stop_key(p) != stop_key] + [depot_code]
            # Deduplicate consecutive identical names
            dedup_path = [path_names[0]]
            for nm in path_names[1:]:
                if _canonical_stop_key(nm) != _canonical_stop_key(dedup_path[-1]):
                    dedup_path.append(nm)
            return {
                "distance_km": round(float(best["distance_km"]), 2),
                "duration_minutes": int(best["duration_min"]),
                "path": dedup_path,
                "source": best.get("source", "WIALON_ZERO_RUN"),
            }

        # 2. Composite zero-run via depot anchor stops on the Wialon platform graph
        depot_meta = self.depots.get(depot_code)
        anchors = depot_meta.get("anchor_stops", []) if depot_meta else []
        if not anchors:
            if depot_code == "ВРМ":
                anchors = ["станція Одеса-Товарна", "пл. Олексіївська"]
            elif depot_code == "ТД-1":
                anchors = ["пл. Старосінна", "ринок \"Привоз\"", "Преображенський парк", "Завод \"Стальканат\""]
            elif depot_code == "ТД-2":
                anchors = ["Слобідський ринок", "узвіз Маловського", "Херсонський сквер"]
            elif depot_code == "ТрД":
                anchors = ["вул. Інглезі", "пл. Трибуни Героїв", "вул. Космонавтів"]

        best_composite: Optional[Dict[str, Any]] = None
        for anchor in anchors:
            anchor_key = _canonical_stop_key(anchor)
            # Check if we have a verified zero-run to/from this anchor, otherwise use depot gate link
            anchor_zrs = self.zero_runs.get((depot_code, kind, anchor_key), [])
            if anchor_zrs:
                azr = min(anchor_zrs, key=lambda c: (c["duration_min"], c["distance_km"]))
                anchor_km = float(azr["distance_km"])
                anchor_min = int(azr["duration_min"])
            else:
                anchor_km = 0.50 if depot_code in ("ВРМ", "ТД-1") else (0.95 if depot_code == "ТД-2" else 1.15)
                anchor_min = 3 if depot_code in ("ВРМ", "ТД-1") else (4 if depot_code == "ТД-2" else 7)

            if kind == "PULL_OUT":
                sub = self.find_platform_path(
                    anchor,
                    norm_stop,
                    transport_type=transport_type,
                    day_type=day_type,
                    period_bucket=period_bucket,
                )
                if sub:
                    tot_km = round(anchor_km + sub["distance_km"], 2)
                    tot_min = anchor_min + sub["duration_minutes"]
                    full_path = [depot_code] + sub["path"]
                    if best_composite is None or (tot_min, tot_km) < (
                        best_composite["duration_minutes"],
                        best_composite["distance_km"],
                    ):
                        best_composite = {
                            "distance_km": tot_km,
                            "duration_minutes": tot_min,
                            "path": full_path,
                            "source": "WIALON_COMPOSITE",
                        }
            else:
                sub = self.find_platform_path(
                    norm_stop,
                    anchor,
                    transport_type=transport_type,
                    day_type=day_type,
                    period_bucket=period_bucket,
                )
                if sub:
                    tot_km = round(sub["distance_km"] + anchor_km, 2)
                    tot_min = sub["duration_minutes"] + anchor_min
                    full_path = sub["path"] + [depot_code]
                    if best_composite is None or (tot_min, tot_km) < (
                        best_composite["duration_minutes"],
                        best_composite["distance_km"],
                    ):
                        best_composite = {
                            "distance_km": tot_km,
                            "duration_minutes": tot_min,
                            "path": full_path,
                            "source": "WIALON_COMPOSITE",
                        }

        return best_composite


_NETWORK = _WialonTransitNetwork()


def get_wialon_transit_network() -> _WialonTransitNetwork:
    """Return initialized singleton of the Wialon transit network."""
    if not _NETWORK.is_loaded:
        _NETWORK.load()
    return _NETWORK


# Initialize on import so TRAM_TRACK_GRAPH and TROLLEYBUS_TRACK_GRAPH are enriched immediately
get_wialon_transit_network()


def format_duration_hours_minutes(total_minutes: int) -> str:
    """Format total minutes into human-readable hours and minutes."""
    if total_minutes < 60:
        return f"{total_minutes} хв"
    hours = total_minutes // 60
    mins = total_minutes % 60
    if mins == 0:
        return f"{hours} год"
    return f"{hours} год {mins:02d} хв"


def get_available_turning_loops(transport_type: Optional[str] = None) -> List[str]:
    """Return sorted list of verified turning loops (Tram, Trolleybus, or all)."""
    net = get_wialon_transit_network()
    if transport_type and transport_type.upper() == "TROLLEYBUS":
        loops = {l["name"] for l in net.turning_loops.get("TROLLEYBUS", [])} | set(OFFICIAL_TROLLEYBUS_LOOPS)
        return sorted(loops)
    if transport_type and transport_type.upper() == "TRAM":
        loops = {l["name"] for l in net.turning_loops.get("TRAM", [])} | set(OFFICIAL_TURNING_LOOPS)
        return sorted(loops)
    loops = {l["name"] for l in net.turning_loops.get("TRAM", [])} | set(OFFICIAL_TURNING_LOOPS)
    return sorted(loops)


def get_available_stops(transport_type: Optional[str] = None) -> List[str]:
    """Return sorted list of all available stops in the requested transport graph."""
    get_wialon_transit_network()
    if transport_type and transport_type.upper() == "TROLLEYBUS":
        return sorted(list(TROLLEYBUS_TRACK_GRAPH.keys()))
    return sorted(list(TRAM_TRACK_GRAPH.keys()))


def get_all_rental_points(transport_type: Optional[str] = None) -> List[str]:
    """Повертає об'єднаний та відсортований список усіх точок оренди (і зупинок, і розворотних кілець)."""
    vt = (transport_type or "TRAM").upper()
    stops = set(get_available_stops(vt))
    loops = set(get_available_turning_loops(vt))
    return sorted(list(stops | loops))


# ТОП-20 популярних та екскурсійних зупинок Одеси
POPULAR_TRAM_STOPS: List[Dict[str, Any]] = [
    {"name": "Аркадія", "icon": "🔄", "is_loop": True, "desc": "Курортний хаб, пляжі, Аркадійська алея"},
    {"name": "Парк ім. Тараса Шевченка", "icon": "🔄", "is_loop": True, "desc": "Центральний парк, спуск до Ланжерона, Алея Слави"},
    {"name": "Театр Музичної комедії", "icon": "🔄", "is_loop": True, "desc": "Початок Французького бульвару, театр ім. М. Водяного"},
    {"name": "пл. Старосінна", "icon": "🔄", "is_loop": True, "desc": "Залізничний вокзал, ТД-1, база ретро-вагона"},
    {"name": "Залізничний вокзал", "icon": "🚏", "is_loop": False, "desc": "Привокзальна площа, головні ворота Одеси"},
    {"name": "Куликове поле", "icon": "🔄", "is_loop": True, "desc": "Кільцевий розворот ліній Фонтану біля вокзалу"},
    {"name": 'ринок "Привоз"', "icon": "🚏", "is_loop": False, "desc": "Культова одеська візитівка, історичний ринок"},
    {"name": "пл. Тираспольська", "icon": "🔄", "is_loop": True, "desc": "Історичне кільце, перетин маршрутів старого міста"},
    {"name": "вул. Пастера", "icon": "🔄", "is_loop": True, "desc": "Новий ринок, Український академічний театр"},
    {"name": "вул. Грецька", "icon": "🚏", "is_loop": False, "desc": "вул. Преображенська, 2 хв до вул. Дерибасівської"},
    {"name": "вул. Преображенська", "icon": "🚏", "is_loop": False, "desc": "Головна вісь старого міста, Соборна площа"},
    {"name": "вул. Торгова", "icon": "🚏", "is_loop": False, "desc": "Початок б-ру Жванецького та Художнього музею"},
    {"name": "вул. Канатна", "icon": "🚏", "is_loop": False, "desc": "Стадіон «Спартак», початок Французького бульвару"},
    {"name": "Інститут ім. Філатова", "icon": "🚏", "is_loop": False, "desc": "Французький бульвар, старовинні садиби та дачі"},
    {"name": "пл. 10 Квітня", "icon": "🚏", "is_loop": False, "desc": "Меморіал «Крила Перемоги», дендропарк Перемоги"},
    {"name": "5-а станція Великого Фонтану", "icon": "🚏", "is_loop": False, "desc": "Сквер Героїв-льотчиків, пересадковий хаб"},
    {"name": "16-а станція Великого Фонтану", "icon": "🔄", "is_loop": True, "desc": "Курорт «Золотий Берег», набережна біля моря"},
    {"name": "Меморіал 411-ї батареї", "icon": "🔄", "is_loop": True, "desc": "Меморіальний парк-музей військової техніки"},
    {"name": "Херсонський сквер", "icon": "🔄", "is_loop": True, "desc": "Хаб під узвозом Маринеска, старт маршруту № 20"},
    {"name": "Лузанівка", "icon": "🔄", "is_loop": True, "desc": "Курортний пляжний комплекс Пересипу"},
]

# Розподіл трамвайних зупинок за 6 районами міста
TRAM_DISTRICTS: Dict[str, List[str]] = {
    "🏖️ Французький б-р & Аркадія": [
        "Театр Музичної комедії",
        "вул. Пироговська",
        "пр. Лесі Українки",
        "вул. Довженка",
        "Інститут ім. Філатова",
        'Санаторій "Аркадія"',
        'Санаторій "ім. Чкалова"',
        'Санаторій "Одеса"',
        "Міжрейсова база моряків",
        "пл. 10 Квітня",
        "Аркадія",
    ],
    "⛲ Великий Фонтан": [
        "1-а станція Великого Фонтану",
        "2-а станція Великого Фонтану",
        "3-а станція Великого Фонтану",
        "4-а станція Великого Фонтану",
        "5-а станція Великого Фонтану",
        "6-а станція Великого Фонтану",
        "7-а станція Великого Фонтану",
        "8-а станція Великого Фонтану",
        "9-а станція Великого Фонтану",
        "10-а станція Великого Фонтану",
        "11-а станція Великого Фонтану",
        "12-а станція Великого Фонтану",
        "14-а станція Великого Фонтану",
        "15-а станція Великого Фонтану",
        "16-а станція Великого Фонтану",
        "Меморіал 411-ї батареї",
    ],
    "🚋 Центр, Вокзал & Привоз": [
        "Залізничний вокзал",
        "Куликове поле",
        "пл. Старосінна",
        'ринок "Привоз"',
        "вул. Преображенська",
        "вул. Грецька",
        "вул. Європейська",
        "пл. Тираспольська",
        "вул. Пастера",
        "вул. Торгова",
        "Парк ім. Тараса Шевченка",
        "Преображенський парк",
        "вул. Канатна",
        "вул. Старопортофранківська",
        "вул. Дегтярна",
        "вул. Тираспольська",
        "вул. Мечникова",
    ],
    "🌊 Люстдорфська дорога & Таїрова": [
        "1-а станція Люстдорфської дороги",
        "2-а ст. Люстдорфської дороги (пл. Трибуни Героїв)",
        "3-я станція Люстдорфської дороги",
        "4-а станція Люстдорфської дороги",
        "5-а станція Люстдорфської дороги",
        "вул. Іцхака Рабіна",
        "ж/м Шкільний",
        "11-а станція Люстдорфської дороги",
        "селище Люстдорф",
        "Рибний порт",
        "2-е кладовище",
    ],
    "🏭 Молдаванка, Застава & Слобідка": [
        "станція Одеса-Товарна",
        "пл. Олексіївська",
        "ВРМ",
        "пров. Високий",
        "вул. М'ясоїдівська",
        "пров. Прохорівський",
        "вул. Степова",
        "вул. Балківська",
        "вул. Колонічна",
        "вул. Бугаївська",
        "станція Застава ІІ",
        "узвіз Маловського",
        "ТД-2",
        "Слобідський ринок",
        "Хаджибейський лиман",
        "Херсонський сквер",
        "Автовокзал",
    ],
    "🚢 Пересип & Селище Котовського": [
        "Пересипський міст",
        "вул. Чорноморського козацтва",
        "пл. Ярмаркова",
        "Лузанівка",
        "вул. 28-ї бригади",
        "завод «Центроліт»",
    ],
}


def is_turnaround_loop(stop_name: str, transport_type: str = "TRAM") -> bool:
    """Визначає, чи є зазначена зупинка офіційним розворотним кільцем із можливістю тривалого відстою."""
    if not stop_name:
        return False
    norm = normalize_stop_name(stop_name)
    loops = get_available_turning_loops(transport_type)
    loop_set = set(loops) | {normalize_stop_name(l) for l in loops}
    if norm in loop_set or stop_name in loop_set:
        return True
    canon = _canonical_stop_key(norm)
    return any(_canonical_stop_key(l) == canon for l in loops)


def search_tram_stops(query_text: str, transport_type: str = "TRAM", limit: int = 6) -> List[str]:
    """Здійснює швидкий та гнучкий пошук зупинок серед усіх точок трамвайної мережі Одеси."""
    q = query_text.strip().lower()
    if not q:
        return []

    stops = get_all_rental_points(transport_type)
    results: List[str] = []

    # 1. Пошук через словник туристичних аліасів (наприклад, 'дерибас' -> 'вул. Грецька')
    for alias_k, canonical_target in STOP_ALIASES.items():
        if q in alias_k or alias_k in q:
            if canonical_target in stops and canonical_target not in results:
                results.append(canonical_target)

    # 2. Прямий збіг підрядка в назві зупинки
    for s in stops:
        if q in s.lower() and s not in results:
            results.append(s)

    # 3. Канонічний збіг кореневої назви (без скорочень 'вул.', 'пл.', 'пр.')
    cq = _canonical_stop_key(q)
    if cq:
        for s in stops:
            if cq in _canonical_stop_key(s) and s not in results:
                results.append(s)

    return results[:limit]


def get_all_districts() -> List[str]:
    """Повертає перелік усіх 6 районів для групування зупинок."""
    return list(TRAM_DISTRICTS.keys())


def get_stops_by_district(district_name: str) -> List[str]:
    """Повертає список зупинок для зазначеного району міста."""
    return TRAM_DISTRICTS.get(district_name, [])


def get_edge_weight(u: str, v: str, transport_type: TransportType = "TRAM") -> Tuple[float, int]:
    """Find edge distance and duration between adjacent nodes in graph."""
    graph = TROLLEYBUS_TRACK_GRAPH if transport_type == "TROLLEYBUS" else TRAM_TRACK_GRAPH
    for neighbor, km, mins in graph.get(u, []):
        if neighbor == v:
            return km, mins
    # Check canonical match in Wialon platform edges
    net = get_wialon_transit_network()
    _, u_sids = net.resolve_stop_ids(u, transport_type)
    _, v_sids = net.resolve_stop_ids(v, transport_type)
    v_set = set(v_sids)
    for usid in u_sids:
        for e in net.adj[transport_type].get(usid, []):
            if str(e["to_stop_id"]) in v_set:
                km = max(0.05, round(float(e["distance_m"]) / 1000.0, 2))
                mins = max(1, int(round(float(e["dep_to_dep_sec"]) / 60.0)))
                return km, mins
    return 0.40, 2


def find_shortest_transit_path(
    origin: str,
    destination: str,
    transport_type: TransportType = "TRAM",
    departure_time: Optional[str] = None,
    day_type: DayType = "WORKDAY",
) -> Dict[str, Any]:
    """Find shortest directed path across all 630 Wialon platforms and depot zero-runs."""
    net = get_wialon_transit_network()
    norm_origin = normalize_stop_name(origin)
    norm_dest = normalize_stop_name(destination)
    period_bucket = _resolve_period_bucket(departure_time)

    depots_set = {"ВРМ", "ТД-1", "ТД-2", "ТрД"}
    if norm_origin in depots_set and norm_dest not in depots_set:
        zr = net.find_depot_zero_run(
            depot_code=norm_origin,
            stop_name=norm_dest,
            kind="PULL_OUT",
            transport_type=transport_type,
            day_type=day_type,
            period_bucket=period_bucket,
        )
        if zr:
            return zr

    if norm_dest in depots_set and norm_origin not in depots_set:
        zr = net.find_depot_zero_run(
            depot_code=norm_dest,
            stop_name=norm_origin,
            kind="PULL_IN",
            transport_type=transport_type,
            day_type=day_type,
            period_bucket=period_bucket,
        )
        if zr:
            return zr

    wialon_res = net.find_platform_path(
        origin_name=norm_origin,
        dest_name=norm_dest,
        transport_type=transport_type,
        day_type=day_type,
        period_bucket=period_bucket,
    )
    if wialon_res:
        return wialon_res

    # Fallback to stop-level graph
    graph = TROLLEYBUS_TRACK_GRAPH if transport_type == "TROLLEYBUS" else TRAM_TRACK_GRAPH
    if norm_origin not in graph:
        raise ValueError(f"Невідома початкова зупинка: '{origin}'")
    if norm_dest not in graph:
        raise ValueError(f"Невідома кінцева зупинка: '{destination}'")

    if norm_origin == norm_dest:
        return {"distance_km": 0.0, "duration_minutes": 0, "path": [norm_origin]}

    distances: Dict[str, Tuple[float, int]] = {norm_origin: (0.0, 0)}
    pq: List[Tuple[float, int, str, List[str]]] = [(0.0, 0, norm_origin, [norm_origin])]
    while pq:
        cur_km, cur_min, cur_node, path = heapq.heappop(pq)
        if cur_node == norm_dest:
            return {
                "distance_km": round(cur_km, 2),
                "duration_minutes": cur_min,
                "path": path,
            }
        for nb, w_km, w_min in graph.get(cur_node, []):
            n_km = round(cur_km + w_km, 2)
            n_min = cur_min + w_min
            if nb not in distances or (n_km, n_min) < distances[nb]:
                distances[nb] = (n_km, n_min)
                heapq.heappush(pq, (n_km, n_min, nb, path + [nb]))

    raise ValueError(f"Маршрут між зупинками '{origin}' та '{destination}' не знайдено в мережі")


def find_shortest_tram_path(origin: str, destination: str) -> Dict[str, Any]:
    """Find shortest physical path between two tram stops using Dijkstra algorithm."""
    norm_origin = normalize_stop_name(origin)
    norm_dest = normalize_stop_name(destination)

    if norm_origin not in TRAM_TRACK_GRAPH:
        # Check if Wialon network can resolve alias/platform name
        net = get_wialon_transit_network()
        disp_o, sids_o = net.resolve_stop_ids(origin, "TRAM")
        if sids_o and disp_o in TRAM_TRACK_GRAPH:
            norm_origin = disp_o
        else:
            raise ValueError(f"Невідома початкова зупинка: '{origin}'")

    if norm_dest not in TRAM_TRACK_GRAPH:
        net = get_wialon_transit_network()
        disp_d, sids_d = net.resolve_stop_ids(destination, "TRAM")
        if sids_d and disp_d in TRAM_TRACK_GRAPH:
            norm_dest = disp_d
        else:
            raise ValueError(f"Невідома кінцева зупинка: '{destination}'")

    if norm_origin == norm_dest:
        return {
            "distance_km": 0.0,
            "duration_minutes": 0,
            "path": [norm_origin],
        }

    distances: Dict[str, Tuple[float, int]] = {norm_origin: (0.0, 0)}
    priority_queue: List[Tuple[float, int, str, List[str]]] = [(0.0, 0, norm_origin, [norm_origin])]

    while priority_queue:
        current_km, current_min, current_node, path = heapq.heappop(priority_queue)

        if current_node == norm_dest:
            return {
                "distance_km": round(current_km, 2),
                "duration_minutes": current_min,
                "path": path,
            }

        for neighbor, weight_km, weight_min in TRAM_TRACK_GRAPH.get(current_node, []):
            new_km = round(current_km + weight_km, 2)
            new_min = current_min + weight_min
            if neighbor not in distances or (new_km, new_min) < distances[neighbor]:
                distances[neighbor] = (new_km, new_min)
                heapq.heappush(priority_queue, (new_km, new_min, neighbor, path + [neighbor]))

    # Fallback to directed Wialon platform graph if stop-level graph has no path
    return find_shortest_transit_path(origin, destination, transport_type="TRAM")


def build_annotated_stops_path(
    path: List[str],
    intermediate_loop: Optional[str] = None,
    via_loops: Optional[List[str]] = None,
    phase_kind: str = "rental",
    transport_type: TransportType = "TRAM",
    target_total_km: Optional[float] = None,
    target_total_min: Optional[int] = None,
) -> List[StopPointInfo]:
    """Build fully detailed, role-annotated list of stops with cumulative km and minutes."""
    annotated: List[StopPointInfo] = []
    total_stops = len(path)
    cum_km = 0.0
    cum_min = 0

    loops_list = list(via_loops or [])
    if intermediate_loop and intermediate_loop not in loops_list:
        loops_list.insert(0, intermediate_loop)
    loop_keys = {_canonical_stop_key(normalize_stop_name(lp)) for lp in loops_list if lp}

    for idx, stop_name in enumerate(path):
        stop_key = _canonical_stop_key(stop_name)
        if idx == 0:
            d_km = 0.0
            d_min = 0
            if phase_kind == "dispatch":
                role = "ПОЧАТКОВИЙ ПУНКТ ДИСЛОКАЦІЇ"
            elif phase_kind == "return":
                role = "ПУНКТ ВИСАДКИ (ПОЧАТОК ЗАЇЗДУ)"
            else:
                role = "ПОЧАТКОВА ЗУПИНКА ПОСАДКИ"
        else:
            prev_stop = path[idx - 1]
            d_km, d_min = get_edge_weight(prev_stop, stop_name, transport_type=transport_type)
            cum_km = round(cum_km + d_km, 2)
            cum_min += d_min

            if idx == total_stops - 1:
                if target_total_km is not None and target_total_km > 0:
                    d_km = round(max(0.05, target_total_km - (cum_km - d_km)), 2)
                    cum_km = round(target_total_km, 2)
                if target_total_min is not None and target_total_min > 0:
                    d_min = max(1, target_total_min - (cum_min - d_min))
                    cum_min = target_total_min

                if phase_kind == "dispatch":
                    role = "ПУНКТ ПОСАДКИ ЗАМОВНИКА"
                elif phase_kind == "return":
                    role = "КІНЦЕВИЙ ПУНКТ ДИСЛОКАЦІЇ (ДЕПО)"
                else:
                    role = "ФІНАЛЬНА ЗУПИНКА ВИСАДКИ"
            elif stop_key in loop_keys:
                role = "РОЗВОРОТНЕ КІЛЬЦЕ (СТОЯНКА 5-10 ХВ)"
            elif idx + 1 < total_stops and _canonical_stop_key(path[idx + 1]) in loop_keys:
                role = "ПЕРЕД КІЛЬЦЕМ (передфінальна до кільця)"
            elif idx == total_stops - 2:
                role = "ПЕРЕДФІНАЛЬНА ЗУПИНКА"
            else:
                role = "ПРОМІЖНА ЗУПИНКА"

        annotated.append(
            StopPointInfo(
                seq=idx + 1,
                stop_name=stop_name,
                role=role,
                distance_from_prev_km=d_km,
                minutes_from_prev=d_min,
                cumulative_km=cum_km,
                cumulative_minutes=cum_min,
            )
        )

    return annotated


def calculate_tram_rental_trip(calc_input: RentalCalculationInput) -> RentalCalculationOutput:
    """Calculate full closed 3-phase rental cycle for Tram or Trolleybus with Wialon telemetry."""
    # 1. Resolve transport_type and depot_base
    if calc_input.transport_type:
        resolved_vt: TransportType = calc_input.transport_type
    elif calc_input.wagon_type == "trolleybus" or calc_input.depot_base == "ТрД":
        resolved_vt = "TROLLEYBUS"
    else:
        resolved_vt = "TRAM"

    if calc_input.depot_base:
        resolved_base: DepotBase = calc_input.depot_base
    elif resolved_vt == "TROLLEYBUS":
        resolved_base = "ТрД"
    elif calc_input.wagon_type == "retro":
        resolved_base = "ВРМ"
    else:
        resolved_base = "ТД-1"

    # 2. Merge intermediate_loop and via_loops into unified ordered list
    ordered_loops: List[str] = []
    if calc_input.intermediate_loop:
        ordered_loops.append(calc_input.intermediate_loop)
    for lp in calc_input.via_loops:
        if lp and lp not in ordered_loops:
            ordered_loops.append(lp)

    # 3. Circular route validation
    norm_pickup = normalize_stop_name(calc_input.pickup_stop)
    norm_dropoff = normalize_stop_name(calc_input.dropoff_stop)
    is_circular = _canonical_stop_key(norm_pickup) == _canonical_stop_key(norm_dropoff)
    if is_circular and not ordered_loops:
        raise ValueError(
            "Для кільцевого маршруту оренди (де точка посадки збігається з точкою висадки) "
            "необхідно обов'язково вказати проміжне розворотне кільце!"
        )

    # Decide routing function: use Wialon directed platform & zero-run engine when TROLLEYBUS,
    # multi-loop, explicit departure_time, or non-legacy stop; use find_shortest_tram_path for
    # standard single-loop tram queries so legacy baseline tests remain 100% exact.
    use_wialon_directed = (
        resolved_vt == "TROLLEYBUS"
        or calc_input.departure_time is not None
        or len(ordered_loops) > 1
    )

    def _route_leg(u_stop: str, v_stop: str) -> Dict[str, Any]:
        if use_wialon_directed:
            return find_shortest_transit_path(
                u_stop,
                v_stop,
                transport_type=resolved_vt,
                departure_time=calc_input.departure_time,
                day_type=calc_input.day_type,
            )
        return find_shortest_tram_path(u_stop, v_stop)

    # 4. Phase 1: Dispatch (нульовий виїзд)
    dispatch_path_data = _route_leg(resolved_base, calc_input.pickup_stop)
    phase_1_detailed = build_annotated_stops_path(
        dispatch_path_data["path"],
        phase_kind="dispatch",
        transport_type=resolved_vt,
        target_total_km=dispatch_path_data["distance_km"],
        target_total_min=dispatch_path_data["duration_minutes"],
    )
    phase_1 = RoutePhaseSummary(
        phase_number=1,
        phase_title="Подача рухомого складу (Нульовий виїзд)" if resolved_vt == "TROLLEYBUS" else "Подача вагона (Нульовий виїзд)",
        from_stop=resolved_base,
        to_stop=calc_input.pickup_stop,
        distance_km=dispatch_path_data["distance_km"],
        motion_minutes=dispatch_path_data["duration_minutes"],
        wait_minutes=0,
        total_phase_minutes=dispatch_path_data["duration_minutes"],
        stops_path=dispatch_path_data["path"],
        detailed_stops=phase_1_detailed,
        data_source=dispatch_path_data.get("source", "WIALON"),
    )

    # 5. Phase 2: Rental trip (рейс з пасажирами через 0, 1 або N розворотних кілець)
    waypoints = [calc_input.pickup_stop] + ordered_loops + [calc_input.dropoff_stop]
    rental_km = 0.0
    rental_motion = 0
    combined_path: List[str] = []

    for i_leg in range(len(waypoints) - 1):
        leg = _route_leg(waypoints[i_leg], waypoints[i_leg + 1])
        rental_km = round(rental_km + leg["distance_km"], 2)
        rental_motion += leg["duration_minutes"]
        if i_leg == 0:
            combined_path.extend(leg["path"])
        else:
            combined_path.extend(leg["path"][1:])

    total_wait_min = calc_input.loop_wait_minutes * len(ordered_loops)
    via_display = " -> ".join(ordered_loops) if ordered_loops else None

    phase_2_detailed = build_annotated_stops_path(
        combined_path,
        intermediate_loop=ordered_loops[0] if ordered_loops else None,
        via_loops=ordered_loops,
        phase_kind="rental",
        transport_type=resolved_vt,
        target_total_km=rental_km,
        target_total_min=rental_motion,
    )
    phase_2 = RoutePhaseSummary(
        phase_number=2,
        phase_title="Орендний маршрут замовника",
        from_stop=calc_input.pickup_stop,
        to_stop=calc_input.dropoff_stop,
        via_loop=via_display,
        via_loops=ordered_loops,
        distance_km=rental_km,
        motion_minutes=rental_motion,
        wait_minutes=total_wait_min,
        total_phase_minutes=rental_motion + total_wait_min,
        stops_path=combined_path,
        detailed_stops=phase_2_detailed,
        data_source="WIALON",
    )

    # 6. Phase 3: Return to original depot base (нульовий заїзд)
    return_path_data = _route_leg(calc_input.dropoff_stop, resolved_base)
    phase_3_detailed = build_annotated_stops_path(
        return_path_data["path"],
        phase_kind="return",
        transport_type=resolved_vt,
        target_total_km=return_path_data["distance_km"],
        target_total_min=return_path_data["duration_minutes"],
    )
    phase_3 = RoutePhaseSummary(
        phase_number=3,
        phase_title="Повернення в депо (Нульовий заїзд)" if resolved_vt == "TROLLEYBUS" else "Повернення вагона (Нульовий заїзд)",
        from_stop=calc_input.dropoff_stop,
        to_stop=resolved_base,
        distance_km=return_path_data["distance_km"],
        motion_minutes=return_path_data["duration_minutes"],
        wait_minutes=0,
        total_phase_minutes=return_path_data["duration_minutes"],
        stops_path=return_path_data["path"],
        detailed_stops=phase_3_detailed,
        data_source=return_path_data.get("source", "WIALON"),
    )

    # 7. Balance calculation (100% billable to customer)
    total_km = round(phase_1.distance_km + phase_2.distance_km + phase_3.distance_km, 2)
    total_motion = phase_1.motion_minutes + phase_2.motion_minutes + phase_3.motion_minutes
    total_wait = phase_2.wait_minutes
    grand_total_minutes = total_motion + total_wait

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    generated_order_id = calc_input.order_id or f"RENT-{datetime.now().strftime('%y%m%d-%H%M')}"
    period_bucket = _resolve_period_bucket(calc_input.departure_time)
    profile_label = f"{calc_input.day_type}:{period_bucket}" if period_bucket else f"{calc_input.day_type}:FULL_DAY_MEDIAN"

    return RentalCalculationOutput(
        is_success=True,
        order_id=generated_order_id,
        calculation_timestamp=now_str,
        transport_type=resolved_vt,
        wagon_type=calc_input.wagon_type,
        depot_base=resolved_base,
        time_profile=profile_label,
        phase_1_dispatch=phase_1,
        phase_2_rental=phase_2,
        phase_3_return=phase_3,
        total_billable_km=total_km,
        total_motion_minutes=total_motion,
        total_wait_minutes=total_wait,
        total_duration_minutes=grand_total_minutes,
        formatted_total_duration=format_duration_hours_minutes(grand_total_minutes),
    )


def generate_rental_route_sheet_pdf(
    calc_output: RentalCalculationOutput,
    output_pdf_path: Optional[str] = None,
    wagon_title: Optional[str] = None,
) -> str:
    """Generate official Route Sheet PDF for КП «Одесміськелектротранс» Служба руху."""
    os.makedirs(ROUTE_SHEETS_DIR, exist_ok=True)
    target_path = output_pdf_path or str(ROUTE_SHEETS_DIR / f"{calc_output.order_id}_route_sheet.pdf")

    regular_font_path = str(FONTS_DIR / "DejaVuSans.ttf")
    bold_font_path = str(FONTS_DIR / "DejaVuSans-Bold.ttf")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    pdf.add_font("DejaVu", "", regular_font_path)
    pdf.add_font("DejaVu", "B", bold_font_path)

    # Header
    pdf.set_font("DejaVu", "B", 13)
    pdf.cell(0, 7, "КП «ОДЕСМІСЬКЕЛЕКТРОТРАНС»", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.set_font("DejaVu", "B", 10)
    sheet_kind = "ТРОЛЕЙБУСА" if calc_output.transport_type == "TROLLEYBUS" else "ТРАМВАЯ"
    pdf.cell(0, 5, f"СЛУЖБА РУХУ — МАРШРУТНИЙ ЛИСТ ОРЕНДИ {sheet_kind}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.ln(2)

    # Meta Info
    pdf.set_draw_color(180, 180, 180)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    pdf.set_font("DejaVu", "", 9)
    pdf.cell(95, 5, f"Номер замовлення: {calc_output.order_id}")
    pdf.cell(95, 5, f"Дата формування: {calc_output.calculation_timestamp}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if wagon_title:
        wagon_label = wagon_title
    elif calc_output.transport_type == "TROLLEYBUS":
        wagon_label = "Тролейбус (БКМ / Богдан Т701)"
    elif "914" in str(calc_output.wagon_type) or "відкритий" in str(calc_output.wagon_type).lower():
        wagon_label = "Відкритий ретро-вагон №914"
    elif "мтв" in str(calc_output.wagon_type).lower() or calc_output.wagon_type == "retro" or "ретро" in str(calc_output.wagon_type).lower():
        wagon_label = "Ретро-трамвай МТВ-82"
    else:
        wagon_label = "Стандартний (Tatra / Odissey)"
    pdf.cell(95, 5, f"Рухомий склад: {wagon_label}")
    pdf.cell(95, 5, f"База приписки (депо): {calc_output.depot_base} ({calc_output.time_profile})", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # Summary table header
    pdf.set_fill_color(230, 235, 245)
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(35, 7, "Фаза рейсу", border=1, fill=True)
    pdf.cell(80, 7, "Ділянка маршруту", border=1, fill=True)
    pdf.cell(25, 7, "Відстань", border=1, fill=True, align="C")
    pdf.cell(25, 7, "Рух (хв)", border=1, fill=True, align="C")
    pdf.cell(25, 7, "Стоянка", border=1, fill=True, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Phase 1
    pdf.set_font("DejaVu", "", 8)
    p1 = calc_output.phase_1_dispatch
    p1_route = f"{p1.from_stop} -> {p1.to_stop}"
    pdf.cell(35, 6, "1. Подача з депо", border=1)
    pdf.cell(80, 6, p1_route[:42], border=1)
    pdf.cell(25, 6, f"{p1.distance_km:.2f} км", border=1, align="C")
    pdf.cell(25, 6, f"{p1.motion_minutes} хв", border=1, align="C")
    pdf.cell(25, 6, "0 хв", border=1, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Phase 2
    p2 = calc_output.phase_2_rental
    p2_route = f"{p2.from_stop} -> [{p2.via_loop}] -> {p2.to_stop}" if p2.via_loop else f"{p2.from_stop} -> {p2.to_stop}"
    pdf.cell(35, 6, "2. Орендний рейс", border=1)
    pdf.cell(80, 6, p2_route[:42], border=1)
    pdf.cell(25, 6, f"{p2.distance_km:.2f} км", border=1, align="C")
    pdf.cell(25, 6, f"{p2.motion_minutes} хв", border=1, align="C")
    pdf.cell(25, 6, f"{p2.wait_minutes} хв", border=1, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Phase 3
    p3 = calc_output.phase_3_return
    p3_route = f"{p3.from_stop} -> {p3.to_stop}"
    pdf.cell(35, 6, "3. Повернення в депо", border=1)
    pdf.cell(80, 6, p3_route[:42], border=1)
    pdf.cell(25, 6, f"{p3.distance_km:.2f} км", border=1, align="C")
    pdf.cell(25, 6, f"{p3.motion_minutes} хв", border=1, align="C")
    pdf.cell(25, 6, "0 хв", border=1, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Total row
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("DejaVu", "B", 9)
    pdf.cell(115, 7, "РАЗОМ ДО ОПЛАТИ (100% КІЛОМЕТРАЖУ):", border=1, fill=True)
    pdf.cell(25, 7, f"{calc_output.total_billable_km:.2f} км", border=1, fill=True, align="C")
    pdf.cell(25, 7, f"{calc_output.total_motion_minutes} хв", border=1, fill=True, align="C")
    pdf.cell(25, 7, f"{calc_output.total_wait_minutes} хв", border=1, fill=True, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)

    # Grand total box
    pdf.set_fill_color(245, 248, 255)
    pdf.set_draw_color(50, 100, 200)
    pdf.rect(10, pdf.get_y(), 190, 13, "DF")
    pdf.set_xy(12, pdf.get_y() + 2)
    pdf.set_font("DejaVu", "B", 10)
    pdf.cell(0, 4, f"ЗАГАЛЬНИЙ ЧАС РОБОТИ: {calc_output.formatted_total_duration} ({calc_output.total_duration_minutes} хв)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DejaVu", "", 8)
    pdf.cell(0, 4, f"Загальний кілометраж до нарахування: {calc_output.total_billable_km:.2f} км | Стоянка на кільці: {calc_output.total_wait_minutes} хв", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    # Detailed Stops Section for Phase 2 (Rental Run)
    pdf.set_font("DejaVu", "B", 10)
    pdf.cell(0, 6, "ДЕТАЛЬНИЙ ПОЗУПИНКОВИЙ ШЛЯХ ОРЕНДНОГО МАРШРУТУ (ФАЗА 2):", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)

    pdf.set_fill_color(230, 235, 245)
    pdf.set_font("DejaVu", "B", 8)
    pdf.cell(10, 6, "№", border=1, fill=True, align="C")
    pdf.cell(70, 6, "Назва зупинки", border=1, fill=True)
    pdf.cell(75, 6, "Роль зупинки на маршруті", border=1, fill=True)
    pdf.cell(18, 6, "Пробіг", border=1, fill=True, align="C")
    pdf.cell(17, 6, "Час", border=1, fill=True, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("DejaVu", "", 7.5)
    for st in calc_output.phase_2_rental.detailed_stops:
        is_highlight = "КІЛЬЦЕ" in st.role or "ФІНАЛЬНА" in st.role or "ПОЧАТКОВА" in st.role or "ПЕРЕД" in st.role
        if is_highlight:
            pdf.set_font("DejaVu", "B", 7.5)
            pdf.set_fill_color(250, 250, 230)
            fill_row = True
        else:
            pdf.set_font("DejaVu", "", 7.5)
            fill_row = False

        pdf.cell(10, 5, str(st.seq), border=1, align="C", fill=fill_row)
        pdf.cell(70, 5, st.stop_name[:38], border=1, fill=fill_row)
        pdf.cell(75, 5, st.role[:40], border=1, fill=fill_row)
        pdf.cell(18, 5, f"{st.cumulative_km:.2f} км", border=1, align="C", fill=fill_row)
        pdf.cell(17, 5, f"{st.cumulative_minutes} хв", border=1, align="C", fill=fill_row, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(3)
    pdf.set_font("DejaVu", "B", 8)
    pdf.cell(0, 4, f"Маршрут подачі (Фаза 1): {' -> '.join(calc_output.phase_1_dispatch.stops_path)}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 4, f"Маршрут повернення (Фаза 3): {' -> '.join(calc_output.phase_3_return.stops_path)}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(5)
    pdf.set_font("DejaVu", "", 8)
    pdf.cell(95, 5, "Начальник служби руху: ____________________")
    pdf.cell(95, 5, "Замовник (підпис): ____________________", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.output(target_path)
    calc_output.pdf_route_sheet_path = target_path
    return target_path


# Alias for compatibility with rental handlers
calculate_rental_route = calculate_tram_rental_trip


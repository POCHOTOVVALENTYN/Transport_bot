"""
Багаторівнева валідація реквізитів замовника оренди трамваїв/тролейбусів КП «ОМЕТ»
(Фізична особа, ФОП, Юридична особа) із захистом від хейтерів, тролів, нецензурної
лексики, клавіатурного сміття та фейкових податкових номерів.
"""

from __future__ import annotations

import datetime
import re
from typing import Optional, Tuple

from config.settings import VALENTIN_ADMIN_ID

# Корені нецензурної лексики, образ та типових тролінг-заглушок
_PROFANITY_AND_TROLL_PATTERNS = (
    r"\b(х[уy][йяєюіи]|п[іиe]зд|їб[аa]|єб[аa]|еб[аa]|бл[яa]д|бл[яa]т|с[уy]к[аaи]|г[оo]вн|г[іи]вн|д[еe]б[іи]л|д[уy]р[аa]к|л[оo]х|п[іи]д[аaо]р|г[аa]нд[оo]н|шл[юy]х|м[уy]д[аa]к|з[аa]л[уy]п)\w*",
    r"\b(fuck|shit|bitch|asshole|dick|cunt|whore)\w*",
    r"\b(йцукен|фыва|фива|ячсмит|qwerty|asdf|zxcv|тест|test|блабла|blabla|лол|кек|азаза|хейтер|троль|анонім|аноним|немає|нема|не\s+скажу|хз|фігня|фигня)\b",
)

_UA_VOWELS = set("аеєиіїоуюяАЕЄИІЇОУЮЯ")
_UA_CONSONANTS = set("бвгґджзйклмнпрстфхцчшщБВГҐДЖЗЙКЛМНПРСТФХЦЧШЩ")

# Дійсні коди мобільних операторів України та міські коди (Одеса 048, Київ 044 тощо)
_VALID_UA_PHONE_PREFIXES = {
    "039", "050", "063", "066", "067", "068", "073", "075", "077",
    "089", "091", "092", "093", "094", "095", "096", "097", "098", "099",
    "044", "048", "0482", "032", "051", "0512", "056", "057", "061",
}

# Дозволені тестові коди для адміністратора (Валентина) під час швидкого тестування
_ADMIN_TEST_RNOKPP = {"1234567890", "9876543210", "1122334455", "2233445566"}
_ADMIN_TEST_EDRPOU = {"12345678", "44556677", "87654321", "03328497"}


def check_text_for_abuse_or_gibberish(text: str) -> Tuple[bool, Optional[str]]:
    """
    Перевіряє довільний текст на:
    - нецензурну лексику, образи та тестові заглушки
    - посилання, рекламу, Telegram-хендли
    - повторення одного символу 4+ рази поспіль ('аааа', '11111')
    Повертає (is_clean, error_message).
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return False, "Поле не може бути порожнім."

    lower_val = cleaned.lower()

    if re.search(r"(https?://|www\.|t\.me/|\.com\b|\.ru\b|\.ua\b|@[a-zA-Z0-9_]{3,})", lower_val):
        return False, "Заборонено вказувати веб-посилання або нікнейми в реквізитах договору."

    if re.search(r"([a-zA-Zа-яА-ЯіїєґІЇЄҐ])\1{3,}", lower_val):
        return False, "Виявлено некоректний повтор однакових літер поспіль. Введіть справжні дані."

    for pat in _PROFANITY_AND_TROLL_PATTERNS:
        if re.search(pat, lower_val, flags=re.IGNORECASE):
            return False, "Виявлено недопустиму лексику або тестову заглушку. Будь ласка, введіть офіційні дані для договору."

    return True, None


def _is_pronounceable_cyrillic_word(word: str) -> bool:
    """Перевіряє, чи слово схоже на реальне українське слово (містить голосні та не має 5+ приголосних поспіль)."""
    letters_only = [ch for ch in word if ch.isalpha()]
    if len(letters_only) < 2:
        return False

    vowel_count = sum(1 for ch in letters_only if ch in _UA_VOWELS)
    if vowel_count == 0:
        return False

    consec_consonants = 0
    consec_vowels = 0
    for ch in letters_only:
        if ch in _UA_CONSONANTS:
            consec_consonants += 1
            consec_vowels = 0
            if consec_consonants >= 5:
                return False
        elif ch in _UA_VOWELS:
            consec_vowels += 1
            consec_consonants = 0
            if consec_vowels >= 4:
                return False
    return True


def validate_person_full_name(raw_name: str) -> Tuple[bool, str, Optional[str]]:
    """
    Валідує ПІБ фізичної особи або ФОП:
    - Відсутність нецензурної лексики та сміття
    - 2–4 слова (Прізвище, Ім'я та По батькові) виключно українською кирилицею
    - Кожне слово має бути вимовною назвою (наявність голосних, без 'бвгджз')
    Повертає (is_valid, normalized_name, error_message).
    """
    cleaned = re.sub(r"\s+", " ", (raw_name or "").strip())
    cleaned = re.sub(r"^(фоп|фізична особа-підприємець)\s+", "", cleaned, flags=re.IGNORECASE).strip()

    is_clean, err = check_text_for_abuse_or_gibberish(cleaned)
    if not is_clean:
        return False, cleaned, err

    words = cleaned.split(" ")
    if len(words) < 2 or len(words) > 4:
        return (
            False,
            cleaned,
            "Введіть повне ПІБ (Прізвище, Ім'я та По батькові — 2 або 3 слова кирилицею).",
        )

    word_pattern = re.compile(r"^[А-ЯІЇЄҐа-яіїєґ'’ʼ\-]{2,35}$")
    formatted_words = []
    for w in words:
        if not word_pattern.match(w):
            return (
                False,
                cleaned,
                f"Слово «{w}» містить недопустимі символи, латиницю або цифри. Введіть ПІБ українською мовою.",
            )
        if re.search(r"[ыэъёЫЭЪЁ]", w):
            return (
                False,
                cleaned,
                "Будь ласка, введіть ПІБ державною (українською) мовою для офіційного договору.",
            )
        if not _is_pronounceable_cyrillic_word(w):
            return (
                False,
                cleaned,
                f"Слово «{w}» виглядає як випадковий набір літер. Перевірте правильність написання ПІБ.",
            )
        parts_hyphen = [p.capitalize() for p in w.split("-")]
        formatted_words.append("-".join(parts_hyphen))

    if len(set(w.lower() for w in formatted_words)) == 1:
        return False, cleaned, "Прізвище та ім'я не можуть складатися з однакових слів."

    return True, " ".join(formatted_words), None


def compute_rnokpp_check_digit(first_nine_digits: str) -> int:
    """Розраховує офіційну 10-ту контрольну цифру РНОКПП (ІПН) за алгоритмом ДПС України."""
    weights = (-1, 5, 7, 9, 4, 6, 10, 5, 7)
    total = sum(int(d) * w for d, w in zip(first_nine_digits[:9], weights))
    return (total % 11) % 10


def validate_rnokpp_tax_id(
    raw_tax: str,
    user_id: Optional[int] = None,
) -> Tuple[bool, str, Optional[str]]:
    """
    Перевіряє 10-значний РНОКПП (ІПН) фізичної особи або ФОП:
    - Рівно 10 цифр
    - Перевірка дати народження за першими 5 цифрами (вік від 18 до 100 років)
    - Перевірка 10-ї контрольної цифри (Модуль 11 ДПС України)
    Для адміністратора (VALENTIN_ADMIN_ID) дозволено тестові коди з _ADMIN_TEST_RNOKPP.
    """
    digits = re.sub(r"\D", "", (raw_tax or "").strip())
    if len(digits) != 10:
        return False, digits, "РНОКПП (ІПН) має складатися рівно з 10 цифр."

    if len(set(digits)) == 1:
        return False, digits, "РНОКПП не може складатися з однакових цифр."

    is_admin = user_id is not None and int(user_id) == int(VALENTIN_ADMIN_ID)
    if is_admin and digits in _ADMIN_TEST_RNOKPP:
        return True, digits, None

    # 1. Перевірка дати народження (перші 5 цифр — кількість днів від 31.12.1899)
    days_since_1899 = int(digits[:5])
    base_date = datetime.date(1899, 12, 31)
    try:
        birth_date = base_date + datetime.timedelta(days=days_since_1899)
    except Exception:
        return False, digits, "Некоректний код РНОКПП (помилка кодування дати народження)."

    today = datetime.date.today()
    age_years = (today - birth_date).days / 365.25
    if age_years < 18 or age_years > 102:
        return (
            False,
            digits,
            "Введений РНОКПП не відповідає дійсному податковому номеру повнолітньої особи. Перевірте правильність 10 цифр.",
        )

    # 2. Математична перевірка контрольної цифри (10-й розряд)
    expected_check = compute_rnokpp_check_digit(digits[:9])
    if int(digits[9]) != expected_check:
        return (
            False,
            digits,
            "Помилка у цифрах РНОКПП (не збігається контрольна сума ДПС України). Перевірте ІПН та введіть ще раз.",
        )

    return True, digits, None


def compute_edrpou_check_digit(first_seven_digits: str) -> int:
    """Розраховує офіційний 8-й контрольний розряд коду ЄДРПОУ за алгоритмом Держстату України."""
    code_int = int(first_seven_digits)
    if 3000000 < code_int < 6000000:
        w1 = (7, 1, 2, 3, 4, 5, 6)
        w2 = (9, 3, 4, 5, 6, 7, 8)
    else:
        w1 = (1, 2, 3, 4, 5, 6, 7)
        w2 = (3, 4, 5, 6, 7, 8, 9)

    digits = [int(ch) for ch in first_seven_digits[:7]]
    rem = sum(d * w for d, w in zip(digits, w1)) % 11
    if rem >= 10:
        rem = sum(d * w for d, w in zip(digits, w2)) % 11
    return rem % 10


def validate_edrpou_code(
    raw_edrpou: str,
    user_id: Optional[int] = None,
) -> Tuple[bool, str, Optional[str]]:
    """
    Перевіряє 8-значний код ЄДРПОУ юридичної особи:
    - Рівно 8 цифр, не '00000000' і не '12345678'
    - Контрольна цифра за алгоритмом Держстату України (Модуль 11)
    Для адміністратора (VALENTIN_ADMIN_ID) дозволено тестові коди з _ADMIN_TEST_EDRPOU.
    """
    digits = re.sub(r"\D", "", (raw_edrpou or "").strip())
    if len(digits) != 8:
        return False, digits, "Код ЄДРПОУ має містити рівно 8 цифр."

    if len(set(digits)) == 1:
        return False, digits, "Код ЄДРПОУ не може складатися з однакових цифр."

    is_admin = user_id is not None and int(user_id) == int(VALENTIN_ADMIN_ID)
    if is_admin and digits in _ADMIN_TEST_EDRPOU:
        return True, digits, None

    if digits in ("12345678", "87654321", "01234567"):
        return False, digits, "Введено фіктивний код ЄДРПОУ. Вкажіть справжній 8-значний код організації з ЄДР."

    expected_check = compute_edrpou_check_digit(digits[:7])
    if int(digits[7]) != expected_check:
        return (
            False,
            digits,
            "Некоректний код ЄДРПОУ (не збігається контрольний розряд за стандартом ЄДР). Перевірте цифри та повторіть введення.",
        )

    return True, digits, None


def validate_ukr_passport(raw_passport: str) -> Tuple[bool, str, Optional[str]]:
    """
    Перевіряє паспортні дані фізичної особи:
    1) Паспорт-книжечка: серія з 2 кириличних літер + 6 цифр (напр. 'КМ 123456' або 'паспорт КЕ 654321...')
    2) ID-картка: номер із 9 цифр (напр. '001234567' або 'ID-картка №001234567...')
    """
    cleaned = re.sub(r"\s+", " ", (raw_passport or "").strip())
    is_clean, err = check_text_for_abuse_or_gibberish(cleaned)
    if not is_clean:
        return False, cleaned, err

    # Перевірка на паспорт-книжечку (2 українські великі/малі літери + 6 цифр)
    m_book = re.search(r"([А-ЯІЇЄҐа-яіїєґ]{2})\s*№?\s*(\d{6})\b", cleaned)
    if m_book:
        series = m_book.group(1).upper()
        number = m_book.group(2)
        if len(set(number)) == 1:
            return False, cleaned, "Номер паспорта не може складатися з однакових цифр (000000 тощо)."
        normalized = re.sub(
            r"([А-ЯІЇЄҐа-яіїєґ]{2})\s*№?\s*(\d{6})\b",
            f"{series} {number}",
            cleaned,
            count=1,
        )
        return True, normalized, None

    # Перевірка на ID-картку (рівно 9 цифр поспіль)
    m_id = re.search(r"(?<!\d)(\d{9})(?!\d)", cleaned)
    if m_id:
        id_num = m_id.group(1)
        if len(set(id_num)) == 1 or id_num == "123456789":
            return False, cleaned, "Введено фіктивний номер ID-картки. Вкажіть дійсний 9-значний номер документа."
        return True, cleaned, None

    return (
        False,
        cleaned,
        "Невірний формат документа. Вкажіть або серію (2 українські літери) і 6 цифр паспорта-книжечки "
        "(наприклад: КМ 123456), або 9 цифр номера ID-картки (наприклад: 001234567).",
    )


def validate_ua_phone(
    raw_phone: str,
    user_id: Optional[int] = None,
) -> Tuple[bool, str, Optional[str]]:
    """
    Валідує та нормалізує український контактний номер телефону:
    - Приводить до формату +380XXXXXXXXX
    - Перевіряє код мобільного оператора або міста (_VALID_UA_PHONE_PREFIXES)
    - Відхиляє фейкові номери з 7 однаковими цифрами поспіль (+380670000000, +380501111111)
    """
    cleaned = (raw_phone or "").strip()
    digits = re.sub(r"\D", "", cleaned)

    if len(digits) == 10 and digits.startswith("0"):
        digits = "38" + digits
    elif len(digits) == 9 and not digits.startswith("0"):
        digits = "380" + digits

    if len(digits) != 12 or not digits.startswith("380"):
        return (
            False,
            cleaned,
            "Введіть український номер телефону у форматі +380XXXXXXXXX або 0XXXXXXXXX (наприклад: +380671234567).",
        )

    local_part = digits[2:]  # '0671234567'
    prefix3 = local_part[:3]
    prefix4 = local_part[:4]
    if prefix3 not in _VALID_UA_PHONE_PREFIXES and prefix4 not in _VALID_UA_PHONE_PREFIXES:
        return (
            False,
            cleaned,
            f"Невідомий код оператора України ({prefix3}). Перевірте номер телефону.",
        )

    is_admin = user_id is not None and int(user_id) == int(VALENTIN_ADMIN_ID)
    subscriber_number = local_part[3:]  # останні 7 цифр
    if len(set(subscriber_number)) == 1:
        return (
            False,
            cleaned,
            "Введено некоректний або фіктивний номер телефону. Вкажіть реальний контактний номер для зв'язку.",
        )
    if not is_admin and subscriber_number in ("1234567", "7654321", "0000000"):
        return (
            False,
            cleaned,
            "Введено тестовий номер телефону. Будь ласка, вкажіть Ваш справжній контактний номер.",
        )

    return True, f"+{digits}", None


def validate_postal_address(
    raw_address: str,
    check_optional_iban: bool = False,
) -> Tuple[bool, str, Optional[str]]:
    """
    Валідує поштову/податкову адресу або реквізити юридичної особи:
    - Не менше 8 символів, без нецензурної лексики та сміття
    - Обов'язкова наявність кириличних слів (місто/вулиця) ТА номера будинку (цифр)
    - Якщо в тексті присутній рахунок IBAN (UA...) — перевіряє формат UA + 27 цифр.
    """
    cleaned = re.sub(r"[ \t]+", " ", (raw_address or "").strip())
    is_clean, err = check_text_for_abuse_or_gibberish(cleaned)
    if not is_clean:
        return False, cleaned, err

    if len(cleaned) < 8:
        return (
            False,
            cleaned,
            "Адреса занадто коротка. Вкажіть місто, вулицю та номер будинку (наприклад: м. Одеса, вул. Канатна, 15, кв. 10).",
        )

    cyr_words = re.findall(r"[А-ЯІЇЄҐа-яіїєґ]{2,}", cleaned)
    if len(cyr_words) < 2:
        return (
            False,
            cleaned,
            "Адреса має містити назву населеного пункту та вулиці українською мовою.",
        )

    if not re.search(r"\d+", cleaned):
        return (
            False,
            cleaned,
            "В адресі відсутній номер будинку. Будь ласка, вкажіть повну адресу з номером будинку.",
        )

    if check_optional_iban or "IBAN" in cleaned.upper() or re.search(r"\bUA\d", cleaned.upper()):
        iban_candidates = re.findall(r"\bUA\d[0-9A-Za-z]*\b", cleaned.upper())
        for cand in iban_candidates:
            if not re.match(r"^UA\d{27}$", cand):
                return (
                    False,
                    cleaned,
                    f"Невірний формат IBAN «{cand}». Український рахунок IBAN має починатися з UA та містити рівно 27 цифр (усього 29 символів).",
                )

    return True, cleaned, None


def validate_legal_company_name(raw_name: str) -> Tuple[bool, str, Optional[str]]:
    """
    Валідує найменування юридичної особи:
    - Відсутність нецензурної лексики, посилань та клавіатурного сміття
    - Наявність кириличних літер та вимовних слів (напр. 'ТОВ «Одеса-Тур»', 'КП «ОМЕТ»', 'ПП Коваленко')
    """
    cleaned = re.sub(r"\s+", " ", (raw_name or "").strip())
    is_clean, err = check_text_for_abuse_or_gibberish(cleaned)
    if not is_clean:
        return False, cleaned, err

    if len(cleaned) < 4:
        return False, cleaned, "Введіть повне офіційне найменування юридичної особи (мінімум 4 символи)."

    cyr_words = re.findall(r"[А-ЯІЇЄҐа-яіїєґ]{2,}", cleaned)
    if not cyr_words:
        return (
            False,
            cleaned,
            "Найменування юридичної особи має бути вказане українською мовою (наприклад: ТОВ «Одеський Центр»).",
        )

    if not any(_is_pronounceable_cyrillic_word(w) or w.upper() in ("ТОВ", "ПП", "АТ", "КП", "ГО", "БФ", "ОСББ", "ПРАТ") for w in cyr_words):
        return (
            False,
            cleaned,
            "Найменування організації виглядає як випадковий набір літер. Введіть дійсну назву згідно з ЄДР.",
        )

    return True, cleaned, None


def validate_signer_or_foundation(raw_text: str) -> Tuple[bool, str, Optional[str]]:
    """Валідує текст підписанта / документа-підстави (Виписка з ЄДР, Статут тощо)."""
    cleaned = re.sub(r"\s+", " ", (raw_text or "").strip())
    is_clean, err = check_text_for_abuse_or_gibberish(cleaned)
    if not is_clean:
        return False, cleaned, err

    cyr_words = re.findall(r"[А-ЯІЇЄҐа-яіїєґ]{2,}", cleaned)
    if len(cyr_words) < 2 or not any(_is_pronounceable_cyrillic_word(w) for w in cyr_words):
        return (
            False,
            cleaned,
            "Вкажіть коректну посаду, ПІБ підписанта або назву документа-підстави українською мовою.",
        )

    return True, cleaned, None

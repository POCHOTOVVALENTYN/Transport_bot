import re
from aiogram import types, Dispatcher
from aiogram.dispatcher import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from bot.states import GratitudeForm
from services.tickets_service import register_gratitude  # Імпортуємо функцію з Кроку 2


# from handlers.menu_handlers import cmd_start # Імпорт для повернення в головне меню (опціонально)

# --- КЛАВІАТУРИ (МОЖНА ВИНЕСТИ ОКРЕМО) ---

def get_cancel_keyboard():
    mk = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    mk.add(KeyboardButton("🔙 Скасувати"), KeyboardButton("🏠 Головне меню"))
    return mk


def get_gratitude_type_keyboard():
    mk = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    mk.add(KeyboardButton("🎯 Написати конкретну подяку"), KeyboardButton("📢 Написати загальну"))
    mk.add(KeyboardButton("🔙 Скасувати"), KeyboardButton("🏠 Головне меню"))
    return mk


def get_transport_type_keyboard():
    mk = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    mk.add(KeyboardButton("🚋 Трамвай"), KeyboardButton("🚎 Тролейбус"))
    mk.add(KeyboardButton("🔙 Скасувати"), KeyboardButton("🏠 Головне меню"))
    return mk


def get_skip_keyboard():
    mk = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    mk.add(KeyboardButton("➡️ Пропустити"))
    mk.add(KeyboardButton("🔙 Скасувати"), KeyboardButton("🏠 Головне меню"))
    return mk


# --- ХЕНДЛЕРИ ---

# 1. Початок (тригер на кнопку з головного меню)
async def start_gratitude(message: types.Message):
    await GratitudeForm.waiting_for_type_selection.set()
    await message.answer(
        "Ваша подяка стосується конкретного водія/маршруту чи роботи підприємства загалом? 🧐👇",
        reply_markup=get_gratitude_type_keyboard()
    )


# 2. Обробка вибору типу (Конкретна / Загальна)
async def gratitude_type_chosen(message: types.Message, state: FSMContext):
    text = message.text

    if text == "🎯 Написати конкретну подяку":
        await state.update_data(is_specific=True)
        await GratitudeForm.waiting_for_transport_type.set()
        await message.answer(
            "Оберіть вид транспорту 🚋🚎:",
            reply_markup=get_transport_type_keyboard()
        )

    elif text == "📢 Написати загальну":
        await state.update_data(is_specific=False)
        await GratitudeForm.waiting_for_general_details.set()
        await message.answer(
            "Будь ласка, опишіть суть вашої вдячності 📝\n(Тільки текст, без стікерів)",
            reply_markup=get_cancel_keyboard()
        )
    else:
        await message.answer("Будь ласка, скористайтеся кнопками нижче 👇")


# --- ГІЛКА КОНКРЕТНОЇ ПОДЯКИ ---

# 3. Вибір транспорту
async def transport_chosen(message: types.Message, state: FSMContext):
    if message.text not in ["🚋 Трамвай", "🚎 Тролейбус"]:
        await message.answer("Будь ласка, оберіть Трамвай або Тролейбус, використовуючи кнопки.")
        return

    await state.update_data(transport_type=message.text)
    await GratitudeForm.waiting_for_vehicle_number.set()
    await message.answer(
        "Вкажіть бортовий номер (4 цифри), якщо пам'ятаєте 🔢\nАбо натисніть 'Пропустити'.",
        reply_markup=get_skip_keyboard()
    )


# 4. Бортовий номер
async def vehicle_number_input(message: types.Message, state: FSMContext):
    text = message.text
    if text == "➡️ Пропустити":
        vehicle_num = "Не вказано"
    else:
        # Валідація: тільки цифри, 3 або 4 знаки
        if not text.isdigit() or not (3 <= len(text) <= 4):
            await message.answer(
                "⚠️ Бортовий номер має складатись з 3 або 4 цифр. Спробуйте ще раз або натисніть 'Пропустити'.")
            return
        vehicle_num = text

    await state.update_data(vehicle_number=vehicle_num)
    await GratitudeForm.waiting_for_specific_details.set()
    await message.answer(
        "Напишіть, за що саме ви вдячні? 🌟\nТакож вкажіть П.І.Б. водія чи кондуктора, якщо знаєте.",
        reply_markup=get_cancel_keyboard()
    )


# 5. Текст подяки (Конкретна)
async def specific_details_input(message: types.Message, state: FSMContext):
    if len(message.text) < 5:
        await message.answer("Будь ласка, напишіть трохи детальніше (мінімум 5 символів) 🙏")
        return

    await state.update_data(message=message.text)
    # ПІБ водія можна спробувати витягнути з тексту, або просто зберегти весь текст як "message"
    # Для простоти зберігаємо все в 'message', а 'user_name' заповнимо пізніше або залишимо пустим для водія

    await GratitudeForm.waiting_for_email.set()
    await message.answer(
        "Вкажіть вашу електронну пошту 📧\nМи надішлемо вам підтвердження.",
        reply_markup=get_cancel_keyboard()
    )


# --- ГІЛКА ЗАГАЛЬНОЇ ПОДЯКИ ---

# 3 (Загальна). Текст подяки
async def general_details_input(message: types.Message, state: FSMContext):
    if len(message.text) < 5:
        await message.answer("Напишіть, будь ласка, трішки більше деталей 😊")
        return

    await state.update_data(message=message.text)
    await GratitudeForm.waiting_for_user_name.set()
    await message.answer(
        "Як ми можемо до вас звертатися? (Прізвище та Ім'я) 🤝",
        reply_markup=get_cancel_keyboard()
    )


# 4 (Загальна). ПІБ користувача
async def user_name_input(message: types.Message, state: FSMContext):
    if len(message.text.split()) < 2:
        await message.answer("Будь ласка, вкажіть Ім'я та Прізвище (мінімум 2 слова).")
        return

    await state.update_data(user_name=message.text)
    await GratitudeForm.waiting_for_email.set()
    await message.answer(
        "Вкажіть вашу електронну пошту 📧",
        reply_markup=get_cancel_keyboard()
    )


# --- ФІНАЛ (EMAIL) ---

async def email_input(message: types.Message, state: FSMContext):
    email = message.text
    # Проста валідація email
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        await message.answer("⚠️ Здається, це не схоже на email. Спробуйте ще раз (наприклад: name@gmail.com).")
        return

    await state.update_data(email=email)

    # Отримуємо всі дані
    data = await state.get_data()

    # Зберігаємо через сервіс
    try:
        ticket_id = await register_gratitude(data)
        await message.answer(
            f"🎉 <b>Дякуємо! Ваша подяка успішно зареєстрована!</b>\n"
            f"Реєстраційний номер: <code>{ticket_id}</code>\n\n"
            f"Ми обов'язково передамо ваші теплі слова! 💛💙",
            parse_mode="HTML",
            reply_markup=get_cancel_keyboard()  # Або повернути клавіатуру головного меню
        )
    except Exception as e:
        await message.answer(f"Сталася помилка при збереженні: {e}. Спробуйте пізніше.")

    await state.finish()


# --- СИСТЕМНІ ХЕНДЛЕРИ (СКАСУВАННЯ) ---

async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.finish()
    await message.answer("Дію скасовано. Повертаємось в меню.", reply_markup=types.ReplyKeyboardRemove())
    # Тут краще викликати функцію показу головного меню


# --- РЕЄСТРАЦІЯ ХЕНДЛЕРІВ ---
def register_thanks_handlers(dp: Dispatcher):
    # Глобальні команди скасування
    dp.register_message_handler(cancel_handler, state="*", text="🔙 Скасувати")
    dp.register_message_handler(cancel_handler, state="*",
                                text="🏠 Головне меню")  # Можна додати окрему логіку для "Головне меню"

    # Точка входу (текст кнопки з головного меню має співпадати!)
    dp.register_message_handler(start_gratitude, text="Висловити подяку", state="*")

    # Вибір типу
    dp.register_message_handler(gratitude_type_chosen, state=GratitudeForm.waiting_for_type_selection)

    # Гілка Конкретна
    dp.register_message_handler(transport_chosen, state=GratitudeForm.waiting_for_transport_type)
    dp.register_message_handler(vehicle_number_input, state=GratitudeForm.waiting_for_vehicle_number)
    dp.register_message_handler(specific_details_input, state=GratitudeForm.waiting_for_specific_details,
                                content_types=types.ContentType.TEXT)

    # Гілка Загальна
    dp.register_message_handler(general_details_input, state=GratitudeForm.waiting_for_general_details,
                                content_types=types.ContentType.TEXT)
    dp.register_message_handler(user_name_input, state=GratitudeForm.waiting_for_user_name)

    # Email (спільний)
    dp.register_message_handler(email_input, state=GratitudeForm.waiting_for_email)
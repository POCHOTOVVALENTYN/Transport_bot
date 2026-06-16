# Проєкт: Transport_bot — Пам'ять Проєкту та Архітектура

У цьому файлі зафіксовано архітектурні рішення, конфігурацію сервера та зміни у логіці бота для забезпечення наступності розробки.

---

## 1. Архітектурні рішення та Міграція

### 1.1 Перехід на SQLite та bare-metal
* **Проблема**: Oracle Cloud Free Tier VM має обмежений об'єм оперативної пам'яті (1 ГБ). Спроби запускати базу даних PostgreSQL та бота у Docker-контейнерах призводили до OOM (Out Of Memory) крашів системи.
* **Рішення**:
  * Проєкт мігрував на прямий запуск (bare-metal) через системну службу `systemd`.
  * Замість PostgreSQL підключено базу даних **SQLite**, що значно економить ресурси та забезпечує миттєвий відгук.
  * База даних на продакшні зберігається безпосередньо на диску в робочій директорії (файл `transport_bot.db`).
* **Конфігурація `DATABASE_URL` у `.env`**:
  ```env
  DATABASE_URL=sqlite+aiosqlite:///transport_bot.db
  ```

### 1.2 Налаштування systemd та SELinux
* **Директорія розгортання**: `/opt/transport_bot` (замість `/home/opc` через обмеження доступу).
* **Конфігурація служби systemd** (`/etc/systemd/system/transport-bot.service`):
  ```ini
  [Unit]
  Description=Transport Bot Service
  After=network.target

  [Service]
  Type=simple
  User=opc
  WorkingDirectory=/opt/transport_bot
  ExecStart=/opt/transport_bot/venv/bin/python main.py
  Restart=always
  RestartSec=5
  EnvironmentFile=/opt/transport_bot/.env

  [Install]
  WantedBy=multi-user.target
  ```
* **SELinux**:
  * Для уникнення помилки запуску `203/EXEC` та блокування доступу до файлів конфігурації, системні дописи було адаптовано, а також тимчасово вимкнено або пом'якшено примусове блокування SELinux (`setenforce 0` / permissive mode), якщо це викликало проблеми з доступом служби.

---

## 2. Логіка реєстрації у Музеї та синхронізація

### 2.1 Локальне сховище замість прямого запису в Google Sheets
* **Проблема**: Пряма робота з API Google Sheets під час взаємодії користувача з ботом створювала мережеві затримки та тайм-аути, через що користувачі не могли завершити бронювання, а бот підвисав.
* **Рішення**:
  * Дані про нове бронювання миттєво зберігаються у локальну таблицю SQLite `museum_bookings`.
  * Бот негайно підтверджує успішну реєстрацію користувачу.
  * Відразу після цього у фоні запускається асинхронна задача `_sync_to_sheets_task(booking_id)`, яка додає запис у Google Sheets (таблиця `MuseumBookings`).
  * Якщо фонова синхронізація з якихось причин не вдалася, статус запису в БД залишається `"new"`, і його можна синхронізувати пізніше за допомогою методу `sync_unsynced_bookings()`.

### 2.2 Перегляд списку зареєстрованих для адміністратора
* **Проблема**: Кнопка «Перелік зареєстрованих» в адмін-панелі раніше зчитувала всі рядки безпосередньо з Google Sheets, що працювало повільно.
* **Рішення**:
  * У `services/museum_service.py` метод `get_last_bookings()` переписано на зчитування останніх 50 записів із локальної SQLite бази.
  * Це забезпечує миттєве відкриття списку для адміністраторів музею без затримок.

### 2.3 Форматування часу: Київська часова зона
* **Проблема**: База даних автоматично проставляє час створення запису через `func.now()`, що використовує системний час (UTC). При завантаженні у Google Sheets або виводі в адмінку час відображався у форматі UTC.
* **Рішення**:
  * У `services/museum_service.py` реалізовано конвертацію в часовий пояс Києва:
    ```python
    def _to_kyiv_time(self, dt_value):
        if not dt_value: return None
        from datetime import timezone
        from zoneinfo import ZoneInfo
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=timezone.utc)
        return dt_value.astimezone(ZoneInfo("Europe/Kyiv"))
    ```
  * Перед відправкою у Google Sheets та перед показом адміністратору час конвертується через `_to_kyiv_time` та форматується як `ДД.ММ.РРРР ГГ:ХХ`.

---

## 3. Концепція середовища розробки та тестування (Dev/Test Environment)

Для безпечного додавання нових функцій та їх тестування окремо від активних користувачів пропонується наступна схема ізоляції на тому ж сервері (1 GB Oracle VM):

### 3.1 Розділення Telegram-ботів
* **Production Bot**: Працює на основному токені (напр., `@OdesaTransportBot`).
* **Dev/Test Bot**: Створюється окремий бот через `@BotFather` (напр., `@OdesaTransportDevBot`) з унікальним токеном `TELEGRAM_BOT_TOKEN`. Всі нові фічі тестуються виключно через нього.

### 3.2 Гілки у Git (Git Flow)
* `main` — стабільна продакшн-версія. Будь-які зміни сюди потрапляють тільки після успішного тестування.
* `dev` — гілка розробки. Сюди зливаються нові функції для тестування на сервері.

### 3.3 Ізоляція файлової системи та конфігурації
На сервері створюється паралельна директорія для dev-версії:
* Продакшн: `/opt/transport_bot`
* Dev: `/opt/transport_bot_dev`

Кожна директорія має свій незалежний файл `.env`:
* **У продакшн `.env`**:
  * Робочий токен бота.
  * Основна БД: `DATABASE_URL=sqlite+aiosqlite:///transport_bot.db`.
  * Основний Google Sheets ID.
  * `DEBUG=False`.
* **У dev `.env`**:
  * Тестовий токен бота.
  * Тестова БД: `DATABASE_URL=sqlite+aiosqlite:///transport_bot_dev.db`.
  * Тестова Google Sheets таблиця (копія основної) — для перевірки синхронізації без забруднення реальних звітів.
  * `DEBUG=True` (для детального виведення помилок в консоль).

### 3.4 Окрема служба systemd
Для Dev-бота створюється окремий системний сервіс `/etc/systemd/system/transport-bot-dev.service`:
```ini
[Unit]
Description=Transport Bot - Development Service
After=network.target

[Service]
Type=simple
User=opc
WorkingDirectory=/opt/transport_bot_dev
ExecStart=/opt/transport_bot_dev/venv/bin/python main.py
Restart=always
RestartSec=5
EnvironmentFile=/opt/transport_bot_dev/.env

[Install]
WantedBy=multi-user.target
```

### 3.5 Скрипт автоматичного деплою на Dev
Для швидкого оновлення dev-версії створюється скрипт `/opt/transport_bot_dev/deploy_dev.sh`:
```bash
#!/bin/bash
cd /opt/transport_bot_dev
git checkout dev
git pull origin dev
./venv/bin/pip install -r requirements.txt
sudo systemctl restart transport-bot-dev
echo "🚀 Dev-версія оновлена та перезапущена!"
```


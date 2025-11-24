# Використовуємо легку версію Python
FROM python:3.11-slim

# Встановлюємо робочу директорію
WORKDIR /app

# Встановлюємо системні залежності (потрібні для деяких Python бібліотек та Postgres)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо requirements.txt і встановлюємо залежності
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо весь код проєкту
COPY . .

# Команда запуску (замініть main.py на ваш файл запуску, якщо він інший)
CMD ["python", "main.py"]
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os
from config.settings import (
    SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_TARGET_EMAIL
)
from utils.logger import logger


def send_feedback_email(pdf_path: str, ticket_id: str, category: str) -> bool:
    """
    Надсилає лист із прикріпленим файлом PDF на пошту секретаря.
    Працює синхронно, але запускається в пулі потоків.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.error("❌ Налаштування SMTP (SMTP_USER/SMTP_PASSWORD) не задані в .env!")
        return False

    if not os.path.exists(pdf_path):
        logger.error(f"❌ Файл PDF не знайдено за шляхом: {pdf_path}")
        return False

    try:
        # Створюємо повідомлення
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = SMTP_TARGET_EMAIL

        category_ua = {
            "complaint": "Скарга",
            "thanks": "Подяка",
            "suggestion": "Пропозиція",
            "Скарги": "Скарга",
            "Подяки": "Подяка",
            "Пропозиції": "Пропозиція"
        }.get(category, category)

        msg['Subject'] = f"Звернення громадян: {category_ua}"

        body = (
            f"Доброго дня!\n\n"
            f"Через Telegram-бот було отримано нове звернення громадян.\n"
            f"Категорія: {category_ua}\n\n"
            f"Повні дані знаходяться у вкладеному файлі PDF.\n\n"
            f"З повагою,\n"
            f"Telegram-бот КП ОМЕТ"
        )
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # Прикріплюємо PDF
        with open(pdf_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{os.path.basename(pdf_path)}"'
            )
            msg.attach(part)

        # З'єднання по SMTP
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10)
            server.starttls()

        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [SMTP_TARGET_EMAIL], msg.as_string())
        server.quit()

        logger.info(f"📧 Лист для {ticket_id} успішно надіслано на {SMTP_TARGET_EMAIL}")
        return True
    except Exception as e:
        logger.error(f"❌ Помилка відправки листа для {ticket_id}: {e}")
        return False

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = 447322502  # Ваш ID
CHANNEL_ID = os.environ.get('CHANNEL_ID', '@kalerichan')
DIAGNOSTIC_LINK = os.environ.get('DIAGNOSTIC_LINK', 'https://t.me/valeriasereda')

# YooKassa настройки (опционально)
YOOKASSA_SHOP_ID = os.environ.get('YOOKASSA_SHOP_ID', '')
YOOKASSA_SECRET_KEY = os.environ.get('YOOKASSA_SECRET_KEY', '')
YOOKASSA_TEST_MODE = os.environ.get('YOOKASSA_TEST_MODE', 'True').lower() == 'true'

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

# Проверка YooKassa только если переменные заданы
# Если вы не используете оплату — просто игнорируем

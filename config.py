import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 447322502

CHANNEL_ID = os.environ.get("CHANNEL_ID", "@kalerichan")
DIAGNOSTIC_LINK = os.environ.get(
    "DIAGNOSTIC_LINK",
    "https://t.me/valeriasereda",
)

YOOKASSA_SHOP_ID = os.environ.get("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.environ.get("YOOKASSA_SECRET_KEY", "")
YOOKASSA_TEST_MODE = (
    os.environ.get("YOOKASSA_TEST_MODE", "True").lower() == "true"
)

# ВАЖНО:
# Все 09:00 и 19:00 считаются по этому часовому поясу.
# При необходимости поменяй на Europe/Amsterdam, Europe/Kyiv и т.д.
BOT_TIMEZONE = os.environ.get("BOT_TIMEZONE", "Europe/Moscow")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

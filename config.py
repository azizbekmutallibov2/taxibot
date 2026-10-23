import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
API_ID      = int(os.getenv("API_ID", "0"))
API_HASH    = os.getenv("API_HASH", "")

# Ruxsat etilgan 3 ta foydalanuvchi Telegram ID lari
ALLOWED_USERS: list[int] = [
    int(x.strip()) for x in os.getenv("ALLOWED_USERS", "").split(",")
    if x.strip().isdigit()
]

SESSION_DIR = os.getenv("SESSION_DIR", "./sessions")
MAX_ACCOUNTS_PER_USER = 20

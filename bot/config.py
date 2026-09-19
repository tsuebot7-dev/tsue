"""
Botning umumiy sozlamalari. Barcha maxfiy qiymatlar (.env) fayldan yoki
muhit o'zgaruvchilaridan (Railway -> Variables) olinadi.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Asosiy sozlamalar ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")

# --- Fayl yo'llari ---
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

GURUHLAR_FILE = DATA_DIR / "guruhlar.json"
USTOZLAR_FILE = DATA_DIR / "ustozlar.json"
XONALAR_FILE = DATA_DIR / "xonalar.json"
BOSHXONALAR_FILE = DATA_DIR / "boshxonalar.json"
HIERARCHY_CONFIG_FILE = DATA_DIR / "hierarchy_config.json"
DISPLAY_NAMES_FILE = DATA_DIR / "display_names.json"
DB_FILE = DATA_DIR / "bot_data.db"

# Agar DATABASE_URL berilgan bo'lsa (Railway PostgreSQL qo'shganda
# avtomatik beriladi), shundan foydalaniladi. Aks holda lokal SQLite
# fayliga (DB_FILE) yoziladi - shu bilan kod o'zgarmasdan ham
# Railway'da, ham kompyuterda ishlayveradi.
DATABASE_URL = os.getenv("DATABASE_URL", "")

# --- Xonalarni avtomatik skanerlash sozlamalari ---
ROOM_SCAN_START = int(os.getenv("ROOM_SCAN_START", 1))
ROOM_SCAN_END = int(os.getenv("ROOM_SCAN_END", 640))
ROOM_SCAN_INTERVAL_DAYS = int(os.getenv("ROOM_SCAN_INTERVAL_DAYS", 7))

# --- O'qituvchilarni avtomatik skanerlash sozlamalari ---
TEACHER_SCAN_START = int(os.getenv("TEACHER_SCAN_START", 1))
TEACHER_SCAN_END = int(os.getenv("TEACHER_SCAN_END", 3100))
TEACHER_SCAN_INTERVAL_DAYS = int(os.getenv("TEACHER_SCAN_INTERVAL_DAYS", 7))
TEACHER_URL_PARAM = os.getenv("TEACHER_URL_PARAM", "teacher")

# --- Guruh havolalarini sinxronlash (faqat mavjud nomlarga mos URL
# yangilash, strukturani o'zgartirmasdan) ---
GROUP_URL_SYNC_START = int(os.getenv("GROUP_URL_SYNC_START", 1))
GROUP_URL_SYNC_END = int(os.getenv("GROUP_URL_SYNC_END", 2500))
GROUP_URL_SYNC_INTERVAL_DAYS = int(os.getenv("GROUP_URL_SYNC_INTERVAL_DAYS", 7))

SCREENSHOT_DIR = Path(os.getenv("SCREENSHOT_DIR", BASE_DIR / "tmp_screenshots"))
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# --- Web-admin porti (Railway avtomatik $PORT beradi) ---
ADMIN_PORT = int(os.getenv("PORT", os.getenv("ADMIN_PORT", 8000)))

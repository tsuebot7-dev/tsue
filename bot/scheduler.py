"""
Har daqiqada bir marta ishga tushib, group_subscriptions jadvalidagi
har bir faol obunani tekshiradi: agar bugungi kun va joriy soat mos
kelsa (va bugun hali yuborilmagan bo'lsa), o'sha guruhga jadval
skrinshotini yuboradi.

Vaqt mintaqasi: Toshkent (UTC+5, yoz vaqtiga o'tish yo'q), shuning
uchun serverning o'zi qaysi mintaqada ishlashidan qat'iy nazar, doim
+5 soat qo'shib hisoblanadi.
"""

import asyncio
import json
import logging
import datetime

from aiogram.types import FSInputFile

from . import db
from .bot_instance import get_bot
from .screenshot import take_timetable_screenshot

logger = logging.getLogger(__name__)

TASHKENT_OFFSET = datetime.timedelta(hours=5)
CHECK_INTERVAL_SECONDS = 30

WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _tashkent_now() -> datetime.datetime:
    return datetime.datetime.utcnow() + TASHKENT_OFFSET


async def _send_to_group(sub: dict):
    bot = get_bot()
    try:
        png_path = await take_timetable_screenshot(sub["url"])
        photo = FSInputFile(png_path)
        await bot.send_photo(
            sub["chat_id"],
            photo=photo,
            caption=f"📅 {sub['name']} — bugungi/joriy dars jadvali",
        )
        png_path.unlink(missing_ok=True)
        logger.info("Guruhga jadval yuborildi: chat_id=%s, %s", sub["chat_id"], sub["name"])
    except Exception:
        logger.exception("Guruhga jadval yuborishda xatolik: chat_id=%s", sub["chat_id"])


async def _check_and_send_once():
    now = _tashkent_now()
    today_code = WEEKDAY_CODES[now.weekday()]
    today_str = now.date().isoformat()
    current_hhmm = now.strftime("%H:%M")

    subs = await db.get_group_subscriptions(active_only=True)
    for sub in subs:
        if sub.get("last_sent_date") == today_str:
            continue  # bugun allaqachon yuborilgan

        try:
            days = json.loads(sub.get("days") or "[]")
        except json.JSONDecodeError:
            days = []

        if today_code not in days:
            continue
        if sub.get("post_time") != current_hhmm:
            continue

        await _send_to_group(sub)
        await db.mark_group_sent_today(sub["chat_id"], today_str)


async def run_scheduler():
    logger.info("Guruhlarga avtomatik jadval yuborish rejalashtiruvchisi ishga tushdi.")
    while True:
        try:
            await _check_and_send_once()
        except Exception:
            logger.exception("Scheduler tsiklida xatolik yuz berdi.")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

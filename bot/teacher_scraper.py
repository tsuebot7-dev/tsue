"""
tsue.edupage.org saytidan barcha o'qituvchilarni (teacher=*1..3100)
skanerlab, har birining ismini (SVG sarlavhasidan) o'qib, natijani
data/ustozlar.json fayliga {"Ism Familiya": "url", ...} ko'rinishida
yozadi.

MUHIM: teacher=*ID URL formati taxmin qilingan (talaba uchun
class=*ID, xona uchun classroom=*ID ishlatilgani kabi, o'qituvchi
uchun eng ko'p tarqalgan konvensiya). Agar bu noto'g'ri bo'lsa,
--debug rejimida (yoki config.py dagi TEACHER_URL_PARAM orqali) tez
tekshirib, to'g'irlash mumkin.
"""

import asyncio
import json
import logging
import re
import time

from . import config, data_loader, db, screenshot
from .room_scraper import fetch_svg_from_url, _ROOM_NAME_RE

logger = logging.getLogger(__name__)


def build_teacher_url(teacher_id: int) -> str:
    return f"https://tsue.edupage.org/timetable/view.php?num=94&{config.TEACHER_URL_PARAM}=*{teacher_id}"


def extract_teacher_name(svg_text: str) -> str:
    """SVG'ning katta sarlavha matnidan o'qituvchi ismini oladi.
    Agar sahifa bo'sh/yaroqsiz bo'lsa, bo'sh qator qaytaradi."""
    if not svg_text:
        return ""
    m = _ROOM_NAME_RE.search(svg_text)
    if not m:
        return ""
    name = m.group(1).strip()
    # Yaroqsiz/bo'sh sahifalarda ko'pincha hech narsa yoki juda qisqa
    # matn chiqadi - haqiqiy ism odatda kamida 2 ta harfdan iborat
    # bo'ladi va bo'sh joy (familiya+ism) bo'ladi.
    if len(name) < 3:
        return ""
    return name


def _save_progress(results: dict):
    with open(config.USTOZLAR_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


async def debug_one_teacher(teacher_id: int) -> dict:
    """Bitta ID'ni tekshirib, natijani qaytaradi - TEACHER_URL_PARAM
    to'g'ri ekanini tez tasdiqlash uchun foydali."""
    url = build_teacher_url(teacher_id)
    svg_text = await fetch_svg_from_url(url)
    name = extract_teacher_name(svg_text)
    return {"teacher_id": teacher_id, "url": url, "name": name, "svg_length": len(svg_text or "")}


STALE_AFTER_SECONDS = 20 * 60
REQUEST_DELAY_SECONDS = 2.5
MAX_CONSECUTIVE_ERRORS = 8
COOLDOWN_SECONDS = 30 * 60


async def is_scan_stuck() -> bool:
    status = await db.get_setting("teacher_scan_status")
    if status != "running":
        return False
    heartbeat = await db.get_setting("teacher_scan_heartbeat")
    if not heartbeat:
        return True
    return (time.time() - float(heartbeat)) > STALE_AFTER_SECONDS


async def scan_all_teachers(start: int = None, end: int = None, save_every: int = 25):
    start = start or config.TEACHER_SCAN_START
    end = end or config.TEACHER_SCAN_END

    await db.set_setting("teacher_scan_status", "running")
    await db.set_setting("teacher_scan_started_at", str(int(time.time())))
    await db.set_setting("teacher_scan_heartbeat", str(int(time.time())))
    await db.set_setting("teacher_scan_progress", "0")
    await db.set_setting("teacher_scan_total", str(end - start + 1))

    try:
        with open(config.USTOZLAR_FILE, "r", encoding="utf-8") as f:
            results = json.load(f)
            if not isinstance(results, dict):
                results = {}
    except (FileNotFoundError, json.JSONDecodeError):
        results = {}

    processed_since_save = 0
    done_count = 0
    found_count = 0
    consecutive_errors = 0

    for teacher_id in range(start, end + 1):
        try:
            url = build_teacher_url(teacher_id)
            svg_text = await fetch_svg_from_url(url)
            name = extract_teacher_name(svg_text)
            if name:
                results[name] = url
                found_count += 1
            consecutive_errors = 0
        except Exception as e:
            logger.warning("O'qituvchi %s skanerlashda xatolik: %s", teacher_id, e)
            await db.log_error("teacher_scan", f"ID {teacher_id}: {e}")
            consecutive_errors += 1

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.warning(
                    "%s marta ketma-ket xato - sayt bloklagan bo'lishi mumkin. "
                    "%s daqiqaga to'xtatilmoqda.",
                    consecutive_errors, COOLDOWN_SECONDS // 60,
                )
                await db.set_setting("teacher_scan_status", "cooldown")
                await db.log_error(
                    "teacher_scan_cooldown",
                    f"{consecutive_errors} ketma-ket xatodan keyin {COOLDOWN_SECONDS // 60} "
                    f"daqiqaga to'xtatildi (ID {teacher_id} da).",
                )
                _save_progress(results)
                await asyncio.sleep(COOLDOWN_SECONDS)
                await db.set_setting("teacher_scan_status", "running")
                await db.set_setting("teacher_scan_heartbeat", str(int(time.time())))
                consecutive_errors = 0

        done_count += 1
        processed_since_save += 1
        await db.set_setting("teacher_scan_progress", str(done_count))
        await db.set_setting("teacher_scan_found", str(found_count))
        await db.set_setting("teacher_scan_heartbeat", str(int(time.time())))

        if processed_since_save >= save_every:
            _save_progress(results)
            processed_since_save = 0

        await asyncio.sleep(REQUEST_DELAY_SECONDS)

    _save_progress(results)
    data_loader.store.reload()

    await db.set_setting("teacher_scan_status", "done")
    await db.set_setting("teacher_scan_finished_at", str(int(time.time())))
    logger.info("O'qituvchilarni skanerlash tugadi: %s ta topildi (%s ID tekshirildi).", found_count, done_count)


async def weekly_teacher_scan_loop():
    logger.info("Haftalik o'qituvchilar skanerlash nazoratchisi ishga tushdi.")
    while True:
        try:
            enabled = (await db.get_setting("scanning_enabled", "1")) == "1"
            if not enabled:
                pass
            elif await is_scan_stuck():
                logger.warning("O'qituvchilar skanerlashi to'xtab qolgan edi - qaytadan boshlanmoqda.")
                await scan_all_teachers()
            else:
                last_finished = await db.get_setting("teacher_scan_finished_at")
                status = await db.get_setting("teacher_scan_status")
                now = time.time()

                should_run = False
                if not last_finished:
                    should_run = True
                else:
                    elapsed_days = (now - float(last_finished)) / 86400
                    if elapsed_days >= config.TEACHER_SCAN_INTERVAL_DAYS:
                        should_run = True

                if should_run and status not in ("running", "cooldown"):
                    logger.info("O'qituvchilarni avtomatik (haftalik) skanerlash boshlandi.")
                    await scan_all_teachers()
        except Exception:
            logger.exception("Haftalik o'qituvchi skanerlash nazoratchisida xatolik.")

        await asyncio.sleep(5 * 60)

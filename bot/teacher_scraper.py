"""
ustozlar.json faylining STRUKTURASI (qanday ismlar bor, qaysi
tartibda) foydalanuvchi tomonidan qo'lda boshqariladi. Bu modul faqat
mavjud ismlarning URL manzilini TSUE saytida qayta tekshirib, agar
ID almashgan bo'lsa, o'sha bitta qiymatni yangilaydi - xuddi
group_url_scraper.py guruhlar.json uchun qilgani kabi.

Saytda topilgan, lekin faylda yo'q ismlar FAYLGA AVTOMATIK
QO'SHILMAYDI - ular "discovered_items" bazasiga yoziladi va admin
panelning "🆕 Yangi topilganlar" sahifasida havolasi bilan ko'rinadi,
xohlasa qo'lda ustozlar.json ga qo'shadi.

MUHIM: teacher=*ID URL formati taxmin qilingan (talaba uchun
class=*ID, xona uchun classroom=*ID ishlatilgani kabi, o'qituvchi
uchun eng ko'p tarqalgan konvensiya). Agar bu noto'g'ri bo'lsa,
botga /debugteacher <ID> yuborib tekshirish mumkin.
"""

import asyncio
import json
import logging
import time

from . import config, data_loader, db
from .room_scraper import _ROOM_NAME_RE, fetch_svg_from_url

logger = logging.getLogger(__name__)

STALE_AFTER_SECONDS = 20 * 60
REQUEST_DELAY_SECONDS = 5.0  # imkon qadar sekinroq - saytni zoriqtirmaslik ustuvor
MAX_CONSECUTIVE_ERRORS = 8
COOLDOWN_SECONDS = 45 * 60


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
    if len(name) < 3:
        return ""
    return name


async def debug_one_teacher(teacher_id: int) -> dict:
    """Bitta ID'ni tekshirib, natijani qaytaradi - TEACHER_URL_PARAM
    to'g'ri ekanini tez tasdiqlash uchun foydali."""
    url = build_teacher_url(teacher_id)
    svg_text = await fetch_svg_from_url(url)
    name = extract_teacher_name(svg_text)
    return {"teacher_id": teacher_id, "url": url, "name": name, "svg_length": len(svg_text or "")}


async def is_scan_stuck() -> bool:
    status = await db.get_setting("teacher_scan_status")
    if status != "running":
        return False
    heartbeat = await db.get_setting("teacher_scan_heartbeat")
    if not heartbeat:
        return True
    return (time.time() - float(heartbeat)) > STALE_AFTER_SECONDS


async def sync_teacher_urls(start: int = None, end: int = None):
    """1-BOSQICH: barcha ID'larni skanerlab {ism: togri_url} lug'atini
    tuzadi. 2-BOSQICH: mavjud ustozlar.json faylidagi faqat mos
    keladigan ismlarning URL'ini yangilaydi (struktura saqlanadi);
    yangi topilgan ismlar FAYLGA qo'shilmasdan, discovered_items
    bazasiga yoziladi."""
    start = start or config.TEACHER_SCAN_START
    end = end or config.TEACHER_SCAN_END

    await db.set_setting("teacher_scan_status", "running")
    await db.set_setting("teacher_scan_started_at", str(int(time.time())))
    await db.set_setting("teacher_scan_heartbeat", str(int(time.time())))
    await db.set_setting("teacher_scan_progress", "0")
    await db.set_setting("teacher_scan_total", str(end - start + 1))

    scanned_map: dict[str, str] = {}
    consecutive_errors = 0
    done_count = 0
    found_count = 0

    for teacher_id in range(start, end + 1):
        try:
            url = build_teacher_url(teacher_id)
            svg_text = await fetch_svg_from_url(url)
            name = extract_teacher_name(svg_text)
            if name:
                scanned_map[name] = url
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
                await asyncio.sleep(COOLDOWN_SECONDS)
                await db.set_setting("teacher_scan_status", "running")
                await db.set_setting("teacher_scan_heartbeat", str(int(time.time())))
                consecutive_errors = 0

        done_count += 1
        await db.set_setting("teacher_scan_progress", str(done_count))
        await db.set_setting("teacher_scan_found", str(found_count))
        await db.set_setting("teacher_scan_heartbeat", str(int(time.time())))
        await asyncio.sleep(REQUEST_DELAY_SECONDS)

    # --- 2-BOSQICH: mavjud faylni ochib, faqat mos ismlarning URL'ini yangilaymiz ---
    try:
        with open(config.USTOZLAR_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
            if not isinstance(existing, dict):
                existing = {}
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {}

    updated_count = 0
    unchanged_count = 0

    for key in list(existing.keys()):
        if key in data_loader.SKIP_KEYS:
            continue
        current_value = existing[key]
        if not isinstance(current_value, str):
            continue
        fresh_url = scanned_map.get(key)
        if fresh_url and fresh_url != current_value:
            existing[key] = fresh_url
            updated_count += 1
        elif fresh_url:
            unchanged_count += 1

    existing_names = {k for k in existing.keys() if k not in data_loader.SKIP_KEYS}
    new_found = sorted(n for n in scanned_map.keys() if n not in existing_names)

    with open(config.USTOZLAR_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    data_loader.store.reload()

    await db.set_setting("teacher_scan_status", "done")
    await db.set_setting("teacher_scan_finished_at", str(int(time.time())))
    await db.set_setting("teacher_scan_updated", str(updated_count))
    await db.set_setting("teacher_scan_unchanged", str(unchanged_count))
    await db.set_setting("teacher_scan_new_found_count", str(len(new_found)))

    for name in new_found:
        await db.add_discovered_item("ustoz", name, scanned_map[name])

    logger.info(
        "O'qituvchilar sinxronlashi tugadi: %s ta yangilandi, %s ta o'zgarmadi, "
        "%s ta yangi topildi (jami %s ID tekshirildi).",
        updated_count, unchanged_count, len(new_found), done_count,
    )


async def weekly_teacher_scan_loop():
    logger.info("Haftalik o'qituvchilar sinxronlash nazoratchisi ishga tushdi.")
    while True:
        try:
            enabled = (await db.get_setting("scanning_enabled", "1")) == "1"
            if not enabled:
                pass
            elif await is_scan_stuck():
                logger.warning("O'qituvchilar sinxronlashi to'xtab qolgan edi - qaytadan boshlanmoqda.")
                await sync_teacher_urls()
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
                    logger.info("O'qituvchilarni avtomatik (haftalik) sinxronlash boshlandi.")
                    await sync_teacher_urls()
        except Exception:
            logger.exception("Haftalik o'qituvchi sinxronlash nazoratchisida xatolik.")

        await asyncio.sleep(5 * 60)

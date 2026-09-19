"""
guruhlar.json faylidagi GURUH NOMLARI va ularning FAKULTET/KURS
ichidagi TARTIBI o'zgarmasdan qoladi (bu qo'lda tahrirlanadi) - bu
modul faqat har bir mavjud guruh nomining URL manzilini TSUE saytida
qayta tekshirib, agar ID almashgan bo'lsa (masalan "MO-900/26" avval
class=*3 bo'lgan bo'lsa, endi class=*7 bo'lib qolgan bo'lsa),
faylning O'SHA JOYIDAGI qiymatini yangi to'g'ri havola bilan
almashtiradi.

Ishlash tartibi:
1. class=*START dan class=*END gacha barcha ID'larni skanerlab,
   har birining sahifasida ko'rsatilgan GURUH NOMINI o'qib oladi
   (masalan "MO-900/26"), va {nom: hozirgi_togri_url} lug'atini
   tuzadi.
2. Mavjud guruhlar.json faylini OCHADI (qayta qurmaydi!), va har bir
   LEAF (guruh nomi) kalit uchun: agar shu nom skanerlashda topilgan
   bo'lsa va uning URL'i faylda yozilgan bilan FARQ QILSA, faqat O'SHA
   BITTA qiymatni yangilaydi - fakultet/kurs sarlavhalari va
   guruhlarning tartibi/joylashuvi BUTUNLAY O'ZGARMAYDI.
3. Skanerlashda topilgan, lekin faylda umuman yo'q nomlar FAYLGA
   QO'SHILMAYDI (chunki foydalanuvchi strukturani qo'lda boshqaradi) -
   ular faqat xatolar jurnaliga "yangi topilgan guruhlar" sifatida
   yoziladi, admin xohlasa qo'lda qo'shishi mumkin.
"""

import asyncio
import json
import logging
import re
import time

from . import config, data_loader, db
from .room_scraper import _ROOM_NAME_RE, fetch_svg_from_url

logger = logging.getLogger(__name__)

_FAKULTET_RE = re.compile(r"^[A-Z]+$")
_KURS_RE = re.compile(r"^\dKURS$")

STALE_AFTER_SECONDS = 20 * 60
REQUEST_DELAY_SECONDS = 5.0  # imkon qadar sekinroq - saytni zoriqtirmaslik ustuvor
MAX_CONSECUTIVE_ERRORS = 8
COOLDOWN_SECONDS = 45 * 60


def build_group_url(group_id: int) -> str:
    return f"https://tsue.edupage.org/timetable/view.php?num=94&class=*{group_id}"


def extract_group_name(svg_text: str) -> str:
    if not svg_text:
        return ""
    m = _ROOM_NAME_RE.search(svg_text)
    if not m:
        return ""
    name = m.group(1).strip()
    if len(name) < 2:
        return ""
    return name


def _is_header_key(key: str) -> bool:
    """Fakultet ('MENEJMENTFAKULTETI') yoki kurs ('1KURS') sarlavha
    kaliti ekanini aniqlaydi - bunday kalitlar hech qachon
    tekshirilmaydi/yangilanmaydi, faqat haqiqiy guruh nomlari
    (masalan 'MO-900/26') tekshiriladi."""
    return bool(_FAKULTET_RE.match(key) or _KURS_RE.match(key))


async def is_scan_stuck() -> bool:
    status = await db.get_setting("group_url_scan_status")
    if status != "running":
        return False
    heartbeat = await db.get_setting("group_url_scan_heartbeat")
    if not heartbeat:
        return True
    return (time.time() - float(heartbeat)) > STALE_AFTER_SECONDS


async def sync_group_urls(start: int = None, end: int = None):
    """1-BOSQICH: barcha ID'larni skanerlab, {guruh_nomi: togri_url}
    lug'atini tuzadi. 2-BOSQICH: mavjud guruhlar.json faylidagi faqat
    mos keladigan nomlarning URL'ini yangilaydi, struktura saqlanadi."""
    start = start or config.GROUP_URL_SYNC_START
    end = end or config.GROUP_URL_SYNC_END

    await db.set_setting("group_url_scan_status", "running")
    await db.set_setting("group_url_scan_started_at", str(int(time.time())))
    await db.set_setting("group_url_scan_heartbeat", str(int(time.time())))
    await db.set_setting("group_url_scan_progress", "0")
    await db.set_setting("group_url_scan_total", str(end - start + 1))

    scanned_map: dict[str, str] = {}
    consecutive_errors = 0
    done_count = 0

    for group_id in range(start, end + 1):
        try:
            url = build_group_url(group_id)
            svg_text = await fetch_svg_from_url(url)
            name = extract_group_name(svg_text)
            if name:
                scanned_map[name] = url
            consecutive_errors = 0
        except Exception as e:
            logger.warning("Guruh ID %s tekshirishda xatolik: %s", group_id, e)
            await db.log_error("group_url_scan", f"ID {group_id}: {e}")
            consecutive_errors += 1

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.warning(
                    "%s marta ketma-ket xato - sayt bloklagan bo'lishi mumkin. "
                    "%s daqiqaga to'xtatilmoqda.",
                    consecutive_errors, COOLDOWN_SECONDS // 60,
                )
                await db.set_setting("group_url_scan_status", "cooldown")
                await db.log_error(
                    "group_url_scan_cooldown",
                    f"{consecutive_errors} ketma-ket xatodan keyin {COOLDOWN_SECONDS // 60} "
                    f"daqiqaga to'xtatildi (ID {group_id} da).",
                )
                await asyncio.sleep(COOLDOWN_SECONDS)
                await db.set_setting("group_url_scan_status", "running")
                await db.set_setting("group_url_scan_heartbeat", str(int(time.time())))
                consecutive_errors = 0

        done_count += 1
        await db.set_setting("group_url_scan_progress", str(done_count))
        await db.set_setting("group_url_scan_heartbeat", str(int(time.time())))
        await asyncio.sleep(REQUEST_DELAY_SECONDS)

    # --- 2-BOSQICH: mavjud faylni ochib, faqat mos nomlarning URL'ini yangilaymiz ---
    try:
        with open(config.GURUHLAR_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {}

    updated_count = 0
    unchanged_count = 0

    for key in list(existing.keys()):
        if key in data_loader.SKIP_KEYS or _is_header_key(key):
            continue  # sarlavha kaliti - tegilmaymiz
        current_value = existing[key]
        if not isinstance(current_value, str):
            continue
        fresh_url = scanned_map.get(key)
        if fresh_url and fresh_url != current_value:
            existing[key] = fresh_url
            updated_count += 1
        elif fresh_url:
            unchanged_count += 1

    # Skanerlashda topilgan, lekin faylda umuman yo'q nomlar - FAYLGA
    # QO'SHILMAYDI, faqat ma'lumot uchun jurnalga yoziladi.
    existing_names = {k for k in existing.keys() if not _is_header_key(k) and k not in data_loader.SKIP_KEYS}
    new_found = sorted(n for n in scanned_map.keys() if n not in existing_names)

    with open(config.GURUHLAR_FILE, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    data_loader.store.reload()

    await db.set_setting("group_url_scan_status", "done")
    await db.set_setting("group_url_scan_finished_at", str(int(time.time())))
    await db.set_setting("group_url_scan_updated", str(updated_count))
    await db.set_setting("group_url_scan_unchanged", str(unchanged_count))
    await db.set_setting("group_url_scan_new_found_count", str(len(new_found)))

    if new_found:
        for name in new_found:
            await db.add_discovered_item("guruh", name, scanned_map[name])

    logger.info(
        "Guruh havolalarini sinxronlash tugadi: %s ta yangilandi, %s ta "
        "o'zgarmadi, %s ta yangi (faylga qo'shilmagan) topildi.",
        updated_count, unchanged_count, len(new_found),
    )


async def weekly_group_url_sync_loop():
    logger.info("Haftalik guruh havolalarini sinxronlash nazoratchisi ishga tushdi.")
    while True:
        try:
            enabled = (await db.get_setting("scanning_enabled", "1")) == "1"
            if not enabled:
                pass
            elif await is_scan_stuck():
                logger.warning("Guruh havolalari sinxronlashi to'xtab qolgan edi - qaytadan boshlanmoqda.")
                await sync_group_urls()
            else:
                last_finished = await db.get_setting("group_url_scan_finished_at")
                status = await db.get_setting("group_url_scan_status")
                now = time.time()

                should_run = False
                if not last_finished:
                    should_run = True
                else:
                    elapsed_days = (now - float(last_finished)) / 86400
                    if elapsed_days >= config.GROUP_URL_SYNC_INTERVAL_DAYS:
                        should_run = True

                if should_run and status not in ("running", "cooldown"):
                    logger.info("Guruh havolalarini avtomatik (haftalik) sinxronlash boshlandi.")
                    await sync_group_urls()
        except Exception:
            logger.exception("Haftalik guruh havolalari sinxronlash nazoratchisida xatolik.")

        await asyncio.sleep(5 * 60)

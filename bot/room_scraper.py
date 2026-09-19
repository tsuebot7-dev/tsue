"""
tsue.edupage.org saytidan barcha xonalarning (classroom=*1..640) dars
jadvalini SVG orqali o'qib, har bir xona uchun band/bo'sh vaqtlarni
aniqlaydi va natijani data/boshxonalar.json fayliga yozadi.

Bu modul avvalgi (qo'lda ishga tushiriladigan) room_schedule_scraper_svg.py
skriptining bot ichiga integratsiya qilingan, asinxron versiyasi -
bot bilan bitta jarayonda, umumiy Playwright brauzeridan foydalanib
ishlaydi (yangi brauzer ochilmaydi).
"""

import asyncio
import json
import logging
import re
import time

from . import config, data_loader, db, screenshot

logger = logging.getLogger(__name__)

BASE_URL = "https://tsue.edupage.org/timetable/view.php"
NUM = 94

PERIOD_TIMES = {
    1: "8:00-9:20", 2: "9:30-10:50", 3: "11:00-12:20", 4: "13:00-14:20",
    5: "14:30-15:50", 6: "16:00-17:20", 7: "17:30-18:50", 8: "19:00-20:20",
}
DAYS = ["Mn", "Tu", "Wed", "Thu", "Fri", "Sat"]

PERIOD_X_BOUNDS = [
    190.815, 530.713125, 870.6112499999999, 1210.509375,
    1550.4075, 1890.305625, 2230.20375, 2570.101875, 2910.0,
]
DAY_Y_BOUNDS = [
    414.05, 670.0416666666667, 926.0333333333333, 1182.025,
    1438.0166666666667, 1694.0083333333334, 1950.0,
]
TOL = 0.5

_BUSY_RECT_RE = re.compile(
    r'<rect\s+x="([\d.]+)"\s+y="([\d.]+)"\s+width="([\d.]+)"\s+height="([\d.]+)"'
    r'\s+fill="transparent"\s+stroke-width="0">'
    r'<title>(.*?)</title>\s*</rect>',
    re.DOTALL,
)
_ROOM_NAME_RE = re.compile(r'font-size="85"[^>]*>([^<]+)</text>')


def _find_index(value: float, bounds: list) -> int:
    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1]
        if lo - TOL <= value < hi - TOL:
            return i
    return -1


def build_url(room_id: int) -> str:
    return f"{BASE_URL}?num={NUM}&classroom=*{room_id}"


def parse_room_svg(svg_text: str) -> dict:
    if not svg_text:
        return {}
    busy = {}
    for m in _BUSY_RECT_RE.finditer(svg_text):
        x, y = float(m.group(1)), float(m.group(2))
        title = m.group(5).strip()
        period_idx = _find_index(x, PERIOD_X_BOUNDS)
        day_idx = _find_index(y, DAY_Y_BOUNDS)
        if period_idx == -1 or day_idx == -1:
            continue
        day = DAYS[day_idx]
        period = period_idx + 1
        info = " | ".join(line.strip() for line in title.splitlines() if line.strip())
        busy[(day, period)] = info
    return busy


def build_room_result(room_id: int, svg_text: str) -> dict:
    busy_map = parse_room_svg(svg_text)
    m = _ROOM_NAME_RE.search(svg_text)
    room_name = m.group(1) if m else ""

    busy_slots, free_slots = [], []
    for day in DAYS:
        for period, time_range in PERIOD_TIMES.items():
            entry = {"day": day, "period": period, "time": time_range}
            info = busy_map.get((day, period))
            if info:
                entry["info"] = info
                busy_slots.append(entry)
            else:
                free_slots.append(entry)

    return {
        "room_id": room_id,
        "room_name": room_name,
        "url": build_url(room_id),
        "busy_slots": busy_slots,
        "free_slots": free_slots,
    }


async def fetch_svg_from_url(url: str) -> str:
    """Berilgan istalgan TSUE timetable URL manzilidan (xona, guruh yoki
    o'qituvchi bo'lishi mumkin) renderlangan SVG jadval kodini oladi.
    room_scraper (xonalar) va group_watcher (guruh o'zgarishlarini
    kuzatish) ikkalasi ham shu umumiy funksiyadan foydalanadi."""
    if screenshot._browser is None:
        await screenshot.start_browser()

    page = await screenshot._browser.new_page(
        viewport={"width": 1200, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    try:
        await page.goto(url, wait_until="commit", timeout=20000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            await page.wait_for_selector("svg", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(500)

        svg = await page.evaluate(
            """() => {
                const el = document.querySelector('div.print-sheet svg')
                        || document.querySelector('svg');
                return el ? el.outerHTML : '';
            }"""
        )
        return svg
    finally:
        await page.close()


async def _fetch_room_svg(room_id: int) -> str:
    return await fetch_svg_from_url(build_url(room_id))


def _save_progress(results: dict):
    with open(config.BOSHXONALAR_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


STALE_AFTER_SECONDS = 20 * 60  # 20 daqiqa progress yangilanmasa - "tokhtab qolgan" deb hisoblanadi
REQUEST_DELAY_SECONDS = 2.5  # har so'rov orasida kutish - saytni "bombardimon" qilmaslik uchun
MAX_CONSECUTIVE_ERRORS = 8  # shuncha ketma-ket xatodan keyin, sayt bloklagan deb hisoblab, uzoq dam olamiz
COOLDOWN_SECONDS = 30 * 60  # bloklanish gumon qilinganda shuncha vaqt butunlay to'xtaymiz


async def is_scan_stuck() -> bool:
    """Agar holat 'running' bo'lsa-yu, lekin so'nggi 20 daqiqada hech
    qanday progress yangilanmagan bo'lsa (masalan Railway qayta deploy
    bo'lganda jarayon o'rtada uzilib qolgan bo'lsa), bu skanerlash
    'to'xtab qolgan' (stuck) deb hisoblanadi va qayta ishga
    tushirishga ruxsat beriladi."""
    status = await db.get_setting("room_scan_status")
    if status != "running":
        return False
    heartbeat = await db.get_setting("room_scan_heartbeat")
    if not heartbeat:
        return True  # heartbeat umuman yozilmagan - eski/uzilgan holat
    return (time.time() - float(heartbeat)) > STALE_AFTER_SECONDS


async def scan_all_rooms(start: int = None, end: int = None, save_every: int = 15):
    """Barcha xonalarni (start..end) ketma-ket skanerlaydi. Har
    'save_every' xonadan keyin oraliq natijani faylga yozadi, shunda
    jarayon uzilib qolsa ham hammasi qaytadan boshlanmaydi.

    MUHIM: so'rovlar orasida REQUEST_DELAY_SECONDS kutiladi (saytni
    "bombardimon" qilib, anti-bot bloklanishga sabab bo'lmaslik
    uchun). Agar ketma-ket ko'p xato chiqsa (MAX_CONSECUTIVE_ERRORS),
    bu sayt bizni bloklagani degani bo'lishi mumkin - shunda skanerlash
    butunlay to'xtatiladi va COOLDOWN_SECONDS dan keyin qaytadan
    boshlanadi (qayta-qayta bloklanishning oldini olish uchun)."""
    start = start or config.ROOM_SCAN_START
    end = end or config.ROOM_SCAN_END

    await db.set_setting("room_scan_status", "running")
    await db.set_setting("room_scan_started_at", str(int(time.time())))
    await db.set_setting("room_scan_heartbeat", str(int(time.time())))
    await db.set_setting("room_scan_progress", "0")
    await db.set_setting("room_scan_total", str(end - start + 1))

    # Avvalgi natijani yuklab, davom ettiramiz (agar bor bo'lsa)
    try:
        with open(config.BOSHXONALAR_FILE, "r", encoding="utf-8") as f:
            results = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        results = {}

    processed_since_save = 0
    done_count = 0
    consecutive_errors = 0

    for room_id in range(start, end + 1):
        try:
            svg_text = await _fetch_room_svg(room_id)
            results[str(room_id)] = build_room_result(room_id, svg_text)
            consecutive_errors = 0
        except Exception as e:
            logger.warning("Xona %s skanerlashda xatolik: %s", room_id, e)
            await db.log_error("room_scan", f"Xona {room_id}: {e}")
            results[str(room_id)] = {
                "room_id": room_id,
                "url": build_url(room_id),
                "error": str(e),
            }
            consecutive_errors += 1

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.warning(
                    "%s marta ketma-ket xato - sayt bloklagan bo'lishi mumkin. "
                    "%s daqiqaga to'xtatilmoqda.",
                    consecutive_errors, COOLDOWN_SECONDS // 60,
                )
                await db.set_setting("room_scan_status", "cooldown")
                await db.log_error(
                    "room_scan_cooldown",
                    f"{consecutive_errors} ketma-ket xatodan keyin {COOLDOWN_SECONDS // 60} "
                    f"daqiqaga to'xtatildi (xona {room_id} da).",
                )
                _save_progress(results)
                await asyncio.sleep(COOLDOWN_SECONDS)
                await db.set_setting("room_scan_status", "running")
                await db.set_setting("room_scan_heartbeat", str(int(time.time())))
                consecutive_errors = 0

        done_count += 1
        processed_since_save += 1
        await db.set_setting("room_scan_progress", str(done_count))
        await db.set_setting("room_scan_heartbeat", str(int(time.time())))

        if processed_since_save >= save_every:
            _save_progress(results)
            processed_since_save = 0

        await asyncio.sleep(REQUEST_DELAY_SECONDS)

    _save_progress(results)
    data_loader.store.reload()

    await db.set_setting("room_scan_status", "done")
    await db.set_setting("room_scan_finished_at", str(int(time.time())))
    logger.info("Xonalarni skanerlash tugadi: %s ta xona.", done_count)


async def weekly_room_scan_loop():
    """Har kuni bir marta tekshirib, agar oxirgi to'liq skanerlashdan
    beri ROOM_SCAN_INTERVAL_DAYS kun o'tgan bo'lsa, qaytadan
    skanerlashni avtomatik ishga tushiradi. Shuningdek, agar avvalgi
    skanerlash to'xtab qolgan (stuck) bo'lsa, uni ham qayta boshlaydi."""
    logger.info("Haftalik xona skanerlash nazoratchisi ishga tushdi.")
    while True:
        try:
            if await is_scan_stuck():
                logger.warning("Xonalar skanerlashi to'xtab qolgan edi - qaytadan boshlanmoqda.")
                await scan_all_rooms()
            else:
                last_finished = await db.get_setting("room_scan_finished_at")
                status = await db.get_setting("room_scan_status")
                now = time.time()

                should_run = False
                if not last_finished:
                    should_run = True
                else:
                    elapsed_days = (now - float(last_finished)) / 86400
                    if elapsed_days >= config.ROOM_SCAN_INTERVAL_DAYS:
                        should_run = True

                if should_run and status not in ("running", "cooldown"):
                    logger.info("Xonalarni avtomatik (haftalik) skanerlash boshlandi.")
                    await scan_all_rooms()
        except Exception:
            logger.exception("Haftalik skanerlash nazoratchisida xatolik.")

        await asyncio.sleep(5 * 60)  # har 5 daqiqada bir tekshiradi (stuck holatni tez aniqlash uchun)

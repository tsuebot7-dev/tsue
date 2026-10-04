"""
TSUE jadvali bilan sinxronlash - saytga QO'SHIMCHA so'rovsiz.

Eski fon skanerlari (room_scraper, teacher_scraper, group_url_scraper,
group_watcher) har hafta minglab sayt sahifasini ochar edi va shu
sababli server IP'si bloklanardi. Endi hammasi bot/timetable_data.py
yuklaydigan bitta JSON'dan (12 soatda 1 so'rov) qilinadi:

  - xonalar.json      - barcha xonalar va havolalari (yangilari qo'shiladi)
  - ustozlar.json     - barcha o'qituvchilar va havolalari (yangilari qo'shiladi)
  - guruhlar.json     - FAQAT havolalar yangilanadi; fakultet/kurs tuzilishi
                        sizniki bo'lib qoladi. Yangi guruhlar admin paneldagi
                        "Yangi topilganlar" bo'limiga chiqadi.
  - boshxonalar.json  - bo'sh xonalar to'liq qayta hisoblanadi
  - jadval o'zgarishi - kuzatilayotgan guruhlar ("Mening guruhim" va
                        Telegram guruhlar) uchun eski va yangi jadval
                        solishtiriladi, farq bo'lsa aniq xabar yuboriladi
  - eslatmalar        - saqlangan jadval nusxalari (schedule_snapshots)
                        yangi ma'lumot bilan yangilanadi
"""

import asyncio
import json
import logging
import re
import time

from aiogram.types import FSInputFile

from . import config, data_loader, db, timetable_data, ui

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 30 * 60
SITE = "https://tsue.edupage.org/timetable/view.php"
DAY_CODES = ["Mn", "Tu", "Wed", "Thu", "Fri", "Sat"]
DAY_SHORT_UZ = ["Du", "Se", "Ch", "Pa", "Ju", "Sh"]
PERIOD_TIMES = {
    1: "8:00-9:20", 2: "9:30-10:50", 3: "11:00-12:20", 4: "13:00-14:20",
    5: "14:30-15:50", 6: "16:00-17:20", 7: "17:30-18:50", 8: "19:00-20:20",
}
SNAPSHOT_PREFIX = "v2:"  # eski (SVG) formatdagi suratlardan ajratish uchun
STATUS_KEY = "tt_sync_last"
KNOWN_CLASSES_KEY = "tt_known_class_ids"

_lock = asyncio.Lock()
_synced_loaded_at: float | None = None


def site_url(kind: str, entity_id: str) -> str:
    return f"{SITE}?num={timetable_data._tt.tt_num or '94'}&{kind}={entity_id}"


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", (name or "")).lower()


def _write_json(path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _read_json(path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _entities(kind: str) -> dict:
    """{id: nom} - joriy jadvalda kamida bitta darsi bor obyektlar."""
    index = timetable_data._tt.index.get(kind, {})
    names = timetable_data._tt.names
    return {eid: names.get((kind, eid), "") for eid in index if names.get((kind, eid))}


# ================================================================ #
# Fayllar
# ================================================================ #

def _merge_flat(path, kind: str, include_all_rooms: bool = False) -> tuple[int, int]:
    """xonalar.json / ustozlar.json: mavjud nomlarning havolasini
    yangilaydi, saytda bor-u faylda yo'q nomlarni oxiriga qo'shadi.
    Faylga qo'lda qo'shilgan narsalar o'chirilmaydi."""
    flat = _read_json(path)
    if include_all_rooms:
        names = {eid: n for (k, eid), n in timetable_data._tt.names.items() if k == kind and n}
    else:
        names = _entities(kind)
    by_norm = {}
    for eid, name in names.items():
        by_norm.setdefault(_norm(name), (eid, name))

    updated = 0
    seen = set()
    for key, value in list(flat.items()):
        if key in data_loader.SKIP_KEYS or not isinstance(value, str) or not value.startswith("http"):
            continue
        hit = by_norm.get(_norm(key))
        if not hit:
            continue
        seen.add(_norm(key))
        url = site_url(kind, hit[0])
        if value != url:
            flat[key] = url
            updated += 1

    added = 0
    for norm, (eid, name) in sorted(by_norm.items(), key=lambda kv: kv[1][1].lower()):
        if norm in seen or name in flat:
            continue
        if kind == "teacher" and len(re.sub(r"[\W_]", "", name)) < 3:
            continue  # "-", ". ." kabi "o'qituvchi belgilanmagan" yozuvlari
        flat[name] = site_url(kind, eid)
        added += 1

    if updated or added:
        _write_json(path, flat)
    return updated, added


def _update_groups() -> tuple[int, list]:
    """guruhlar.json: faqat mavjud guruhlarning havolasini yangilaydi
    (tuzilish o'zgarmaydi). Faylda yo'q guruhlar ro'yxatini qaytaradi."""
    flat = _read_json(config.GURUHLAR_FILE)
    classes = _entities("class")
    by_norm = {}
    for eid, name in classes.items():
        by_norm.setdefault(_norm(name), eid)

    updated = 0
    present = set()
    for key, value in list(flat.items()):
        if not isinstance(value, str) or not value.startswith("http"):
            continue
        eid = by_norm.get(_norm(key))
        if not eid:
            continue
        present.add(eid)
        url = site_url("class", eid)
        if value != url:
            flat[key] = url
            updated += 1
    if updated:
        _write_json(config.GURUHLAR_FILE, flat)

    missing = [(eid, classes[eid]) for eid in classes if eid not in present]
    return updated, missing


def _build_free_rooms() -> int:
    """boshxonalar.json ni (bo'sh xonalar) JSON'dan to'liq qayta
    hisoblaydi. Format eski room_scraper bilan bir xil, shuning uchun
    data_loader va bo'sh xonalar bo'limi o'zgarishsiz ishlaydi.
    A yoki B haftaning birortasida dars bo'lsa - xona band hisoblanadi."""
    index = timetable_data._tt.index.get("classroom", {})
    result = {}
    for (kind, eid), name in timetable_data._tt.names.items():
        if kind != "classroom" or not name:
            continue
        busy = {}
        for lesson in index.get(eid, []):
            info = " | ".join(x for x in (
                lesson.get("subject"), "/".join(lesson.get("classes") or []), " / ".join(lesson.get("teachers") or []),
            ) if x)
            for day, flag in enumerate(lesson.get("days", "")):
                if flag != "1" or day >= len(DAY_CODES):
                    continue
                for period in range(lesson["period"], lesson.get("last_period", lesson["period"]) + 1):
                    busy[(DAY_CODES[day], period)] = info
        busy_slots, free_slots = [], []
        for day in DAY_CODES:
            for period, t in PERIOD_TIMES.items():
                entry = {"day": day, "period": period, "time": t}
                if (day, period) in busy:
                    busy_slots.append({**entry, "info": busy[(day, period)]})
                else:
                    free_slots.append(entry)
        key = eid.lstrip("*")
        result[key] = {
            "room_id": int(key) if key.isdigit() else key,
            "room_name": name,
            "url": site_url("classroom", eid),
            "busy_slots": busy_slots,
            "free_slots": free_slots,
        }
    _write_json(config.BOSHXONALAR_FILE, result)
    return len(result)


# ================================================================ #
# Jadval o'zgarishlari
# ================================================================ #

def _lesson_desc(lesson: dict) -> str:
    parts = [lesson.get("subject") or "—"]
    if lesson.get("rooms"):
        parts.append(" / ".join(lesson["rooms"]))
    if lesson.get("teachers"):
        parts.append(" / ".join(lesson["teachers"]))
    if lesson.get("subgroup"):
        parts.append(lesson["subgroup"])
    return " · ".join(parts)


def _slots(lessons: list) -> dict:
    """{"Du 14:30 (A hafta)": "Fizika · 5/402 · Karimov"} ko'rinishida."""
    slots: dict = {}
    for lesson in lessons:
        weeks = lesson.get("weeks") or ""
        week = {"10": " (A hafta)", "01": " (B hafta)"}.get(weeks, "")
        for day, flag in enumerate(lesson.get("days", "")):
            if flag != "1" or day >= len(DAY_SHORT_UZ):
                continue
            key = f"{day}|{lesson['start']}|{week}"
            slots.setdefault(key, []).append(_lesson_desc(lesson))
    return {k: "; ".join(sorted(v)) for k, v in slots.items()}


def _slot_label(key: str) -> str:
    day, start, week = key.split("|")
    return f"{DAY_SHORT_UZ[int(day)]} {start}{week}"


def diff_text(old: dict, new: dict, limit: int = 8) -> str:
    lines = []
    for key in sorted(set(old) | set(new), key=lambda k: (int(k.split("|")[0]), k.split("|")[1])):
        o, n = old.get(key), new.get(key)
        if o == n:
            continue
        label = f"<b>{ui.esc(_slot_label(key))}</b>"
        if o and n:
            op, np_ = o.split(" · "), n.split(" · ")
            if len(op) == len(np_) and op[0] == np_[0] and ";" not in o + n:
                # Bir xil fan - faqat o'zgargan qismini (xona/o'qituvchi) ko'rsatamiz
                parts = [f"{ui.esc(a)} → {ui.esc(b)}" for a, b in zip(op[1:], np_[1:]) if a != b]
                lines.append(f"🔄 {label}, {ui.esc(op[0])}: " + "; ".join(parts))
            else:
                lines.append(f"🔄 {label}: {ui.esc(o)} → {ui.esc(n)}")
        elif n:
            lines.append(f"➕ {label}: {ui.esc(n)}")
        else:
            lines.append(f"➖ {label}: <s>{ui.esc(o)}</s>")
    if len(lines) > limit:
        lines = lines[:limit] + [f"… va yana {len(lines) - limit} ta o'zgarish"]
    return "\n".join(lines)


async def _notify_change(group_name: str, url: str, changes: str) -> int:
    from .bot_instance import get_bot
    from .timetable_render import get_timetable_image

    user_ids = await db.get_users_watching_group(group_name)
    chat_ids = await db.get_telegram_groups_watching(group_name)
    if not user_ids and not chat_ids:
        return 0
    caption = ui.schedule_caption(
        "guruh", group_name, url,
        note=f"🔔 <b>Jadvalda o'zgarish bor!</b>\n{changes}",
    )
    if len(caption) > 1000:
        caption = caption[:990] + "…"
    bot = get_bot()
    png_path = await get_timetable_image(url)
    file_id, sent = None, 0
    try:
        for chat_id in list(user_ids) + list(chat_ids):
            try:
                msg = await bot.send_photo(chat_id, photo=file_id or FSInputFile(png_path), caption=caption)
                if file_id is None and msg.photo:
                    file_id = msg.photo[-1].file_id
                sent += 1
            except Exception as e:
                logger.info("O'zgarish xabari yuborilmadi (chat_id=%s): %s", chat_id, e)
            await asyncio.sleep(0.05)
    finally:
        png_path.unlink(missing_ok=True)
    return sent


async def _check_changes() -> int:
    changed = 0
    for g in await db.get_watched_group_names():
        name, url = g.get("default_group_name"), g.get("default_group_url")
        lessons = timetable_data.lessons_for_url(url or "")
        if not name or lessons is None:
            continue
        new_slots = _slots(lessons)
        stored = await db.get_group_snapshot(name)
        await db.set_group_snapshot(name, SNAPSHOT_PREFIX + json.dumps(new_slots, ensure_ascii=False, sort_keys=True))
        if not stored or not stored.startswith(SNAPSHOT_PREFIX):
            continue  # birinchi marta (yoki eski formatdagi surat) - solishtirishga narsa yo'q
        try:
            old_slots = json.loads(stored[len(SNAPSHOT_PREFIX):])
        except json.JSONDecodeError:
            continue
        if old_slots == new_slots:
            continue
        changes = diff_text(old_slots, new_slots)
        if not changes:
            continue
        changed += 1
        try:
            await _notify_change(name, url, changes)
        except Exception:
            logger.exception("O'zgarish xabarini yuborishda xatolik: %s", name)
    return changed


async def _refresh_reminder_snapshots() -> int:
    """Eslatmalar uchun saqlangan jadval nusxalarini yangilaydi."""
    updated = 0
    for snap in await db.get_all_schedule_snapshots():
        lessons = timetable_data.lessons_for_url(snap["url"])
        if lessons is None:
            continue
        if lessons != snap["lessons"]:
            await db.set_schedule_snapshot(snap["url"], snap["name"], lessons)
            updated += 1
    return updated


# ================================================================ #
# Asosiy sinxronlash
# ================================================================ #

async def sync(force_download: bool = False) -> dict | None:
    """JSON'ni (kerak bo'lsa) yangilab, barcha fayllar va o'zgarishlarni
    sinxronlaydi. Natija statistikasini qaytaradi va bazaga yozadi."""
    global _synced_loaded_at
    async with _lock:
        ok = await timetable_data.refresh(force=force_download)
        if not timetable_data.is_loaded():
            return None
        if not force_download and _synced_loaded_at == timetable_data._tt.loaded_at:
            return None  # yangi ma'lumot yo'q

        rooms_updated, rooms_added = await asyncio.to_thread(
            _merge_flat, config.XONALAR_FILE, "classroom", True)
        teachers_updated, teachers_added = await asyncio.to_thread(
            _merge_flat, config.USTOZLAR_FILE, "teacher")
        groups_updated, missing_groups = await asyncio.to_thread(_update_groups)
        free_rooms = await asyncio.to_thread(_build_free_rooms)
        data_loader.store.reload()

        # Faylda yo'q guruhlar - faqat ilgari ko'rilmaganlari "Yangi
        # topilganlar"ga chiqadi (admin o'chirgan narsa qayta chiqmaydi).
        try:
            known = set(json.loads(await db.get_setting(KNOWN_CLASSES_KEY, "[]") or "[]"))
        except json.JSONDecodeError:
            known = set()
        new_groups = [(eid, name) for eid, name in missing_groups if eid not in known]
        for eid, name in new_groups:
            await db.add_discovered_item("guruh", name, site_url("class", eid))
        await db.set_setting(KNOWN_CLASSES_KEY, json.dumps(sorted(known | {e for e, _ in missing_groups})))

        changes = await _check_changes()
        reminders_updated = await _refresh_reminder_snapshots()

        _synced_loaded_at = timetable_data._tt.loaded_at
        status = {
            "at": int(time.time()),
            "loaded_at": int(timetable_data._tt.loaded_at),
            "download_ok": timetable_data.site_status()["site_ok"],
            "tt_num": timetable_data._tt.tt_num,
            "validity": timetable_data.validity(),
            "groups_total": len(_entities("class")),
            "groups_updated": groups_updated,
            "groups_new": len(new_groups),
            "teachers_updated": teachers_updated,
            "teachers_added": teachers_added,
            "rooms_updated": rooms_updated,
            "rooms_added": rooms_added,
            "free_rooms": free_rooms,
            "changed_groups": changes,
            "reminder_snapshots_updated": reminders_updated,
        }
        await db.set_setting(STATUS_KEY, json.dumps(status))
        logger.info("TSUE sinxronlash tugadi: %s", status)
        return status


async def get_status() -> dict:
    try:
        return json.loads(await db.get_setting(STATUS_KEY, "{}") or "{}")
    except json.JSONDecodeError:
        return {}


async def sync_loop():
    logger.info("TSUE sinxronlash (JSON) ishga tushdi.")
    while True:
        try:
            await sync()
        except Exception:
            logger.exception("TSUE sinxronlashda xatolik.")
            await db.log_error("tt_sync", "Sinxronlashda xatolik (batafsil - server logida)")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

"""
TSUE (tsue.edupage.org) jadvalini MATN ko'rinishida (fan, xona,
o'qituvchi, boshlanish/tugash vaqti) olib beradi.

Skrinshot va SVG'dan farqli o'laroq, bu modul edupage'ning ichki JSON
API'sidan foydalanadi: BITTA so'rov bilan butun universitetning
jadvali (barcha guruhlar, fanlar, xonalar, o'qituvchilar) keladi.
Shuning uchun har bir guruh uchun alohida sahifa ochish shart emas va
TSUE saytiga deyarli yuk tushmaydi (TIMETABLE_REFRESH_HOURS da bir
marta).

Foydalanuvchi jadvalni saqlaganda shu ma'lumotdan guruhning haftalik
darslari ajratib olinib, bazaga matn ko'rinishida yoziladi. Dars
oldidan eslatmalar o'sha saqlangan nusxadan yuboriladi (qarang:
bot/reminders.py).
"""

import asyncio
import datetime
import gzip
import json
import logging
import re
import time

import aiohttp

from . import config

logger = logging.getLogger(__name__)

API_BASE = "https://tsue.edupage.org/timetable/server/"
# connect=10: sayt serverni bloklagan bo'lsa, uzoq kutib qolmaslik uchun.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=120, connect=10, sock_connect=10)
# Oxirgi muvaffaqiyatli yuklangan jadval diskda saqlanadi (~1 MB) - bot
# qayta ishga tushganda yoki sayt vaqtincha javob bermasa shundan
# foydalaniladi.
CACHE_FILE = config.DATA_DIR / "timetable_cache.json.gz"
# Sayt javob bermasa, har bir foydalanuvchi so'rovida qayta urinmaslik
# uchun shuncha vaqt kutiladi.
RETRY_AFTER_FAILURE_SECONDS = 15 * 60

# URL ichidagi "class=*1282", "teacher=*15", "classroom=*3" qismlari.
_URL_ENTITY_RE = re.compile(r"[?&](class|teacher|classroom)=(\*?-?\d+)")
_URL_NUM_RE = re.compile(r"[?&]num=(\d+)")


class _Timetable:
    def __init__(self):
        self.tt_num: str | None = None
        # Jadval amal qilish muddati, masalan "07/09/2026-30/09/2026"
        self.validity: str = ""
        self.loaded_at: float = 0.0
        self.failed_at: float = 0.0
        # Saytdan oxirgi marta MUVAFFAQIYATLI yuklangan vaqt (shu jarayonda).
        self.fetched_at: float = 0.0
        # "class" / "teacher" / "classroom" -> {id -> [lesson dict, ...]}
        self.index: dict[str, dict[str, list]] = {}
        # (kind, id) -> saytdagi nomi (rasm sarlavhasi uchun)
        self.names: dict[tuple, str] = {}
        self._lock = asyncio.Lock()

    @property
    def by_class(self) -> dict[str, list]:
        return self.index.get("class", {})

    @property
    def is_loaded(self) -> bool:
        return bool(self.by_class)


_tt = _Timetable()


async def _post(session: aiohttp.ClientSession, func_path: str, args: list) -> dict:
    async with session.post(
        API_BASE + func_path,
        json={"__args": args, "__gsh": "00000000"},
        timeout=REQUEST_TIMEOUT,
    ) as resp:
        resp.raise_for_status()
        # content_type=None: edupage javobni text/html deb belgilaydi.
        return await resp.json(content_type=None)


async def _latest_tt_num(session: aiohttp.ClientSession) -> str | None:
    """Saytda e'lon qilingan jadval versiyalaridan bugungi kunga eng
    mos (boshlanish sanasi bugundan oldin bo'lgan eng oxirgi)sini
    tanlaydi."""
    year = datetime.date.today().year
    today = datetime.date.today().isoformat()
    best = None
    for y in (year, year - 1):
        try:
            data = await _post(session, "ttviewer.js?__func=getTTViewerData", [None, y])
        except Exception:
            logger.exception("Jadval versiyalari ro'yxatini olib bo'lmadi (yil=%s).", y)
            continue
        for t in data.get("r", {}).get("regular", {}).get("timetables", []):
            if t.get("hidden"):
                continue
            if (t.get("datefrom") or "") <= today and (best is None or t["datefrom"] > best["datefrom"]):
                best = t
        if best:
            break
    return best["tt_num"] if best else None


def _clean_teacher(name: str) -> str:
    name = (name or "").strip()
    # Saytda "-", ".", ". ." kabi "o'qituvchi belgilanmagan" belgilari bor.
    if len(re.sub(r"[\W_]", "", name)) < 2:
        return ""
    return name


def _validity_text(raw: dict) -> str:
    """Saytda jadval ostida yoziladigan muddat ("Действительность:
    07/09/2026-30/09/2026") dan faqat sanalarni ajratadi."""
    try:
        tables = {t["id"]: t.get("data_rows", []) for t in raw["r"]["dbiAccessorRes"]["tables"]}
        text = tables["globals"][0]["settings"].get("m_strDateBellowTimeTable") or ""
    except (KeyError, IndexError, TypeError):
        return ""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{4})", text)
    if not m:
        return ""
    d1, m1, y1, d2, m2, y2 = m.groups()
    return f"{d1}.{m1}.{y1} – {d2}.{m2}.{y2}"


def validity() -> str:
    return _tt.validity


def _build_index(raw: dict) -> tuple[dict, dict]:
    tables = {t["id"]: t.get("data_rows", []) for t in raw["r"]["dbiAccessorRes"]["tables"]}

    periods = {p["period"]: p for p in tables["periods"]}
    subjects = {s["id"]: (s.get("name") or s.get("short") or "").strip() for s in tables["subjects"]}
    subject_colors = {s["id"]: s.get("color") or "" for s in tables["subjects"]}
    class_colors = {c["id"]: c.get("color") or "" for c in tables["classes"]}
    rooms = {r["id"]: (r.get("short") or r.get("name") or "").strip() for r in tables["classrooms"]}
    teachers = {t["id"]: _clean_teacher(t.get("short") or t.get("name")) for t in tables["teachers"]}
    teacher_colors = {t["id"]: t.get("color") or "" for t in tables["teachers"]}
    class_names = {c["id"]: (c.get("short") or c.get("name") or "").strip() for c in tables["classes"]}
    names = {}
    for c in tables["classes"]:
        names[("class", c["id"])] = (c.get("name") or c.get("short") or "").strip()
    for t in tables["teachers"]:
        names[("teacher", t["id"])] = (t.get("name") or t.get("short") or "").strip()
    for r in tables["classrooms"]:
        names[("classroom", r["id"])] = (r.get("name") or r.get("short") or "").strip()
    groups = {g["id"]: g for g in tables["groups"]}
    lessons = {l["id"]: l for l in tables["lessons"]}

    by_class: dict[str, list] = {}
    by_teacher: dict[str, list] = {}
    by_room: dict[str, list] = {}
    for card in tables["cards"]:
        lesson = lessons.get(card.get("lessonid"))
        period = periods.get(card.get("period") or "")
        days = card.get("days") or ""
        if not lesson or not period or "1" not in days:
            continue

        duration = int(lesson.get("durationperiods") or 1)
        last_period = periods.get(str(int(period["period"]) + duration - 1), period)

        base = {
            "lesson_id": lesson["id"],
            "days": days,
            "weeks": card.get("weeks") or "",
            "period": int(period["period"]),
            "last_period": int(last_period["period"]),
            "start": period["starttime"],
            "end": last_period["endtime"],
            "subject": subjects.get(lesson.get("subjectid"), ""),
            "rooms": [rooms[r] for r in card.get("classroomids") or [] if rooms.get(r)],
            "teachers": [teachers[t] for t in lesson.get("teacherids") or [] if teachers.get(t)],
            # Rasm chizish uchun: fan rangi (saytdagidek) va bir nechta
            # guruh birga o'tiradigan (potok) darsmi.
            "color": subject_colors.get(lesson.get("subjectid"), ""),
            "joint": len(lesson.get("classids") or []) > 1,
            # Pastki chiziq saytda darsdagi har bir guruh rangidagi
            # bo'laklardan iborat.
            "class_colors": [class_colors.get(c, "") for c in lesson.get("classids") or []],
            # O'qituvchi va xona jadvali uchun: darsdagi guruhlar va
            # o'qituvchi rangi.
            "classes": [class_names[c] for c in lesson.get("classids") or [] if class_names.get(c)],
            "teacher_color": next((teacher_colors[t] for t in lesson.get("teacherids") or [] if teacher_colors.get(t)), ""),
        }
        for teacher_id in lesson.get("teacherids") or []:
            by_teacher.setdefault(teacher_id, []).append(base)
        for room_id in card.get("classroomids") or []:
            by_room.setdefault(room_id, []).append(base)
        for class_id in lesson.get("classids") or []:
            # Agar dars guruhning faqat bir qismi (kichik guruh) uchun
            # bo'lsa, shu kichik guruh nomini ham ko'rsatamiz.
            subgroup = ""
            for gid in lesson.get("groupids") or []:
                g = groups.get(gid)
                if g and g.get("classid") == class_id and not g.get("entireclass"):
                    subgroup = (g.get("name") or "").strip()
            by_class.setdefault(class_id, []).append({**base, "subgroup": subgroup})
    return {"class": by_class, "teacher": by_teacher, "classroom": by_room}, names


def _save_cache(tt_num: str, raw: dict):
    try:
        tmp = CACHE_FILE.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump({"tt_num": tt_num, "saved_at": time.time(), "raw": raw}, f, ensure_ascii=False)
        tmp.replace(CACHE_FILE)
    except Exception:
        logger.exception("Jadval keshini diskka yozib bo'lmadi.")


def _load_cache() -> tuple[str, float, dict] | None:
    try:
        with gzip.open(CACHE_FILE, "rt", encoding="utf-8") as f:
            data = json.load(f)
        return data["tt_num"], float(data.get("saved_at") or 0), data["raw"]
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("Jadval keshini o'qib bo'lmadi.")
        return None


async def refresh(force: bool = False) -> bool:
    """Jadvalni TSUE saytidan qayta yuklaydi (agar eskirgan bo'lsa yoki
    force=True). Muvaffaqiyatli bo'lsa True qaytaradi. Xato bo'lsa,
    avvalgi yuklangan ma'lumot (xotiradagi yoki diskdagi) saqlanib
    qoladi."""
    async with _tt._lock:
        now = time.time()
        if not _tt.is_loaded:
            # Bot endi ishga tushdi - avval diskdagi nusxani yuklaymiz.
            cached = await asyncio.to_thread(_load_cache)
            if cached:
                tt_num, saved_at, raw = cached
                index, names = await asyncio.to_thread(_build_index, raw)
                _tt.tt_num, _tt.index, _tt.names = tt_num, index, names
                _tt.validity = _validity_text(raw)
                _tt.loaded_at = saved_at
                logger.info("TSUE jadvali diskdagi nusxadan yuklandi (tt_num=%s).", tt_num)

        age = now - _tt.loaded_at
        if not force and _tt.is_loaded and age < config.TIMETABLE_REFRESH_HOURS * 3600:
            return True
        if not force and now - _tt.failed_at < RETRY_AFTER_FAILURE_SECONDS:
            return _tt.is_loaded
        try:
            async with aiohttp.ClientSession() as session:
                tt_num = await _latest_tt_num(session) or _tt.tt_num or "94"
                raw = await _post(session, "regulartt.js?__func=regularttGetData", [None, tt_num])
            # 8 MB atrofidagi JSON - event loop'ni to'xtatib qo'ymaslik
            # uchun alohida thread'da qayta ishlanadi.
            index, names = await asyncio.to_thread(_build_index, raw)
            validity = _validity_text(raw)
        except Exception:
            _tt.failed_at = time.time()
            logger.exception("TSUE jadvalini (JSON) yuklab bo'lmadi.")
            return _tt.is_loaded
        await asyncio.to_thread(_save_cache, tt_num, raw)
        _tt.fetched_at = time.time()
        _tt.tt_num = tt_num
        _tt.index = index
        _tt.names = names
        _tt.validity = validity
        _tt.loaded_at = time.time()
        logger.info(
            "TSUE jadvali yuklandi: tt_num=%s, %s ta guruh, %s ta o'qituvchi, %s ta xona.",
            tt_num, len(index["class"]), len(index["teacher"]), len(index["classroom"]),
        )
        return True


def parse_url(url: str) -> tuple[str, str] | None:
    """Jadval havolasidan (kind, id) ni ajratadi, masalan
    ('class', '*1282'). Topilmasa None."""
    m = _URL_ENTITY_RE.search(url or "")
    if not m:
        return None
    return m.group(1), m.group(2)


def week_index(date: datetime.date) -> int:
    """0 = A hafta, 1 = B hafta."""
    try:
        anchor = datetime.date.fromisoformat(config.WEEK_A_MONDAY)
    except ValueError:
        anchor = datetime.date(2026, 9, 7)
    anchor -= datetime.timedelta(days=anchor.weekday())
    monday = date - datetime.timedelta(days=date.weekday())
    return ((monday - anchor).days // 7) % 2


def lessons_for_url(url: str) -> list | None:
    """Havola (guruh, o'qituvchi yoki xona) bo'yicha HAFTALIK barcha
    darslar (A va B hafta belgilari bilan). Jadval yuklanmagan yoki
    havoladagi ID saytda topilmasa None qaytaradi. Avval refresh()
    chaqirilgan bo'lishi kerak."""
    parsed = parse_url(url)
    if not parsed or not _tt.is_loaded or parsed not in _tt.names:
        return None
    return [dict(l) for l in _tt.index.get(parsed[0], {}).get(parsed[1], [])]


def name_for_url(url: str) -> str:
    """Havoladagi guruh/o'qituvchi/xonaning saytdagi nomi."""
    parsed = parse_url(url)
    return _tt.names.get(parsed, "") if parsed else ""


def lessons_for_day(lessons: list, date: datetime.date) -> list:
    """Haftalik darslar ro'yxatidan (lessons_for_url natijasi yoki
    bazadagi saqlangan nusxa) shu sanadagi darslarni ajratadi
    (boshlanish vaqti bo'yicha tartiblangan)."""
    weekday = date.weekday()
    week = week_index(date)
    result = []
    for lesson in lessons:
        days = lesson["days"]
        if weekday >= len(days) or days[weekday] != "1":
            continue
        weeks = lesson["weeks"]
        if weeks and week < len(weeks) and weeks[week] != "1":
            continue
        result.append(lesson)
    result.sort(key=lambda l: (l["period"], l["subject"]))

    # Ketma-ket paralarda bir xil dars bo'lsa (masalan 13:00-14:20 va
    # 14:30-15:50 da bir fan, bir xona), TSUE sayti ularni bitta uzun
    # dars sifatida ko'rsatadi. Biz ham shunday birlashtiramiz - aks
    # holda ikkinchi para uchun ortiqcha eslatma ketadi.
    merged = []
    for lesson in result:
        prev = next(
            (m for m in reversed(merged)
             if m["lesson_id"] == lesson["lesson_id"] and m["rooms"] == lesson["rooms"]
             and m["last_period"] + 1 == lesson["period"]),
            None,
        )
        if prev:
            prev["last_period"] = lesson["last_period"]
            prev["end"] = lesson["end"]
        else:
            merged.append(dict(lesson))
    merged.sort(key=lambda l: (l["start"], l["subject"]))
    return merged


def is_loaded() -> bool:
    return _tt.is_loaded


def site_status() -> dict:
    """Admin panel uchun: TSUE sayti bilan aloqa holati."""
    return {
        "site_ok": _tt.fetched_at > 0 and _tt.fetched_at >= _tt.failed_at,
        "fetched_at": _tt.fetched_at,
        "failed_at": _tt.failed_at,
        "data_from": _tt.loaded_at,
    }

"""
Dars jadvali rasmini TSUE saytiga murojaat qilmasdan, o'zimiz chizamiz.

Ma'lumot bot/timetable_data.py dan keladi (12 soatda bir marta
yuklanadigan JSON). Ko'rinish tsue.edupage.org dagi jadvalga imkon
qadar yaqin: tepada guruh nomi, ustunlarda paralar va vaqtlari,
qatorlarda kunlar, katak foni - fan rangining och tusi, katakda
o'qituvchi, fan va pastki chiziqda xona.

HTML shablon umumiy Playwright brauzerida (screenshot.py) chiziladi -
sahifa tarmoqqa chiqmaydi, shuning uchun TSUE serveriga hech qanday
so'rov ketmaydi va IP bloklanish xavfi yo'q.
"""

import datetime
import html
import logging
import uuid
from pathlib import Path

from . import config, screenshot, timetable_data

logger = logging.getLogger(__name__)

PERIODS = [
    (1, "8:00 - 9:20"), (2, "9:30 - 10:50"), (3, "11:00 - 12:20"), (4, "13:00 - 14:20"),
    (5, "14:30 - 15:50"), (6, "16:00 - 17:20"), (7, "17:30 - 18:50"), (8, "19:00 - 20:20"),
]
DAYS = ["Mn", "Tu", "Wed", "Thu", "Fri", "Sat"]

# Shrift loyiha ichida saqlanadi (bot/assets, SIL Open Font License) va
# brauzerga shu soxta manzil orqali beriladi - har bir rasm uchun
# Google Fonts'ga so'rov ketmaydi.
FONT_PATH = Path(__file__).parent / "assets" / "OpenSans.ttf"
FONT_URL = "https://render.local/OpenSans.ttf"
_font_bytes: bytes | None = None


def _font() -> bytes:
    global _font_bytes
    if _font_bytes is None:
        _font_bytes = FONT_PATH.read_bytes() if FONT_PATH.exists() else b""
    return _font_bytes
WEEK_LABELS = ["A hafta", "B hafta"]


def _esc(text) -> str:
    return html.escape(str(text or ""), quote=False)


def _light(color: str) -> str:
    """Saytdagidek: fan rangini oq bilan 50/50 aralashtiradi
    (#FFFF00 -> #FFFF80)."""
    c = (color or "").lstrip("#")
    if len(c) != 6:
        return "#eef0f6"
    try:
        r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#eef0f6"
    return "#%02x%02x%02x" % ((r + 255) // 2, (g + 255) // 2, (b + 255) // 2)


def _bar_background(lesson: dict) -> str:
    """Pastki chiziq: darsdagi har bir guruh rangining och tusidan
    teng bo'laklar (saytdagidek). Ma'lumot bo'lmasa - jigarrang."""
    colors = [_light(c) for c in lesson.get("class_colors") or [] if c]
    if not colors:
        return "#b39980"
    if len(colors) == 1:
        return colors[0]
    step = 100 / len(colors)
    stops = ", ".join(f"{c} {i * step:.2f}% {(i + 1) * step:.2f}%" for i, c in enumerate(colors))
    return f"linear-gradient(90deg, {stops})"


def _cards_by_slot(lessons: list) -> dict:
    """(kun, para) -> shu katakdagi darslar ro'yxati."""
    slots: dict = {}
    for lesson in lessons:
        for day, flag in enumerate(lesson.get("days", "")):
            if flag != "1" or day >= len(DAYS):
                continue
            slots.setdefault((day, lesson["period"]), []).append(lesson)
    return slots


def _week_note(weeks: str) -> str:
    if weeks in ("10", "01"):
        return WEEK_LABELS[weeks.index("1")]
    return ""


def _card_html(lesson: dict, kind: str) -> str:
    """Katak ko'rinishi saytdagidek, jadval turiga qarab:
      guruh:      o'qituvchi / FAN / [guruh ranglaridagi chiziq: xona]
      o'qituvchi: fan / guruhlar / [o'qituvchi rangidagi chiziq: xona]
      xona:       fan / guruhlar / o'qituvchi   (fon - o'qituvchi rangi)
    """
    teachers = " / ".join(lesson.get("teachers") or [])
    rooms = " / ".join(lesson.get("rooms") or [])
    classes = "/".join(lesson.get("classes") or [])
    notes = [n for n in (lesson.get("subgroup"), _week_note(lesson.get("weeks", ""))) if n]
    note_html = f'<div class="note">{_esc(" · ".join(notes))}</div>' if notes else ""

    if kind == "teacher":
        return (
            f'<div class="card alt" style="--bg:{_light(lesson.get("color"))}">'
            f'<div class="top">{_esc(lesson.get("subject"))}</div>'
            f'<div class="mid">{_esc(classes)}</div>{note_html}'
            f'<div class="bar" style="background:{_light(lesson.get("teacher_color")) if lesson.get("teacher_color") else "#b39980"}">'
            f'<span class="room">{_esc(rooms)}</span></div></div>'
        )
    if kind == "classroom":
        return (
            f'<div class="card alt" style="--bg:{_light(lesson.get("teacher_color") or lesson.get("color"))}">'
            f'<div class="top">{_esc(lesson.get("subject"))}</div>'
            f'<div class="mid">{_esc(classes)}</div>{note_html}'
            f'<div class="bottom">{_esc(teachers)}</div></div>'
        )
    return (
        f'<div class="card" style="--bg:{_light(lesson.get("color"))}">'
        f'<div class="teacher">{_esc(teachers)}</div>'
        f'<div class="subject">{_esc(lesson.get("subject"))}</div>{note_html}'
        f'<div class="bar" style="background:{_bar_background(lesson)}"><span class="room">{_esc(rooms)}</span></div>'
        "</div>"
    )


def build_html(title: str, lessons: list, today: datetime.date | None = None, signature: str = "", kind: str = "class") -> str:
    slots = _cards_by_slot(lessons)
    cells = []
    for day_idx, day in enumerate(DAYS):
        row = 2 + day_idx
        today_cls = " today" if today and today.weekday() == day_idx else ""
        cells.append(f'<div class="day{today_cls}" style="grid-row:{row}">{day}</div>')
        covered = set()
        for period, _ in PERIODS:
            if period in covered:
                continue
            cards = slots.get((day_idx, period), [])
            span = max((c.get("last_period", c["period"]) - c["period"] + 1 for c in cards), default=1)
            span = max(1, min(span, 9 - period))
            covered.update(range(period, period + span))
            inner = "".join(_card_html(c, kind) for c in cards)
            cells.append(
                f'<div class="cell{today_cls}" style="grid-row:{row};grid-column:{period + 1} / span {span}">'
                f"{inner}</div>"
            )

    header = "".join(
        f'<div class="ph" style="grid-column:{n + 1}"><b>{n}{"." if n == 8 else ""}</b><span>{t}</span></div>'
        for n, t in PERIODS
    )
    validity = timetable_data.validity()
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
  @font-face {{ font-family: "Open Sans"; src: url("{FONT_URL}") format("truetype"); font-weight: 300 800; font-display: block; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #fff; font-family: "Open Sans", "Liberation Sans", Arial, sans-serif; color: #000; }}
  .sheet {{ width: 1320px; padding: 26px 28px 18px; }}
  h1 {{ margin: 0; text-align: center; font-size: 34px; font-weight: 400; letter-spacing: 0.5px; }}
  .school {{ font-size: 14.5px; margin: 2px 0 4px; }}
  .grid {{
    display: grid;
    grid-template-columns: 50px repeat(8, 1fr);
    grid-template-rows: 72px repeat(6, 116px);
    border: 1.5px solid #000;
  }}
  .grid > div {{ border-right: 1px solid #9a9a9a; border-bottom: 1px solid #9a9a9a; }}
  .corner {{ grid-row: 1; grid-column: 1; border-right: 1px solid #000 !important; border-bottom: 1px solid #000 !important; }}
  .ph {{ grid-row: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
        border-bottom: 1px solid #000 !important; line-height: 1.1; }}
  .ph b {{ font-size: 23px; font-weight: 700; }}
  .ph span {{ font-size: 16px; }}
  .day {{ grid-column: 1; display: flex; align-items: center; justify-content: center;
         font-size: 21px; border-right: 1px solid #000 !important; }}
  .day.today {{ background: #fff4c2; font-weight: 700; }}
  .cell {{ display: flex; flex-direction: column; min-width: 0; }}
  .card {{ flex: 1; display: flex; flex-direction: column; background: var(--bg); min-height: 0; overflow: hidden; }}
  .card + .card {{ border-top: 1px solid #9a9a9a; }}
  .teacher {{ font-size: 12.5px; font-weight: 700; padding: 3px 7px 0; line-height: 1.12;
             display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
  .subject {{ flex: 1; display: flex; align-items: center; justify-content: center; text-align: center;
             font-size: 11.5px; font-weight: 700; line-height: 1.05; padding: 1px 6px; overflow: hidden; }}
  .note {{ font-size: 10.5px; text-align: center; color: #333; }}
  .bar {{ height: 22px; background: #b39980; display: flex; justify-content: flex-end; flex-shrink: 0; }}
  .room {{ font-size: 12.5px; font-weight: 700; padding: 0 6px; display: flex; align-items: center; justify-content: flex-end;
          white-space: nowrap; overflow: hidden; }}
  .card.alt .top {{ font-size: 11.5px; padding: 3px 7px 0; line-height: 1.1;
                   display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }}
  .card.alt .mid {{ flex: 1; display: flex; align-items: center; justify-content: center; text-align: center;
                   font-size: 10.5px; padding: 0 6px; line-height: 1.15; overflow: hidden; word-break: break-all; }}
  .card.alt .room {{ font-weight: 600; font-size: 11.5px; }}
  .card.alt .bottom {{ font-size: 11px; text-align: right; padding: 0 7px 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .foot {{ display: flex; justify-content: space-between; font-size: 14.5px; margin-top: 6px; }}
</style></head><body>
<div class="sheet" id="sheet">
  <h1>{_esc(title)}</h1>
  <div class="school">Tashkent State University of Economics, Uzbekiston avenue 49</div>
  <div class="grid"><div class="corner"></div>{header}{''.join(cells)}</div>
  <div class="foot"><span>{"Amal qiladi: " + _esc(validity) if validity else ""}</span><span>{_esc(signature)}</span></div>
</div></body></html>"""


async def render_html(html_doc: str, width: int = 1320, selector: str = "#sheet", scale: float = 1.5) -> Path:
    """Istalgan HTML sahifani (tarmoqqa chiqmasdan, loyiha shrifti bilan)
    PNG rasmga chizadi. Jadval va yo'riqnoma rasmlari shu orqali chiziladi."""
    browser = await screenshot.ensure_browser()
    page = await browser.new_page(viewport={"width": width, "height": 900}, device_scale_factor=scale)
    try:
        async def _serve_font(route):
            if _font():
                await route.fulfill(status=200, body=_font(), content_type="font/ttf")
            else:
                await route.abort()

        await page.route(FONT_URL, _serve_font)
        await page.set_content(html_doc, wait_until="load", timeout=15000)
        try:
            await page.evaluate("document.fonts.ready")
        except Exception:
            pass
        out = config.SCREENSHOT_DIR / f"{uuid.uuid4().hex}.png"
        await page.locator(selector).screenshot(path=str(out))
        return out
    finally:
        await page.close()


async def render_png(title: str, lessons: list, today: datetime.date | None = None, signature: str = "", kind: str = "class") -> Path:
    """Jadval rasmini PNG faylga chizadi va yo'lini qaytaradi (chaqiruvchi
    yuborgach o'chiradi)."""
    return await render_html(build_html(title, lessons, today, signature, kind))


_bot_username: str | None = None


async def get_timetable_image(url: str) -> Path:
    """Botning barcha bo'limlari jadval rasmini shu funksiya orqali oladi.

    Avval jadvalni o'zimiz chizamiz (saytga so'rovsiz). Faqat jadval
    ma'lumoti umuman yuklanmagan yoki havoladagi ID saytning joriy
    jadvalida topilmagan holatda eski usulga - saytdan skrinshot
    olishga - qaytamiz."""
    global _bot_username
    # Jadval allaqachon yuklangan bo'lsa saytni kutmaymiz - yangilash
    # fonda (tt_sync) bajariladi. Faqat umuman ma'lumot bo'lmasa yuklaymiz.
    if not timetable_data.is_loaded():
        await timetable_data.refresh()
    lessons = timetable_data.lessons_for_url(url)
    parsed = timetable_data.parse_url(url)
    if lessons is None or parsed is None:
        logger.info("Jadval JSON'da topilmadi, saytdan skrinshot olinadi: %s", url)
        return await screenshot.take_timetable_screenshot(url)

    if _bot_username is None:
        try:
            from .bot_instance import get_bot

            _bot_username = (await get_bot().get_me()).username or ""
        except Exception:
            _bot_username = ""
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=5)).date()
    try:
        return await render_png(
            timetable_data.name_for_url(url), lessons, today,
            f"@{_bot_username}" if _bot_username else "", parsed[0],
        )
    except Exception:
        logger.exception("Jadvalni chizib bo'lmadi, saytdan skrinshot olinadi: %s", url)
        return await screenshot.take_timetable_screenshot(url)

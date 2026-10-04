"""
"Botni Telegram guruhga ulash" yo'riqnomasi - matn o'rniga RASM bilan.

Rasm 4 qadamni Telegram oynasiga o'xshash chizmalar bilan ko'rsatadi va
botning haqiqiy @username'i bilan chiziladi. Bir marta chizilib, keyin
Telegram'dagi file_id orqali qayta yuboriladi (har safar qayta
chizilmaydi va qayta yuklanmaydi).

Rasm ostida:
  - "➕ Botni guruhga qo'shish" - Telegram'ning guruh tanlash oynasini
    to'g'ridan-to'g'ri ochadi (?startgroup havolasi);
  - "📋 Buyruqni nusxalash" - /start@bot buyrug'ini nusxalaydi (aiogram
    3.14+ / Bot API 7.11+ da; eski versiyada tugma ko'rinmaydi, lekin
    matndagi buyruqni bosish orqali baribir nusxalanadi).
"""

import html
import logging
from pathlib import Path

from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from . import timetable_render

try:  # aiogram 3.14+
    from aiogram.types import CopyTextButton
except ImportError:  # eski aiogram - nusxalash tugmasisiz ishlaydi
    CopyTextButton = None

logger = logging.getLogger(__name__)

_cache: dict = {"username": None, "path": None, "file_id": None}


def setup_command(username: str) -> str:
    return f"/start@{username}"


def caption(username: str) -> str:
    cmd = html.escape(setup_command(username))
    return (
        "👥 <b>Botni Telegram guruhga ulash</b>\n"
        "<i>Guruhingizga dars jadvali va har bir dars oldidan eslatma avtomatik keladi</i>\n\n"
        "1️⃣ «➕ Botni guruhga qo'shish» tugmasini bosing va guruhni tanlang\n"
        f"2️⃣ Guruhda buyruqni yuboring 👉 <code>{cmd}</code>\n"
        "     <i>(buyruqni bosing — nusxalanadi)</i>\n"
        "3️⃣ Fakultet › kurs › guruhni tanlang\n"
        "4️⃣ Kun va soatni belgilang — tayyor ✅\n\n"
        "<i>Buyruqni guruh admini yuborishi kerak.</i>"
    )


def keyboard(username: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="➕ Botni guruhga qo'shish", url=f"https://t.me/{username}?startgroup=jadval")]]
    if CopyTextButton is not None:
        rows.append([InlineKeyboardButton(
            text="📋 Buyruqni nusxalash", copy_text=CopyTextButton(text=setup_command(username)),
        )])
    rows.append([InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="nav:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_html(username: str) -> str:
    u = html.escape(username)
    cmd = html.escape(setup_command(username))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  @font-face {{ font-family: "Open Sans"; src: url("{timetable_render.FONT_URL}") format("truetype"); font-weight: 300 800; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: "Open Sans", Arial, sans-serif; color: #0f172a; }}
  #sheet {{ width: 1200px; padding: 44px 46px 36px; background: linear-gradient(150deg, #eef4ff 0%, #f5f3ff 55%, #ecfdf5 100%); }}
  .head {{ display: flex; align-items: center; gap: 18px; margin-bottom: 30px; }}
  .logo {{ width: 64px; height: 64px; border-radius: 18px; display: grid; place-items: center; font-size: 34px;
          background: linear-gradient(135deg, #3b82f6, #6366f1); box-shadow: 0 10px 24px -8px rgba(59,130,246,.6); }}
  h1 {{ margin: 0; font-size: 38px; font-weight: 800; letter-spacing: -0.02em; }}
  .sub {{ margin-top: 4px; color: #475569; font-size: 19px; font-weight: 600; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }}
  .step {{ background: #fff; border-radius: 26px; padding: 24px 24px 22px; box-shadow: 0 12px 30px -14px rgba(15,23,42,.25);
          border: 1px solid #e2e8f0; display: flex; flex-direction: column; gap: 16px; }}
  .st-head {{ display: flex; align-items: center; gap: 14px; }}
  .num {{ width: 46px; height: 46px; border-radius: 50%; display: grid; place-items: center; color: #fff;
         font-size: 22px; font-weight: 800; flex-shrink: 0; }}
  .n1 {{ background: linear-gradient(135deg, #3b82f6, #2563eb); }}
  .n2 {{ background: linear-gradient(135deg, #8b5cf6, #7c3aed); }}
  .n3 {{ background: linear-gradient(135deg, #f97316, #ea580c); }}
  .n4 {{ background: linear-gradient(135deg, #10b981, #059669); }}
  .st-title {{ font-size: 23px; font-weight: 800; }}
  .st-text {{ color: #475569; font-size: 16.5px; font-weight: 600; margin-top: 2px; }}
  .phone {{ background: #dbe6f1; border-radius: 18px; padding: 16px; height: 238px; display: flex; flex-direction: column; gap: 10px;
           border: 1px solid #cbd5e1; overflow: hidden; }}
  .bar {{ display: flex; align-items: center; gap: 10px; background: #fff; border-radius: 12px; padding: 9px 12px; font-weight: 700; font-size: 15px; }}
  .av {{ width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; color: #fff; font-weight: 800; font-size: 14px; flex-shrink: 0; }}
  .row {{ display: flex; align-items: center; gap: 10px; background: #fff; border-radius: 12px; padding: 8px 12px; font-size: 15px; font-weight: 600; }}
  .row.sel {{ outline: 3px solid #3b82f6; }}
  .chk {{ margin-left: auto; width: 22px; height: 22px; border-radius: 50%; background: #3b82f6; color: #fff; display: grid; place-items: center; font-size: 13px; }}
  .cta {{ margin-top: auto; background: #3b82f6; color: #fff; border-radius: 12px; padding: 11px; text-align: center; font-weight: 800; font-size: 16px;
         box-shadow: 0 8px 18px -8px rgba(59,130,246,.8); }}
  .msg-out {{ align-self: flex-end; background: #dcf8c6; border-radius: 16px 16px 4px 16px; padding: 10px 14px; font-size: 18px; font-weight: 800;
             font-family: "Consolas", monospace; color: #166534; box-shadow: 0 2px 4px rgba(0,0,0,.08); }}
  .msg-in {{ align-self: flex-start; background: #fff; border-radius: 16px 16px 16px 4px; padding: 10px 14px; font-size: 15px; font-weight: 600; max-width: 88%;
            box-shadow: 0 2px 4px rgba(0,0,0,.08); }}
  .copy {{ align-self: flex-end; background: #0f172a; color: #fff; border-radius: 10px; padding: 7px 12px; font-size: 14px; font-weight: 700; }}
  .input {{ margin-top: auto; display: flex; align-items: center; gap: 10px; background: #fff; border-radius: 22px; padding: 10px 14px;
           font-family: "Consolas", monospace; font-weight: 700; font-size: 16px; color: #2563eb; }}
  .send {{ margin-left: auto; width: 32px; height: 32px; border-radius: 50%; background: #3b82f6; color: #fff; display: grid; place-items: center; font-size: 16px; }}
  .btns {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }}
  .tb {{ background: rgba(30,41,59,.55); color: #fff; border-radius: 9px; padding: 8px 6px; text-align: center; font-size: 14px; font-weight: 700; }}
  .tb.on {{ background: #2563eb; }}
  .foot {{ margin-top: 26px; display: flex; justify-content: space-between; align-items: center; color: #475569; font-size: 17px; font-weight: 700; }}
  .foot b {{ color: #2563eb; }}
</style></head><body><div id="sheet">
  <div class="head">
    <div class="logo">👥</div>
    <div><h1>Botni Telegram guruhga ulash</h1><div class="sub">4 ta oddiy qadam · taxminan 1 daqiqa</div></div>
  </div>
  <div class="grid">
    <div class="step">
      <div class="st-head"><div class="num n1">1</div><div><div class="st-title">Botni guruhga qo'shing</div>
        <div class="st-text">«➕ Botni guruhga qo'shish» tugmasi → guruhni tanlang</div></div></div>
      <div class="phone">
        <div class="bar">Guruhni tanlang</div>
        <div class="row sel"><div class="av" style="background:#3b82f6">AT</div>AT-75/23 guruhi<div class="chk">✓</div></div>
        <div class="row"><div class="av" style="background:#f97316">K</div>Kursdoshlar</div>
        <div class="cta">Guruhga qo'shish</div>
      </div>
    </div>
    <div class="step">
      <div class="st-head"><div class="num n2">2</div><div><div class="st-title">Buyruqni yuboring</div>
        <div class="st-text">Nusxa oling va guruhga yuboring (admin)</div></div></div>
      <div class="phone">
        <div class="bar"><div class="av" style="background:#3b82f6">AT</div>AT-75/23 guruhi</div>
        <div class="msg-out">{cmd}</div>
        <div class="copy">📋 Buyruqni nusxalash</div>
        <div class="input">{cmd}<div class="send">➤</div></div>
      </div>
    </div>
    <div class="step">
      <div class="st-head"><div class="num n3">3</div><div><div class="st-title">Guruhingizni tanlang</div>
        <div class="st-text">Fakultet › kurs › guruh</div></div></div>
      <div class="phone">
        <div class="msg-in">👋 Bu guruhga dars jadvalini ulaymiz.<br><b>Guruhni tanlang:</b></div>
        <div class="btns">
          <div class="tb">Menejment</div><div class="tb">Iqtisodiyot</div>
          <div class="tb">1-kurs</div><div class="tb">2-kurs</div>
          <div class="tb on">AT-75/23</div><div class="tb">AT-76/23</div>
        </div>
      </div>
    </div>
    <div class="step">
      <div class="st-head"><div class="num n4">4</div><div><div class="st-title">Kun va soatni belgilang</div>
        <div class="st-text">Jadval shu vaqtda guruhga keladi</div></div></div>
      <div class="phone">
        <div class="btns">
          <div class="tb on">✅ Dushanba</div><div class="tb on">✅ Chorshanba</div>
          <div class="tb">▫️ Juma</div><div class="tb on">🕐 08:00</div>
        </div>
        <div class="msg-in">✅ <b>Tayyor! Guruh ulandi.</b><br>Jadval va dars eslatmalari avtomatik keladi 🔔</div>
      </div>
    </div>
  </div>
  <div class="foot"><span>📅 TSUE dars jadvali</span><span><b>@{u}</b></span></div>
</div></body></html>"""


async def _image(username: str) -> Path:
    path = _cache.get("path")
    if _cache.get("username") == username and path and Path(path).exists():
        return Path(path)
    path = await timetable_render.render_html(build_html(username), width=1200, scale=1.25)
    _cache.update(username=username, path=str(path), file_id=None)
    return path


async def send_guide(bot, chat_id: int):
    """Yo'riqnoma rasmini, izohini va tugmalarini yuboradi."""
    username = (await bot.get_me()).username or ""
    text, markup = caption(username), keyboard(username)
    if _cache.get("username") == username and _cache.get("file_id"):
        try:
            await bot.send_photo(chat_id, photo=_cache["file_id"], caption=text, reply_markup=markup)
            return
        except Exception:
            _cache["file_id"] = None
    try:
        path = await _image(username)
        msg = await bot.send_photo(chat_id, photo=FSInputFile(path), caption=text, reply_markup=markup)
        if msg.photo:
            _cache["file_id"] = msg.photo[-1].file_id
    except Exception:
        logger.exception("Guruh yo'riqnomasi rasmini yuborib bo'lmadi - matn yuboriladi.")
        await bot.send_message(chat_id, text, reply_markup=markup)

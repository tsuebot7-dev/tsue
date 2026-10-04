"""
Foydalanuvchiga ko'rinadigan xabarlarning umumiy "dizayn tizimi".

Barcha bo'limlar (talaba, o'qituvchi, xona, bo'sh xona, "Mening
jadvalim", AI orqali so'rov) jadvalni bir xil ko'rinishda yuklaydi va
yuboradi:

  ⏳ AT-75/23 jadvali tayyorlanmoqda…
  Shoshilinch bo'lsa, AT-75/23 havolasi orqali saytda ko'ring.

Havolalar ochiq URL ko'rinishida emas, bosiladigan nom ko'rinishida
chiqadi ("AT-75/23" ni bossangiz - TSUE saytidagi jadval ochiladi).

Bot HTML parse_mode bilan ishlaydi, shuning uchun ma'lumotlardan
keladigan har qanday nom shu yerdagi esc() orqali o'tkaziladi.
"""

import hashlib
import html

from aiogram.types import InlineKeyboardButton

# Jadval turlari: ikonka va qisqa tavsif
KINDS = {
    "guruh": ("🎓", "Talaba guruhi"),
    "ustoz": ("👨‍🏫", "O'qituvchi"),
    "xona": ("🚪", "Xona"),
    "free": ("🟢", "Bo'sh xona"),
    "mygroup": ("⭐", "Mening guruhim"),
}


def esc(text) -> str:
    return html.escape(str(text or ""), quote=False)


def link(text, url: str) -> str:
    """Bosiladigan nom: <a href="...">AT-75/23</a>"""
    if not url:
        return f"<b>{esc(text)}</b>"
    return f'<a href="{html.escape(url, quote=True)}">{esc(text)}</a>'


def site_button(url: str, text: str = "🌐 Saytda ochish") -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def loading_text(name: str, url: str) -> str:
    return (
        f"⏳ <b>{esc(name)}</b> jadvali tayyorlanmoqda…\n\n"
        f"<i>Shoshilinch bo'lsa, {link(name, url)} havolasi orqali saytda ko'ring.</i>"
    )


def schedule_caption(kind: str, name: str, url: str, bot_username: str | None = None, note: str = "") -> str:
    """Jadval rasmi ostidagi matn."""
    icon, label = KINDS.get(kind, ("📅", "Dars jadvali"))
    lines = [
        f"{icon} <b>{link(name, url)}</b>",
        f"<i>{esc(label)} · dars jadvali</i>",
    ]
    if note:
        lines += ["", note]
    footer = "🔗 Saytda ochish uchun nomini bosing"
    if bot_username:
        footer += f"\n🤖 @{esc(bot_username)}"
    lines += ["", footer]
    return "\n".join(lines)


def error_text(name: str, url: str) -> str:
    """Skrinshot olinmaganda - texnik xatolik matnisiz, foydalanuvchiga
    tushunarli xabar."""
    return (
        f"😕 <b>{esc(name)}</b> jadvalini hozir yuklab bo'lmadi.\n\n"
        f"TSUE sayti sekin ishlayotgan bo'lishi mumkin. "
        f"{link(name, url)} havolasi orqali to'g'ridan-to'g'ri ko'ring "
        f"yoki birozdan keyin qayta urinib ko'ring."
    )


def header(icon: str, title: str, subtitle: str = "") -> str:
    """Bo'lim sarlavhasi: qalin sarlavha + (ixtiyoriy) kulrang izoh."""
    text = f"{icon} <b>{esc(title)}</b>"
    if subtitle:
        text += f"\n<i>{esc(subtitle)}</i>"
    return text


# ---------------------------------------------------------------- #
# Tugma "callback_data" si Telegram'da 64 baytdan oshmasligi kerak.
# Oshsa, Telegram BUTUN menyuni rad etadi va tugma umuman ishlamaydi
# (masalan "UNICON.UZ. Yangi raqamli texnologiyalarni o'qitish
# markazi" kabi uzun xona nomlari). Shunday nomlar o'rniga qisqa kod
# yoziladi va bosilganda qayta nomga aylantiriladi.
# ---------------------------------------------------------------- #

_CB_LIMIT = 64
_cb_names: dict[str, str] = {}


def _cb_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def cb(prefix: str, value: str) -> str:
    data = f"{prefix}:{value}"
    if len(data.encode("utf-8")) <= _CB_LIMIT and not value.startswith("#"):
        return data
    code = _cb_hash(value)
    _cb_names[code] = value
    return f"{prefix}:#{code}"


def cb_value(raw: str, candidates=()) -> str | None:
    """cb() bilan yaratilgan qiymatni qaytaradi. Bot qayta ishga tushgan
    bo'lsa (xotira tozalangan), kod `candidates` ichidan qidiriladi."""
    if not raw.startswith("#"):
        return raw
    code = raw[1:]
    if code in _cb_names:
        return _cb_names[code]
    for value in candidates:
        if _cb_hash(value) == code:
            _cb_names[code] = value
            return value
    return None

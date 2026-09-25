from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

PAGE_SIZE = 15

DAYS = [
    ("Mn", "Dushanba"),
    ("Tu", "Seshanba"),
    ("Wed", "Chorshanba"),
    ("Thu", "Payshanba"),
    ("Fri", "Juma"),
    ("Sat", "Shanba"),
]

PERIOD_TIMES = {
    1: "8:00-9:20",
    2: "9:30-10:50",
    3: "11:00-12:20",
    4: "13:00-14:20",
    5: "14:30-15:50",
    6: "16:00-17:20",
    7: "17:30-18:50",
    8: "19:00-20:20",
}


POST_DAYS = [
    ("mon", "Dushanba"),
    ("tue", "Seshanba"),
    ("wed", "Chorshanba"),
    ("thu", "Payshanba"),
    ("fri", "Juma"),
    ("sat", "Shanba"),
    ("sun", "Yakshanba"),
]

DAY_LABELS_SHORT = dict(POST_DAYS)

POST_TIMES = ["06:00", "09:00", "11:00", "13:00", "15:00", "17:00", "19:00", "21:00", "23:00"]


def days_toggle_kb(selected: list) -> InlineKeyboardMarkup:
    """Guruhga jadval yuborilishi kerak bo'lgan hafta kunlarini
    ko'p-tanlovli (checkbox uslubidagi) tugmalar bilan ko'rsatadi."""
    b = InlineKeyboardBuilder()
    for code, label in POST_DAYS:
        mark = "✅ " if code in selected else "⬜ "
        b.button(text=mark + label, callback_data=f"gs:day:{code}")
    b.adjust(1)
    b.row(InlineKeyboardButton(text="💾 Saqlash", callback_data="gs:days_done"))
    return b.as_markup()


def times_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in POST_TIMES:
        b.button(text=t, callback_data=f"gs:time:{t}")
    b.adjust(3)
    return b.as_markup()


def main_menu_kb(default_group_name: str | None = None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎓 Talabalar", callback_data="menu:guruh")
    b.button(text="👨‍🏫 O'qituvchilar", callback_data="menu:ustoz")
    b.button(text="🚪 Xonalar", callback_data="menu:xona")
    b.button(text="🟢 Bo'sh xonalarni topish", callback_data="menu:free")
    b.adjust(2, 2)

    rows = list(b.export())

    if default_group_name:
        rows.insert(0, [InlineKeyboardButton(
            text=f"🎓 Mening jadvalim ({default_group_name})",
            callback_data="mygroup",
        )])

    rows.append([InlineKeyboardButton(text="🌐 Til / Язык", callback_data="lang:menu")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def nav_kb(names: list, page: int, can_go_back: bool, prefix: str = "nav") -> InlineKeyboardMarkup:
    """names: joriy darajadagi barcha nomlar ro'yxati (tartib bo'yicha).
    page: qaysi sahifa ko'rsatilmoqda.
    Callback data: "{prefix}:idx:<absolute_index>" | "{prefix}:page:prev" |
                    "{prefix}:page:next" | "{prefix}:back" | "{prefix}:home"
    """
    b = InlineKeyboardBuilder()
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    for i, name in enumerate(names[start:end], start=start):
        b.button(text=name, callback_data=f"{prefix}:idx:{i}")
    b.adjust(1)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"{prefix}:page:prev"))
    if end < len(names):
        nav_row.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"{prefix}:page:next"))
    if nav_row:
        b.row(*nav_row)

    bottom_row = []
    if can_go_back:
        bottom_row.append(InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"{prefix}:back"))
    bottom_row.append(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data=f"{prefix}:home"))
    b.row(*bottom_row)

    return b.as_markup()


def after_result_kb(prefix: str = "nav") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔙 Orqaga", callback_data=f"{prefix}:back")
    b.button(text="🏠 Bosh menyu", callback_data=f"{prefix}:home")
    b.adjust(2)
    return b.as_markup()


def loading_text(name: str, url: str) -> str:
    """Jadval skrinshoti tayyorlanayotganda ko'rsatiladigan "yuklanmoqda"
    xabari - nomi va shu havolasi bilan birga (dars jadvali, ustozlar
    jadvali, xonalar jadvali va bosh xonalar jadvali - barchasi uchun
    bir xil ko'rinishda)."""
    return f"⏳ {name} jadvali yuklanmoqda...\n🔗 {url}"


# Botning o'z username'ini (masalan "tsue_bot") jarayon davomida bir
# marta olib, keshlab qo'yamiz - har bir skrinshot yuborilganda qayta
# so'rov yubormaslik uchun (username bot ishlab turgan davrda
# o'zgarmaydi).
_bot_username_cache: str | None = None


async def _get_bot_username(bot) -> str:
    global _bot_username_cache
    if _bot_username_cache is None:
        me = await bot.get_me()
        _bot_username_cache = me.username
    return _bot_username_cache


async def caption_with_bot_link(text: str, bot) -> str:
    """Skrinshot rasmi ostidagi matnga botning o'z havolasini
    (https://t.me/<username>) ham qo'shib beradi - shunda rasm
    boshqalarga forward/ulashilganda ham, uni ko'rgan odam qayerdan
    olinganini va botdan qanday foydalanishni biladi."""
    username = await _get_bot_username(bot)
    return f"{text}\n\n🤖 Bot: https://t.me/{username}"


def days_kb(prefix: str = "free") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for code, label in DAYS:
        b.button(text=label, callback_data=f"{prefix}:day:{code}")
    b.adjust(1)
    b.row(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data=f"{prefix}:home"))
    return b.as_markup()


def periods_kb(prefix: str = "free") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n, t in PERIOD_TIMES.items():
        b.button(text=f"{n}-para ({t})", callback_data=f"{prefix}:period:{n}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data=f"{prefix}:home"))
    return b.as_markup()

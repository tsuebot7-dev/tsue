"""
Dars oldidan eslatma yuborish.

Har bir dars boshlanishidan REMINDER_MINUTES_BEFORE daqiqa oldin
(standart 10) xabar yuboriladi, masalan dushanba 14:20 da:

    📚 KI-900/26
    ⏰ 14:30 da Fizika fanidan 5/402 xonada Karimov Sh., darsga kech qolmang!

Kimlarga yuboriladi:
  - foydalanuvchining "Mening guruhim"i bo'yicha,
  - foydalanuvchi saqlab qo'ygan guruh jadvallari bo'yicha,
  - avtomatik jadval ulangan Telegram guruhlarga.

Foydalanuvchi eslatmalarni xabar ostidagi tugma yoki /eslatma buyrug'i
orqali o'chirib/yoqib qo'yishi mumkin. Telegram guruhda buni faqat
guruh adminlari qila oladi.

Jadval qayerdan olinadi: foydalanuvchi jadvalni saqlaganda (yoki
"Mening guruhim" qilganda, yoki guruhga avtomatik jadval ulaganda)
guruhning haftalik darslari TSUE saytidan bir marta olinib, bazaga
(schedule_snapshots) matn ko'rinishida yoziladi. Eslatmalar FAQAT shu
saqlangan nusxadan yuboriladi - jadval qaytadan saqlanmaguncha (yoki
admin paneldan qayta yuklanmaguncha) saytga murojaat qilinmaydi.

Bot soati: admin paneldagi "Kalendar" bo'limida bot uchun boshqa vaqt
belgilash mumkin (masalan sinov uchun "2026-10-05 12:00"). Shunda
eslatmalar shu belgilangan vaqtdan boshlab yuradigan soat bo'yicha
yuboriladi. Farq "clock_offset_seconds" sozlamasida saqlanadi.
"""

import asyncio
import datetime
import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import config, db, timetable_data, ui
from .bot_instance import get_bot

logger = logging.getLogger(__name__)
router = Router(name="reminders")

TASHKENT_OFFSET = datetime.timedelta(hours=5)
CHECK_INTERVAL_SECONDS = 20
SEND_DELAY_SECONDS = 0.05  # Telegram limitlariga tushmaslik uchun xabarlar orasida


CLOCK_OFFSET_KEY = "clock_offset_seconds"
SENT_KEY_PREFIX = "reminder_sent:"

# Fon vazifalari GC tomonidan o'chirib yuborilmasligi uchun.
_background_tasks: set = set()
# Bu jarayonda nusxasi yaratishga urinib ko'rilgan havolalar - sayt
# ishlamay qolsa, har 20 soniyada qayta-qayta urinmaslik uchun.
_snapshot_attempted: set = set()


def real_tashkent_now() -> datetime.datetime:
    return datetime.datetime.utcnow() + TASHKENT_OFFSET


async def bot_now() -> datetime.datetime:
    """Eslatmalar uchun "hozirgi vaqt" (Toshkent). Admin paneldan
    kalendar sozlangan bo'lsa, shunga ko'ra siljigan."""
    try:
        offset = float(await db.get_setting(CLOCK_OFFSET_KEY, "0") or 0)
    except ValueError:
        offset = 0
    return real_tashkent_now() + datetime.timedelta(seconds=offset)


async def set_bot_clock(target: datetime.datetime | None):
    """Bot soatini `target` vaqtga o'rnatadi (None - haqiqiy vaqtga
    qaytaradi). Avval yuborilgan eslatma belgilari tozalanadi, shunda
    yangi vaqt bo'yicha eslatmalar qaytadan yuboriladi."""
    offset = 0 if target is None else (target - real_tashkent_now()).total_seconds()
    await db.set_setting(CLOCK_OFFSET_KEY, str(round(offset)))
    await db.delete_settings_with_prefix(SENT_KEY_PREFIX)


# ================================================================ #
# Jadvalni matn ko'rinishida saqlash
# ================================================================ #

async def snapshot_schedule(url: str, name: str, force_download: bool = False) -> bool:
    """Guruhning haftalik darslarini (yuklangan TSUE jadvalidan) bazaga yozadi."""
    if force_download or not timetable_data.is_loaded():
        if not await timetable_data.refresh(force=force_download):
            return False
    parsed = timetable_data.parse_url(url)
    lessons = timetable_data.lessons_for_url(url) if parsed and parsed[0] == "class" else None
    if lessons is None:
        return False
    await db.set_schedule_snapshot(url, name, lessons)
    logger.info("Jadval matn ko'rinishida saqlandi: %s (%s ta dars).", name, len(lessons))
    return True


def snapshot_in_background(url: str, name: str):
    """Foydalanuvchini kuttirmaslik uchun fonda saqlaydi."""
    async def _run():
        try:
            await snapshot_schedule(url, name)
        except Exception:
            logger.exception("Jadvalni matn ko'rinishida saqlab bo'lmadi: %s", url)

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def resnapshot_all() -> tuple[int, int]:
    """Eslatma oluvchilarning barcha jadvallarini saytdan qayta yuklaydi
    (admin panel tugmasi). (muvaffaqiyatli, jami) qaytaradi."""
    urls = {t["url"]: t["name"] for t in await db.get_reminder_targets()}
    if not await timetable_data.refresh(force=True):
        return 0, len(urls)
    ok = 0
    for url, name in urls.items():
        if await snapshot_schedule(url, name):
            ok += 1
    return ok, len(urls)


# ================================================================ #
# Xabar matni
# ================================================================ #

def _lesson_line(lesson: dict, lang: str) -> str:
    start = html.escape(lesson["start"])
    subject = html.escape(lesson["subject"] or "—")
    rooms = html.escape(", ".join(lesson["rooms"]))
    teachers = html.escape(", ".join(lesson["teachers"]))
    subgroup = html.escape(lesson.get("subgroup") or "")

    if lang == "ru":
        parts = [f"⏰ В <b>{start}</b> — <b>{subject}</b>"]
        if rooms:
            parts.append(f"аудитория <b>{rooms}</b>")
        if teachers:
            parts.append(f"преподаватель <b>{teachers}</b>")
        line = ", ".join(parts)
    else:
        line = f"⏰ <b>{start}</b> da <b>{subject}</b> fanidan"
        if rooms:
            line += f" <b>{rooms}</b> xonada"
        if teachers:
            line += f" <b>{teachers}</b>"
    if subgroup:
        line += f" ({subgroup})"
    return line


def build_reminder_text(group_name: str, lessons: list, lang: str, url: str = "") -> str:
    title = "Напоминание о паре" if lang == "ru" else "Dars eslatmasi"
    lines = [f"📚 <b>{title}</b> · {ui.link(group_name, url)}", ""]
    lines += [_lesson_line(l, lang) for l in lessons]
    if lang == "ru":
        lines[-1] += ". Не опаздывайте на занятие!"
    else:
        lines[-1] += ", darsga kech qolmang!"
    return "\n".join(lines)


def _off_button_kb(lang: str) -> InlineKeyboardMarkup:
    text = "🔕 Отключить напоминания" if lang == "ru" else "🔕 Eslatmalarni o'chirish"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data="rem:off")]])


# ================================================================ #
# Yuborish tsikli
# ================================================================ #

async def _send(target: dict, text: str) -> bool:
    bot = get_bot()
    markup = None if target["is_group"] else _off_button_kb(target["language"])
    for _ in range(2):
        try:
            await bot.send_message(target["chat_id"], text, reply_markup=markup)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            if isinstance(e, TelegramBadRequest) and "chat not found" not in str(e).lower():
                logger.warning("Eslatma yuborilmadi (chat_id=%s): %s", target["chat_id"], e)
                return False
            # Foydalanuvchi botni bloklagan yoki bot guruhdan chiqarilgan -
            # har daqiqada qayta urinmaslik uchun eslatmani o'chirib qo'yamiz.
            logger.info("Eslatma yuborilmadi (chat_id=%s): %s. Eslatma o'chirildi.", target["chat_id"], e)
            if target["is_group"]:
                await db.set_group_reminders(target["chat_id"], False)
            else:
                await db.set_user_reminders(target["chat_id"], False)
            return False
        except Exception:
            logger.exception("Eslatma yuborishda xatolik: chat_id=%s", target["chat_id"])
            return False
    return False


async def _check_and_send_once():
    now = await bot_now()
    today = now.date()
    window = datetime.timedelta(minutes=config.REMINDER_MINUTES_BEFORE)
    snapshots: dict[str, list | None] = {}

    for target in await db.get_reminder_targets():
        url = target["url"]
        if url not in snapshots:
            snap = await db.get_schedule_snapshot(url)
            if snap is None and url not in _snapshot_attempted:
                # Yangi funksiyadan oldin saqlangan jadval - bir marta
                # avtomatik matn ko'rinishiga o'giramiz.
                _snapshot_attempted.add(url)
                if await snapshot_schedule(url, target["name"]):
                    snap = await db.get_schedule_snapshot(url)
            snapshots[url] = snap["lessons"] if snap else None
        weekly = snapshots[url]
        if not weekly:
            continue

        lessons = timetable_data.lessons_for_day(weekly, today)
        by_start: dict[str, list] = {}
        for lesson in lessons:
            by_start.setdefault(lesson["start"], []).append(lesson)

        for start, group in by_start.items():
            hour, minute = map(int, start.split(":"))
            start_dt = datetime.datetime.combine(today, datetime.time(hour, minute))
            if not (datetime.timedelta(0) < start_dt - now <= window):
                continue

            # Bazada saqlanadi - bot qayta ishga tushsa ham bir dars uchun
            # ikki marta yuborilmaydi.
            entity = timetable_data.parse_url(url)
            sent_key = f"{SENT_KEY_PREFIX}{target['chat_id']}:{entity[1] if entity else url}"
            sent_value = f"{today.isoformat()} {start}"
            if await db.get_setting(sent_key) == sent_value:
                continue

            text = build_reminder_text(target["name"], group, target["language"], url)
            await db.set_setting(sent_key, sent_value)
            await _send(target, text)
            await asyncio.sleep(SEND_DELAY_SECONDS)


async def run_reminders():
    logger.info("Dars oldidan eslatma yuboruvchi ishga tushdi (%s daqiqa oldin).", config.REMINDER_MINUTES_BEFORE)
    while True:
        try:
            await _check_and_send_once()
        except Exception:
            logger.exception("Eslatma tsiklida xatolik yuz berdi.")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


# ================================================================ #
# /eslatma buyrug'i va tugmalar
# ================================================================ #

def _settings_kb(enabled: bool) -> InlineKeyboardMarkup:
    if enabled:
        button = InlineKeyboardButton(text="🔕 O'chirish", callback_data="rem:off")
    else:
        button = InlineKeyboardButton(text="🔔 Yoqish", callback_data="rem:on")
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def _status_text(enabled: bool, is_group: bool) -> str:
    who = "guruhga" if is_group else "sizga"
    state = "✅ yoqilgan" if enabled else "🔕 o'chirilgan"
    return (
        f"🔔 <b>Dars eslatmalari</b>\n"
        f"Holat: {state}\n\n"
        f"Har bir dars boshlanishidan <b>{config.REMINDER_MINUTES_BEFORE} daqiqa</b> oldin "
        f"{who} fan, xona va o'qituvchi haqida xabar yuboriladi.\n\n"
        f"<i>Eslatma \"Mening guruhim\" va saqlangan guruh jadvallari bo'yicha keladi.</i>"
    )


async def _is_chat_admin(bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in ("creator", "administrator")


@router.message(Command("eslatma"), F.chat.type == "private")
async def cmd_reminders_private(message: Message):
    enabled = await db.get_user_reminders(message.from_user.id)
    text = _status_text(enabled, is_group=False)
    if not await db.get_default_group(message.from_user.id) and not await db.get_saved_schedules(message.from_user.id):
        text += (
            "\n\nℹ️ Eslatma olish uchun guruhingiz jadvalini oching va "
            "\"⭐ Mening guruhim\" yoki \"💾 Saqlab qo'yish\" tugmasini bosing."
        )
    await message.answer(text, reply_markup=_settings_kb(enabled))


@router.message(Command("eslatma"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_reminders_group(message: Message):
    enabled = await db.get_group_reminders(message.chat.id)
    if enabled is None:
        await message.answer("Bu guruhda avtomatik jadval hali sozlanmagan. Avval /start buyrug'ini yuboring.")
        return
    await message.answer(_status_text(enabled, is_group=True), reply_markup=_settings_kb(enabled))


@router.callback_query(F.data == "rem:menu")
async def reminders_menu(call: CallbackQuery):
    enabled = await db.get_user_reminders(call.from_user.id)
    await call.answer()
    await call.message.answer(_status_text(enabled, is_group=False), reply_markup=_settings_kb(enabled))


@router.callback_query(F.data.in_({"rem:on", "rem:off"}))
async def toggle_reminders(call: CallbackQuery):
    enabled = call.data == "rem:on"
    is_group = call.message.chat.type in ("group", "supergroup")

    if is_group:
        if not await _is_chat_admin(call.bot, call.message.chat.id, call.from_user.id):
            await call.answer("Buni faqat guruh adminlari o'zgartira oladi.", show_alert=True)
            return
        await db.set_group_reminders(call.message.chat.id, enabled)
    else:
        await db.set_user_reminders(call.from_user.id, enabled)

    await call.answer("🔔 Eslatmalar yoqildi." if enabled else "🔕 Eslatmalar o'chirildi.")
    if (call.message.text or "").startswith("📚 Dars eslatmasi") or (call.message.text or "").startswith("📚 Напоминание"):
        # Tugma eslatma xabarining o'zida bosilgan - eslatma matnini
        # saqlab, faqat tugmani almashtiramiz.
        try:
            await call.message.edit_reply_markup(reply_markup=_settings_kb(enabled))
        except TelegramBadRequest:
            pass
        return
    try:
        await call.message.edit_text(_status_text(enabled, is_group), reply_markup=_settings_kb(enabled))
    except TelegramBadRequest:
        await call.message.answer(_status_text(enabled, is_group), reply_markup=_settings_kb(enabled))

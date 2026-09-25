"""
Foydalanuvchi botga ERKIN MATN yozganda YOKI OVOZLI XABAR yuborganda
(masalan "AT-75 guruh jadvalini topib ber", "Fanonchiyev domlani
jadvalini topib ber" yoki "menga dushanba kuniga bosh xona topib
ber"), shu matnni OpenAI orqali (bot/ai_router.py) tahlil qilib,
botning MAVJUD uchta buyrug'idan (guruh jadvali / o'qituvchi jadvali /
bo'sh xona qidirish) biriga aylantiradigan handler.

MUHIM QOIDA (foydalanuvchi talabiga ko'ra - texnik bo'limga yozilgan
xabarlarga AI javob yozib yubormasligi kerak):
  - Bu handler HAR DOIM, eng birinchi navbatda, xabarni (matn bo'lsa
    o'zini, ovozli bo'lsa - matnga aylantirilgan holini, aylantirib
    bo'lmasa ham shunchaki "ovozli xabar" belgisini) chat_messages
    jadvaliga "kiruvchi" sifatida yozadi - admin panelning Texnik
    bo'limida ko'rinadi, odam qo'lda javob bera oladi. Bu xatti-harakat
    AI integratsiyasidan MUSTAQIL - ai_router ishlamasa ham, xato
    bersa ham, "none" qaytarsa ham, xabar baribir yoziladi.
  - Shundan KEYINGINA, AI aniq uchta buyruqdan birini ANIQ tanigan
    holatdagina, QO'SHIMCHA ravishda o'sha natija (skrinshot/tugmalar)
    yuboriladi. Boshqa har qanday holatda (savol, salom, shikoyat,
    texnik muammo va h.k.) - hech qanday qo'shimcha AI-generatsiya
    qilingan matn YOZILMAYDI, xabar shunchaki odatdagidek "kiruvchi"
    sifatida qoladi va inson javob beradi.
  - Faqat shaxsiy chatlarda (guruh chatlarida emas) ishlaydi - guruh
    chatlaridagi funksiyalar (group_setup) o'zgarishsiz qoladi.
"""

import difflib
import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import ai_router, config, data_loader, db
from ..keyboards import after_result_kb, caption_with_bot_link, days_kb, loading_text, periods_kb
from ..screenshot import take_timetable_screenshot
from ..states import FreeRoomStates
from . import chat_log
from .free_rooms import DAY_LABELS, _room_list_text, buildings_kb, rooms_result_kb
from .teacher_search import search_teachers

router = Router(name="ai_intent")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Umumiy jadval yetkazish (guruh HAM, o'qituvchi HAM shu orqali)
# ---------------------------------------------------------------------

async def _deliver_schedule(
    bot, chat_id: int, user_id: int, feature: str, name: str, icon: str, event_name: str
):
    """Berilgan (guruh yoki o'qituvchi) nom uchun jadval skrinshotini
    shu chatga yuboradi. Message-context uchun mo'ljallangan (aniq bitta
    "call.message" yo'q, foydalanuvchi yozgan/aytgan oddiy xabar bor),
    shuning uchun bot.send_message/send_photo orqali ishlaydi."""
    url = data_loader.store.get_leaf_url(feature, name)
    if not url:
        await bot.send_message(chat_id, f"❌ \"{name}\" uchun havola topilmadi.")
        return

    status = await bot.send_message(chat_id, loading_text(name, url))
    try:
        png_path = await take_timetable_screenshot(url)
        photo = FSInputFile(png_path)
        caption = await caption_with_bot_link(f"{icon} {name}\n🔗 {url}", bot)
        await bot.send_photo(
            chat_id, photo, caption=caption, reply_markup=after_result_kb(prefix="nav")
        )
        png_path.unlink(missing_ok=True)
        await db.log_event(user_id, event_name, name)
        try:
            await status.delete()
        except Exception:
            pass
    except Exception as e:
        logger.exception("AI orqali %s jadvali skrinshotida xatolik: %s", feature, name)
        await db.log_error(f"ai_{feature}_screenshot", f"{name} ({url}): {e}")
        try:
            await status.edit_text(f"❌ Jadvalni yuklab bo'lmadi. Xatolik: {e}")
        except Exception:
            await bot.send_message(chat_id, f"❌ Jadvalni yuklab bo'lmadi. Xatolik: {e}")


# ---------------------------------------------------------------------
# Guruh jadvali
# ---------------------------------------------------------------------

def _base_code(key: str) -> str:
    """"AT-75/25" -> "AT-75" (guruh kodining yil/qism qo'shimchasisiz
    asosiy qismi)."""
    return key.split("/", 1)[0].upper()


def _compact(s: str) -> str:
    return "".join(ch for ch in s.upper() if ch.isalnum())


def _find_group_matches(query: str, limit: int = 8) -> list:
    """AI aniqlagan (yoki foydalanuvchi to'g'ridan-to'g'ri yozgan) guruh
    nomini haqiqiy guruhlar.json kalitlariga moslashtirib topadi.
    Faqat "-" belgisi bor kalitlar (haqiqiy guruh yozuvlari, fakultet/kurs
    "sarlavha" yozuvlari emas) orasidan qidiradi."""
    flat = data_loader.store.guruhlar_flat
    keys = [k for k in flat.keys() if "-" in k]
    q = (query or "").strip().upper().replace(" ", "")
    if not q or not keys:
        return []

    # 1) to'liq mos (katta-kichik harf farqisiz, qo'shimchasi bilan ham)
    for k in keys:
        if k.upper() == q:
            return [k]

    # 2) bazaviy kod to'liq mos (masalan "AT-75" -> "AT-75/25", "AT-75/24r")
    exact_base = sorted(k for k in keys if _base_code(k) == q)
    if exact_base:
        return exact_base[:limit]

    # 3) bazaviy kod shu bilan boshlanadi
    prefix_base = sorted(k for k in keys if _base_code(k).startswith(q))
    if prefix_base:
        return prefix_base[:limit]

    # 4) belgilarni "tozalab" (bo'sh joy/chiziqchasiz) moslashtirish
    qc = _compact(q)
    if qc:
        fuzzy = sorted(
            k for k in keys
            if (kc := _compact(_base_code(k))) and (kc.startswith(qc) or qc.startswith(kc))
        )
        if fuzzy:
            return fuzzy[:limit]

    # 5) difflib orqali eng yaqinlarini topish (yengil imlo xatolariga
    #    chidamli, masalan foydalanuvchi bittа harfni noto'g'ri yozgan
    #    bo'lsa)
    base_codes = sorted({_base_code(k) for k in keys})
    close = difflib.get_close_matches(q, base_codes, n=limit, cutoff=0.6)
    if close:
        result, seen = [], set()
        for c in close:
            for k in keys:
                if _base_code(k) == c and k not in seen:
                    result.append(k)
                    seen.add(k)
        return result[:limit]

    return []


async def _handle_group_schedule(message: Message, group_name: str):
    matches = _find_group_matches(group_name)

    if not matches:
        # Bu AI-generatsiya qilingan "javob" emas - oldindan tayyorlangan,
        # doim bir xil matn (fail-safe qoida shu tufayli buzilmaydi).
        await message.answer(
            f"❌ \"{group_name}\" nomli guruh topilmadi. Guruh kodini to'g'ri "
            f"yozganingizga ishonch hosil qiling (masalan: AT-75) yoki "
            f"\"🎓 Talabalar\" bo'limi orqali qidiring."
        )
        return

    if len(matches) == 1:
        await _deliver_schedule(
            message.bot, message.chat.id, message.from_user.id,
            "guruh", matches[0], "🎓", "view_guruh_ai",
        )
        return

    b = InlineKeyboardBuilder()
    for name in matches:
        b.button(text=name, callback_data=f"ai_guruh_pick:{name}")
    b.adjust(1)
    b.row(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="nav:home"))
    await message.answer(
        f"🔍 \"{group_name}\" bo'yicha bir nechta guruh topildi, birini tanlang:",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.startswith("ai_guruh_pick:"))
async def pick_ai_group(call: CallbackQuery):
    name = call.data.split(":", 1)[1]
    await call.answer("⏳ Jadval yuklanmoqda...")
    try:
        await call.message.delete()
    except Exception:
        pass
    await _deliver_schedule(
        call.bot, call.message.chat.id, call.from_user.id, "guruh", name, "🎓", "view_guruh_ai"
    )


# ---------------------------------------------------------------------
# O'qituvchi jadvali (teacher_search.py dagi moslashtirilgan qidiruvni
# qayta ishlatadi, o'z alohida mantig'ini yozmaydi)
# ---------------------------------------------------------------------

async def _handle_teacher_schedule(message: Message, teacher_name: str):
    matches = search_teachers(teacher_name, limit=8)

    if not matches:
        await message.answer(
            f"❌ \"{teacher_name}\" ismli o'qituvchi topilmadi. Ism-familiyani "
            f"to'g'riroq yozib ko'ring yoki \"👨‍🏫 O'qituvchilar\" bo'limi "
            f"orqali qidiring."
        )
        return

    if len(matches) == 1:
        await _deliver_schedule(
            message.bot, message.chat.id, message.from_user.id,
            "ustoz", matches[0], "👨‍🏫", "view_ustoz_ai",
        )
        return

    b = InlineKeyboardBuilder()
    for name in matches:
        b.button(text=name, callback_data=f"ai_ustoz_pick:{name}")
    b.adjust(1)
    b.row(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="nav:home"))
    await message.answer(
        f"🔍 \"{teacher_name}\" bo'yicha bir nechta o'qituvchi topildi, birini tanlang:",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.startswith("ai_ustoz_pick:"))
async def pick_ai_teacher(call: CallbackQuery):
    name = call.data.split(":", 1)[1]
    await call.answer("⏳ Jadval yuklanmoqda...")
    try:
        await call.message.delete()
    except Exception:
        pass
    await _deliver_schedule(
        call.bot, call.message.chat.id, call.from_user.id, "ustoz", name, "👨‍🏫", "view_ustoz_ai"
    )


# ---------------------------------------------------------------------
# Bo'sh xona qidiruvi - mavjud FreeRoomStates oqimiga ulash.
#
# AI kun/bino/paraning ISTALGAN kombinatsiyasini (hattoki barchasi
# noma'lum bo'lsa ham - masalan foydalanuvchi shunchaki "bo'sh xona
# topib ber" desa) aniqlashi mumkin. Quyidagi funksiya har bir holatni
# mavjud oqimning tegishli bosqichiga to'g'ridan-to'g'ri ulaydi.
# ---------------------------------------------------------------------

def _ai_buildings_kb_for_day():
    """Kun AVVAL ma'lum bo'lgan holatda bino tanlash klaviaturasi -
    mavjud "free:bino:" handleri buni ishlata olmaydi, chunki u
    tanlangandan keyin YANA kun so'raydi (aifree:bino: alohida
    handleriga qarang)."""
    b = InlineKeyboardBuilder()
    for name in data_loader.store.buildings():
        label = name if not name[0].isdigit() else f"{name}-bino"
        b.button(text=f"🏢 {label}", callback_data=f"aifree:bino:{name}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="free:home"))
    return b.as_markup()


async def _handle_free_room(message: Message, state: FSMContext, intent: dict):
    day = intent.get("day")
    building = intent.get("building")
    period = intent.get("period")

    # 1) Hammasi ma'lum - natijani to'g'ridan-to'g'ri ko'rsatamiz.
    if day and building and period:
        rooms = data_loader.store.free_rooms(building, day, period)
        await db.log_event(message.from_user.id, "free_rooms_search_ai", f"{building}/{day}/{period}")
        await state.update_data(building=building, day=day, period=period, rooms=rooms)
        await state.set_state(FreeRoomStates.viewing_rooms)

        text = _room_list_text(building, day, period, rooms)
        if rooms:
            kb = rooms_result_kb(rooms)
        else:
            b = InlineKeyboardBuilder()
            b.button(text="🔁 Boshqa vaqt / bino", callback_data="menu:free")
            b.button(text="🏠 Bosh menyu", callback_data="free:home")
            b.adjust(1)
            kb = b.as_markup()
        await message.answer(text, reply_markup=kb)
        return

    # 2) Kun va bino ma'lum, para noma'lum - para tanlashni so'raymiz.
    if day and building:
        await state.update_data(building=building, day=day)
        await state.set_state(FreeRoomStates.choosing_period)
        label = building if not building[0].isdigit() else f"{building}-bino"
        await message.answer(
            f"🏢 {label}, {DAY_LABELS.get(day, day)}\n\nEndi darsni (paraga) tanlang:",
            reply_markup=periods_kb(prefix="free"),
        )
        return

    # 3) Faqat kun ma'lum (bino yo'q) - bino tanlashni so'raymiz.
    if day and not building:
        await state.update_data(day=day)
        await state.set_state(FreeRoomStates.choosing_building)
        await message.answer(
            f"📅 {DAY_LABELS.get(day, day)}\n\nQaysi binoda bo'sh xona qidiraylik?",
            reply_markup=_ai_buildings_kb_for_day(),
        )
        return

    # 4) Faqat bino ma'lum (kun yo'q) - kun tanlashni so'raymiz. Bu xuddi
    #    "free_rooms.py"dagi oddiy "bino tanlandi" bosqichi bilan bir xil,
    #    shuning uchun mavjud "free:day:" handleri buni to'g'ridan-to'g'ri
    #    davom ettira oladi.
    if building and not day:
        await state.update_data(building=building)
        await state.set_state(FreeRoomStates.choosing_day)
        label = building if not building[0].isdigit() else f"{building}-bino"
        await message.answer(
            f"🏢 {label}\n\nEndi kunni tanlang:",
            reply_markup=days_kb(prefix="free"),
        )
        return

    # 5) Hech narsa ma'lum emas (masalan shunchaki "bo'sh xona topib
    #    ber") - "🟢 Bo'sh xonalarni topish" tugmasi bosilgandagi bilan
    #    AYNAN bir xil, avval binoni so'raymiz.
    buildings = data_loader.store.buildings()
    if not buildings:
        await message.answer(
            "Hozircha bo'sh xonalar ma'lumoti topilmadi. Iltimos, keyinroq "
            "qayta urinib ko'ring."
        )
        return
    await state.set_state(FreeRoomStates.choosing_building)
    await message.answer(
        "🟢 Bo'sh xonalarni topish\n\nAvval binoni tanlang:",
        reply_markup=buildings_kb(),
    )


@router.callback_query(FreeRoomStates.choosing_building, F.data.startswith("aifree:bino:"))
async def ai_choose_building(call: CallbackQuery, state: FSMContext):
    building = call.data.split(":", 2)[2]
    data = await state.get_data()
    day = data.get("day")
    if not day:
        await call.answer("Sessiya eskirgan, qaytadan urinib ko'ring.", show_alert=True)
        return

    await state.update_data(building=building)
    await state.set_state(FreeRoomStates.choosing_period)
    label = building if not building[0].isdigit() else f"{building}-bino"
    await call.message.edit_text(
        f"🏢 {label}, {DAY_LABELS.get(day, day)}\n\nEndi darsni (paraga) tanlang:",
        reply_markup=periods_kb(prefix="free"),
    )
    await call.answer()


# ---------------------------------------------------------------------
# Umumiy dispatch (matn HAM, ovozli xabardan matnga aylantirilgan HAM
# shu orqali bajariladi - ikkalasi ham bir xil niyat aniqlash va
# bajarish mantig'idan foydalanadi)
# ---------------------------------------------------------------------

async def _dispatch_intent(message: Message, state: FSMContext, text: str):
    try:
        intent = await ai_router.classify_intent(text)
    except Exception:
        logger.exception("AI niyat aniqlashda kutilmagan xatolik")
        intent = None

    if not intent:
        # AI o'chirilgan, xato bergan yoki uchala buyruqdan birortasiga
        # ham mos kelmadi (masalan texnik bo'limga savol) - hech qanday
        # qo'shimcha (AI-generatsiya qilingan) xabar YOZILMAYDI.
        return

    kind = intent.get("intent")
    if kind == "group_schedule":
        await _handle_group_schedule(message, intent["group_name"])
    elif kind == "teacher_schedule":
        await _handle_teacher_schedule(message, intent["teacher_name"])
    elif kind == "free_room":
        await _handle_free_room(message, state, intent)


# ---------------------------------------------------------------------
# Kirish nuqtalari: erkin MATN va OVOZLI xabar
# ---------------------------------------------------------------------

@router.message(StateFilter(None), F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def handle_free_text(message: Message, state: FSMContext):
    # HAR DOIM avval - oldingi (AI'siz) xatti-harakat to'liq saqlanadi:
    # xabar chat_messages jadvaliga yoziladi, Texnik bo'lim uni ko'radi.
    await chat_log.log_incoming_text(message)

    text = (message.text or "").strip()
    if not text:
        return

    await _dispatch_intent(message, state, text)


@router.message(StateFilter(None), F.chat.type == "private", F.voice)
async def handle_voice_message(message: Message, state: FSMContext):
    """Ovozli xabarni OpenAI Whisper orqali matnga aylantirib, xuddi
    yozma xabar kabi ishlaydi. OPENAI_API_KEY sozlanmagan yoki
    transkripsiya muvaffaqiyatsiz bo'lsa - xabar baribir chat tarixiga
    yoziladi (Texnik bo'lim ko'ra oladi), lekin hech qanday qo'shimcha
    AI-javob yuborilmaydi (xuddi matnli xabardagi fail-safe qoida
    kabi)."""
    text = None
    if config.OPENAI_API_KEY:
        try:
            audio_buf = await message.bot.download(message.voice)
            audio_bytes = audio_buf.read() if audio_buf else b""
            text = await ai_router.transcribe_voice(audio_bytes, filename="voice.ogg")
        except Exception:
            logger.exception("Ovozli xabarni yuklab/matnga aylantirishda xatolik")
            text = None

    # HAR DOIM - matnga aylantirilgan holida (muvaffaqiyatli bo'lsa) yoki
    # oddiy belgi bilan (bo'lmasa), Texnik bo'lim ko'rishi uchun yoziladi.
    await chat_log.log_incoming_voice(message, text)

    if not text:
        return

    await _dispatch_intent(message, state, text)

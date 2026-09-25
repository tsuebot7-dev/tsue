"""
"O'qituvchilar" bo'limi endi menyu bo'ylab yurish emas, balki
QIDIRUV orqali ishlaydi - chunki o'qituvchilar soni juda ko'p (3000
gacha ID) va ular orasida tabiiy "fakultet" guruhlanishi yo'q.

Qidiruv moslashuvchan (fuzzy): foydalanuvchi "Abdullayeva Dilbar" deb
yozsa, natijada:
  - "Abdullayeva D" (qisqartirilgan ism) ham chiqadi
  - "Abdullayeva Dilber" (biroz boshqacha imlo) ham chiqadi
Bunga ikki qoida bilan erishiladi:
  1) Agar so'z bitta harfdan iborat bo'lsa (initsial), faqat birinchi
     harf mos kelishi kifoya qiladi.
  2) Aks holda, so'zlar prefiks sifatida yoki difflib orqali "yetarlicha
     o'xshash" (ratio >= 0.82) bo'lsa mos deb hisoblanadi.

MUHIM: bu chegara (0.82) ataylab yuqori qilib qo'yilgan - avval 0.75
edi, lekin bu chegarada masalan "Abdug'aniyeva" so'roviga "Abdullayeva",
"Abdullayev" kabi UMUMAN BOSHQA familiyalar ham "o'xshash" deb chiqib
ketardi (ular faqat "Abdu-" bilan boshlanib, "-yeva" bilan tugashi
tasodifan yetarlicha o'xshashlik hosil qilardi). 0.82 chegarasi haqiqiy
imlo xatolariga (masalan "Dilbar"/"Dilber", "Yusupova"/"Yusufova",
"Rahimova"/"Raximova" - bularning barchasi ratio >= 0.85) hamon chidamli
qoladi, lekin umuman boshqa familiyalarni (ratio odatda <= 0.78) chiqarib
tashlaydi. Apostrof belgisining turli Unicode variantlari ('/ʻ/ʼ/'/')
ham solishtirishdan OLDIN bitta shaklga keltiriladi - aks holda faqat
apostrof belgisi boshqacha yozilgani uchun ratio pasayib, chegaradan
o'tolmay qolishi mumkin edi.
"""

import difflib
import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import data_loader, db
from ..keyboards import after_result_kb, caption_with_bot_link, loading_text
from ..screenshot import take_timetable_screenshot

router = Router(name="teacher_search")
logger = logging.getLogger(__name__)

_FUZZY_RATIO_THRESHOLD = 0.82

_APOSTROPHE_CHARS = "'‘’ʻʼ´`"
_APOSTROPHE_TABLE = {ord(ch): "'" for ch in _APOSTROPHE_CHARS}


class TeacherSearchStates(StatesGroup):
    waiting_query = State()


def _normalize_apostrophes(s: str) -> str:
    """Barcha apostrof/tutuq belgisi variantlarini ("'" "ʻ" "ʼ" "'" "'")
    bitta shaklga keltiradi, shunda ular difflib solishtiruvida haqiqiy
    imlo farqi sifatida hisoblanib, ratio'ni sun'iy pasaytirmaydi."""
    return s.translate(_APOSTROPHE_TABLE)


def _word_matches(query_word: str, name_word: str) -> bool:
    query_word = _normalize_apostrophes(query_word.lower())
    name_word = _normalize_apostrophes(name_word.lower().rstrip("."))
    if not query_word or not name_word:
        return False

    # Foydalanuvchi QIDIRUV so'zini initsial sifatida yozgan bo'lsa
    # (masalan "d"), faqat birinchi harf mos kelishi kifoya - bu esa
    # saqlangan to'liq so'zga ("Dilbar") ham, saqlangan initsialga
    # ("D.") ham mos tushishi kerak.
    if len(query_word) == 1:
        return name_word[0] == query_word[0]

    # Aksincha - foydalanuvchi TO'LIQ so'z yozgan, lekin saqlangan
    # ma'lumotda o'sha so'z o'rnida faqat initsial bor (masalan
    # "Abdurahmanov A." dagi "A."). Bunda faqat birinchi harf bir xil
    # bo'lishi DEYARLI HAR DOIM to'g'ri chiqib, umuman aloqasi yo'q
    # odamlarni ham natijaga qo'shib yuborardi - shu sabab bu holat mos
    # kelmadi deb hisoblanadi (kerak bo'lsa, boshqa so'z/familiya orqali
    # baribir topiladi).
    if len(name_word) == 1:
        return False

    if name_word.startswith(query_word) or query_word.startswith(name_word):
        return True

    # Yengil imlo farqiga chidamli (masalan "dilbar" vs "dilber"), lekin
    # umuman boshqa familiya/ismlarni chiqarib tashlaydigan darajada
    # qattiq chegara bilan (yuqoridagi izohga qarang).
    ratio = difflib.SequenceMatcher(None, query_word, name_word).ratio()
    return ratio >= _FUZZY_RATIO_THRESHOLD


def teacher_matches(teacher_name: str, query: str) -> bool:
    query_words = [w for w in query.replace(",", " ").lower().split() if w]
    name_words = [w for w in teacher_name.replace(",", " ").lower().split() if w]
    if not query_words:
        return False
    for qw in query_words:
        if not any(_word_matches(qw, nw) for nw in name_words):
            return False
    return True


def search_teachers(query: str, limit: int = 15) -> list:
    flat = data_loader.store.ustozlar_flat
    results = [name for name in flat.keys() if teacher_matches(name, query)]
    results.sort()
    return results[:limit]


@router.callback_query(F.data == "menu:ustoz")
async def start_teacher_search(call: CallbackQuery, state: FSMContext):
    await state.set_state(TeacherSearchStates.waiting_query)
    from ..keyboards import InlineKeyboardButton

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="nav:home"))
    await call.message.edit_text(
        "👨‍🏫 O'qituvchilar\n\n"
        "Qidirmoqchi bo'lgan o'qituvchining ism-familiyasini yozib yuboring "
        "(masalan: <i>Abdullayeva Dilbar</i>):",
        reply_markup=b.as_markup(),
    )
    await call.answer()


@router.message(StateFilter(TeacherSearchStates.waiting_query), F.text)
async def handle_teacher_query(message: Message, state: FSMContext):
    query = message.text.strip()
    if not query:
        return

    results = search_teachers(query)

    if not results:
        await message.answer(
            "❌ Hech kim topilmadi. Boshqa nom bilan qayta urinib ko'ring, "
            "yoki ism-familiyani to'liqroq yozing."
        )
        return

    b = InlineKeyboardBuilder()
    for name in results:
        b.button(text=name, callback_data=f"ustoz_pick:{name}")
    b.adjust(1)
    from ..keyboards import InlineKeyboardButton
    b.row(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="nav:home"))

    await message.answer(
        f"🔍 \"{query}\" bo'yicha {len(results)} ta natija topildi:",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.startswith("ustoz_pick:"))
async def pick_teacher(call: CallbackQuery, state: FSMContext):
    name = call.data.split(":", 1)[1]
    url = data_loader.store.get_leaf_url("ustoz", name)
    if not url:
        await call.answer("Havola topilmadi.", show_alert=True)
        return

    await state.clear()
    await call.answer("⏳ Jadval yuklanmoqda...")
    loading_msg = await call.message.edit_text(loading_text(name, url))

    try:
        png_path = await take_timetable_screenshot(url)
        photo = FSInputFile(png_path)
        caption = await caption_with_bot_link(f"👨‍🏫 {name}\n🔗 {url}", call.bot)
        await call.message.answer_photo(
            photo,
            caption=caption,
            reply_markup=after_result_kb(prefix="nav"),
        )
        png_path.unlink(missing_ok=True)
        await db.log_event(call.from_user.id, "view_ustoz", name)
        try:
            await loading_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.exception("O'qituvchi skrinshotida xatolik")
        await db.log_error("screenshot_ustoz", f"{name}: {e}")
        await call.message.answer(
            f"❌ Jadvalni yuklab bo'lmadi. Xatolik: {e}",
            reply_markup=after_result_kb(prefix="nav"),
        )

"""
Foydalanuvchi dars jadvalini (o'z guruhining jadvalini) BIRINCHI
marta ko'rgandan keyin, xizmatni 1-5 yulduz bilan baholashni so'rab,
avtomatik xabar yuboradi - FAQAT BIR MARTA (keyingi safar jadval
ko'rsa ham qayta so'ralmaydi).

Xabar tagida 6 ta inline tugma bo'ladi:
  - 1 qatorda 5 ta ("parallel"): 1⭐️ 2⭐️ 3⭐️ 4⭐️ 5⭐️
  - ular ostida yana 1 ta ("ketma-ket"): 🛠 Texnik bo'lim bilan bog'lanish

"Texnik bo'lim bilan bog'lanish" tugmasi alohida chat/forma ochmaydi -
bot allaqachon foydalanuvchi yozgan har qanday oddiy xabarni
(bot/handlers/chat_log.py orqali) qabul qilib, admin panelning
"Foydalanuvchilar" bo'limida ko'rsatadi, shu yerdan admin javob
yozishi mumkin. Shuning uchun tugma shunchaki foydalanuvchiga "shu
yerga yozing" deb eslatib qo'yadi.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import db

router = Router(name="rating")
logger = logging.getLogger(__name__)

RATING_TEXT = (
    "⭐ Xizmatimizdan mamnunmisiz?\n\n"
    "Botdan foydalanish tajribangizni 1 dan 5 yulduzgacha baholab bering — "
    "bu bizga xizmatni yanada yaxshilashda yordam beradi!"
)

SUPPORT_TEXT = (
    "💬 Savolingiz yoki murojaatingizni shu yerga (shu chatga) yozib qoldiring — "
    "tez orada mas'ul xodim siz bilan bog'lanadi."
)


def rating_kb():
    """5 ta yulduz tugmasi bir qatorda ('parallel'), ularning ostida
    esa 1 ta 'Texnik bo'lim bilan bog'lanish' tugmasi ('ketma-ket')."""
    b = InlineKeyboardBuilder()
    for n in range(1, 6):
        b.button(text=f"{n}⭐️", callback_data=f"rate:star:{n}")
    b.adjust(5)
    b.row(InlineKeyboardButton(text="🛠 Texnik bo'lim bilan bog'lanish", callback_data="rate:support"))
    return b.as_markup()


def support_only_kb():
    """Baholangandan keyin xabar ostida qoladigan tugma - endi faqat
    bog'lanish imkoniyati."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🛠 Texnik bo'lim bilan bog'lanish", callback_data="rate:support"))
    return b.as_markup()


async def maybe_prompt_rating(bot, user_id: int, chat_id: int):
    """Dars jadvali muvaffaqiyatli ko'rsatilgandan keyin chaqiriladi.
    Foydalanuvchi ilgari so'ralmagan bo'lsa, baholash xabarini
    yuboradi. Xatolik (masalan bot bloklangan) butun oqimni
    to'xtatmasligi uchun chaqiruvchi joyda try/except bilan
    o'ralishi kerak."""
    should_prompt = await db.mark_rating_prompted(user_id)
    if not should_prompt:
        return
    await bot.send_message(chat_id, RATING_TEXT, reply_markup=rating_kb())


@router.callback_query(F.data.startswith("rate:star:"))
async def handle_star_rating(call: CallbackQuery):
    try:
        n = int(call.data.split(":", 2)[2])
    except ValueError:
        await call.answer()
        return
    if n < 1 or n > 5:
        await call.answer()
        return

    await db.set_rating(call.from_user.id, n)
    await db.log_event(call.from_user.id, "rating", str(n))

    try:
        await call.message.edit_text(
            f"🙏 Rahmat! Siz xizmatimizni {n} ⭐ deb baholadingiz.",
            reply_markup=support_only_kb(),
        )
    except Exception:
        pass
    await call.answer("Rahmat!")


@router.callback_query(F.data == "rate:support")
async def handle_support_contact(call: CallbackQuery):
    try:
        await call.message.answer(SUPPORT_TEXT)
    except Exception:
        logger.exception("Texnik bo'lim xabarini yuborishda xatolik")
    await call.answer()

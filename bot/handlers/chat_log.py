"""
Foydalanuvchi botga yozgan har qanday oddiy matnni (buyruq bo'lmagan)
jurnalga yozib boradi - shaxsiy chat bo'lsa chat_messages jadvaliga
("Foydalanuvchilar" bo'limida ko'rinadi), GURUH chati bo'lsa esa
group_chat_messages jadvaliga (admin panelning "Guruhlar" bo'limidagi
"💬 Yozishma" sahifasida ko'rinadi, kim yozgani bilan birga).

MUHIM: bu handler routers ro'yxatida ENG OXIRIDA turishi kerak, aks
holda boshqa (buyruq/FSM) handlerlardan oldin ishlab, ularga
xalaqit berishi mumkin.

ESLATMA (Telegram "privacy mode"): agar botning @BotFather'dagi
Group Privacy sozlamasi yoqilgan (standart holat) bo'lsa, bot guruhda
faqat buyruqlarni, o'ziga yozilgan javoblarni va o'zi mention
qilingan xabarlarni oladi - guruhdagi HAR BIR xabarni emas. Guruhdagi
TO'LIQ yozishmani ko'rish uchun @BotFather'da shu botga
"/setprivacy" -> "Disable" qilish kerak.
"""

from aiogram import F, Router
from aiogram.types import Message

from .. import db

router = Router(name="chat_log")


@router.message(F.text & ~F.text.startswith("/"))
async def log_incoming(message: Message):
    if message.chat.type == "private":
        await log_incoming_text(message)
    else:
        await log_incoming_group_text(message)


async def log_incoming_text(message: Message):
    await db.log_chat_message(message.from_user.id, "in", message.text)


async def log_incoming_group_text(message: Message):
    sender = message.from_user
    if sender:
        sender_name = sender.full_name or (f"@{sender.username}" if sender.username else str(sender.id))
        sender_user_id = sender.id
    else:
        sender_name = "Noma'lum"
        sender_user_id = None
    await db.log_group_chat_message(
        message.chat.id, "in", message.text,
        sender_user_id=sender_user_id, sender_name=sender_name,
    )


async def log_incoming_voice(message: Message, transcribed_text: str | None = None):
    """Ovozli xabarni ham chat tarixiga yozadi (ai_intent.py'dagi ovozli
    xabar handleridan chaqiriladi - shu tufayli AI matnga aylantirsa ham,
    aylantirmasa ham, Texnik bo'lim buni har doim ko'ra oladi).

    Agar OpenAI orqali matnga aylantirilgan bo'lsa, o'sha matn yoziladi
    (odam nima deyilganini o'qiy oladi); aks holda hech bo'lmasa ovozli
    xabar kelgani haqida belgi qoldiriladi."""
    if transcribed_text:
        text = f"🎤 (ovozli xabar): {transcribed_text}"
    else:
        text = "🎤 (ovozli xabar - matnga aylantirib bo'lmadi)"
    await db.log_chat_message(message.from_user.id, "in", text)

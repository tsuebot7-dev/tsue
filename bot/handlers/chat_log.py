"""
Foydalanuvchi botga yozgan har qanday oddiy matnni (buyruq bo'lmagan)
chat_messages jadvaliga "kiruvchi" sifatida yozib boradi - shunda
admin panelning "Foydalanuvchilar" bo'limida shu yozishmani ko'rib,
javob yozish mumkin bo'ladi.

MUHIM: bu handler routers ro'yxatida ENG OXIRIDA turishi kerak, aks
holda boshqa (buyruq/FSM) handlerlardan oldin ishlab, ularga
xalaqit berishi mumkin.
"""

from aiogram import F, Router
from aiogram.types import Message

from .. import db

router = Router(name="chat_log")


@router.message(F.text & ~F.text.startswith("/"))
async def log_incoming_text(message: Message):
    await db.log_chat_message(message.from_user.id, "in", message.text)

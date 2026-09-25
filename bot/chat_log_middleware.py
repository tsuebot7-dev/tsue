"""
Bot yuboradigan HAR BIR xabarni (matn, rasm, video, fayl) avtomatik
ravishda jurnalga "chiquvchi" xabar sifatida yozib boradi - shaxsiy
chatga yuborilgan bo'lsa chat_messages jadvaliga (user_id bo'yicha),
GURUH chatiga yuborilgan bo'lsa group_chat_messages jadvaliga (chat_id
bo'yicha - masalan avtomatik dars jadvali posti yoki admin panelning
"Guruhlar" bo'limidan yuborilgan qo'lda xabar/broadcast).

Bu aiogram'ning "request middleware" mexanizmi orqali ishlaydi - ya'ni
bot.send_message() / answer_photo() / va h.k. qayerdan (qaysi handler
yoki admin panel funksiyasidan) chaqirilishidan qat'iy nazar, ular
haqiqatda Telegram API'ga yuborilayotgan PASTKI QATLAMDA ushlanadi.
Shu sabab, har bir handlerga alohida db.log_chat_message() chaqiruvi
qo'shishning hojati yo'q - admin panelning "Foydalanuvchilar -> Yozish"
va "Guruhlar -> Yozishma" sahifalarida TO'LIQ yozishma (jadval
rasmlari, tugmali xabarlar, avtomatik postlar va h.k.) ko'rinadi.
"""

import logging

from aiogram.client.session.middlewares.base import BaseRequestMiddleware

from . import db

logger = logging.getLogger(__name__)

_LOGGED_METHODS = {"sendMessage", "sendPhoto", "sendVideo", "sendDocument"}


class ChatLogMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        result = await make_request(bot, method)
        try:
            await self._maybe_log(method, result)
        except Exception:
            logger.exception("Chiquvchi xabarni jurnalga yozishda xatolik")
        return result

    async def _maybe_log(self, method, result):
        api_method = getattr(method, "__api_method__", None)
        if api_method not in _LOGGED_METHODS:
            return

        msg = result
        chat = getattr(msg, "chat", None)
        if not chat:
            return

        if chat.type == "private":
            await self._log(db.log_chat_message, chat.id, msg)
        elif chat.type in ("group", "supergroup"):
            await self._log(db.log_group_chat_message, chat.id, msg)

    @staticmethod
    async def _log(log_fn, chat_or_user_id: int, msg):
        if getattr(msg, "photo", None):
            file_id = msg.photo[-1].file_id
            await log_fn(chat_or_user_id, "out", msg.caption or "", msg_type="photo", file_id=file_id)
        elif getattr(msg, "video", None):
            await log_fn(chat_or_user_id, "out", msg.caption or "", msg_type="video", file_id=msg.video.file_id)
        elif getattr(msg, "document", None):
            file_name = msg.document.file_name or "fayl"
            caption = msg.caption or ""
            text = f"{caption}\n📎 {file_name}".strip() if caption else f"📎 {file_name}"
            await log_fn(chat_or_user_id, "out", text, msg_type="document", file_id=msg.document.file_id)
        elif getattr(msg, "text", None):
            await log_fn(chat_or_user_id, "out", msg.text, msg_type="text")

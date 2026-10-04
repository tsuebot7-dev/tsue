"""
Har bir kiruvchi xabar/callback uchun foydalanuvchini bazaga yozib
boradi (yoki bor bo'lsa yangilaydi) va agar u admin panel orqali
bloklangan bo'lsa, so'rovni butunlay e'tiborsiz qoldiradi (botga
umuman yetib bormaydi)."""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from . import db


class UserTrackingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")

        if user is not None:
            if await db.is_blocked(user.id):
                # Bloklangan foydalanuvchi - hech qanday javob bermaymiz.
                return
            await db.upsert_user(user.id, user.username, user.first_name, user.last_name)

        return await handler(event, data)

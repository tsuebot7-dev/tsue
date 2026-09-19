"""
Bot obyektining yagona (singleton) nusxasi. Bu bot/main.py va
admin/app.py ikkalasi tomonidan ham ishlatiladi - shu orqali admin
panel "Reklama yuborish" funksiyasi orqali botning o'zi yordamida
xabar yubora oladi (alohida ulanish ochishga hojat yo'q).
"""

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from . import config

_bot: Bot | None = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        if not config.BOT_TOKEN:
            raise RuntimeError("BOT_TOKEN muhit o'zgaruvchisi berilmagan.")
        _bot = Bot(
            token=config.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return _bot

"""
Botni (aiogram, polling) va admin panelni (FastAPI, uvicorn) BITTA
process ichida, bir vaqtda ishga tushiradi. Bu Railway'da bitta
"service" sifatida deploy qilishni osonlashtiradi (ikkita alohida
service ochishga hojat yo'q).

Agar xohlasangiz, ularni alohida-alohida ham ishga tushirishingiz
mumkin:
    python -m bot.main                       # faqat bot
    uvicorn admin.app:app --host 0.0.0.0 --port 8000   # faqat admin panel
"""

import asyncio
import logging

import uvicorn

from admin.app import app as admin_app
from bot import config
from bot.main import main as run_bot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("run")


async def run_admin():
    uv_config = uvicorn.Config(
        admin_app,
        host="0.0.0.0",
        port=config.ADMIN_PORT,
        log_level="info",
    )
    server = uvicorn.Server(uv_config)
    await server.serve()


async def main():
    logger.info("Bot va admin panel bir vaqtda ishga tushirilmoqda...")
    await asyncio.gather(
        run_bot(),
        run_admin(),
    )


if __name__ == "__main__":
    asyncio.run(main())

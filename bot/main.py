import asyncio
import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from . import config, db
from .bot_instance import get_bot
from .handlers import routers
from .middlewares import UserTrackingMiddleware
from .reminders import run_reminders
from .scheduler import run_scheduler
from .screenshot import start_browser, stop_browser
from .tt_sync import sync_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    if not config.BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN muhit o'zgaruvchisi berilmagan. "
            ".env fayliga yoki Railway Variables bo'limiga BOT_TOKEN=... qo'shing."
        )

    await db.init_db()
    logger.info("Baza tayyor.")

    bot = get_bot()
    dp = Dispatcher(storage=MemoryStorage())

    try:
        from aiogram.types import BotCommand

        await bot.set_my_commands([
            BotCommand(command="start", description="🏠 Bosh menyu"),
            BotCommand(command="saqlanganlar", description="💾 Saqlangan jadvallar"),
            BotCommand(command="eslatma", description="🔔 Dars eslatmalari"),
        ])
    except Exception:
        logger.exception("Bot buyruqlari menyusini o'rnatib bo'lmadi.")

    dp.message.outer_middleware(UserTrackingMiddleware())
    dp.callback_query.outer_middleware(UserTrackingMiddleware())

    for router in routers:
        dp.include_router(router)

    await start_browser()
    logger.info("Playwright brauzeri ishga tushdi.")

    scheduler_task = asyncio.create_task(run_scheduler())
    reminders_task = asyncio.create_task(run_reminders())
    # Eski fon skanerlari (room_scraper, teacher_scraper, group_url_scraper,
    # group_watcher) TSUE saytini minglab marta ochib, server IP'sini
    # bloklatar edi. Endi ularning hammasi bitta JSON'dan ishlaydigan
    # tt_sync orqali bajariladi (qarang: bot/tt_sync.py).
    tt_sync_task = asyncio.create_task(sync_loop())

    try:
        # drop_pending_updates=False: bot qayta ishga tushayotgan paytda
        # (masalan yangi deploy vaqtida) kelgan xabarlar/tugma bosishlar
        # yo'qolib ketmasin, bot tiklangach ularni ham qayta ishlab
        # chiqsin.
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("Bot polling rejimida ishga tushmoqda...")
        import time

        from . import bot_instance

        bot_instance.polling_started_at = time.time()
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        reminders_task.cancel()
        tt_sync_task.cancel()
        await stop_browser()
        await bot.session.close()
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())

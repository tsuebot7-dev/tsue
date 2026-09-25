import asyncio
import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from . import config, db
from .bot_instance import get_bot
from .group_url_scraper import weekly_group_url_sync_loop
from .group_watcher import watch_groups_loop
from .handlers import routers
from .middlewares import UserTrackingMiddleware
from .room_scraper import weekly_room_scan_loop
from .scheduler import run_scheduler
from .screenshot import start_browser, stop_browser
from .teacher_scraper import weekly_teacher_scan_loop

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

    dp.message.outer_middleware(UserTrackingMiddleware())
    dp.callback_query.outer_middleware(UserTrackingMiddleware())

    for router in routers:
        dp.include_router(router)

    await start_browser()
    logger.info("Playwright brauzeri ishga tushdi.")

    scheduler_task = asyncio.create_task(run_scheduler())
    room_scan_task = asyncio.create_task(weekly_room_scan_loop())
    teacher_scan_task = asyncio.create_task(weekly_teacher_scan_loop())
    group_url_sync_task = asyncio.create_task(weekly_group_url_sync_loop())
    group_watch_task = asyncio.create_task(watch_groups_loop())

    try:
        # drop_pending_updates=False: bot qayta ishga tushayotgan paytda
        # (masalan yangi deploy vaqtida) kelgan xabarlar/tugma bosishlar
        # yo'qolib ketmasin, bot tiklangach ularni ham qayta ishlab
        # chiqsin.
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("Bot polling rejimida ishga tushmoqda...")
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        room_scan_task.cancel()
        teacher_scan_task.cancel()
        group_url_sync_task.cancel()
        group_watch_task.cancel()
        await stop_browser()
        await bot.session.close()
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())

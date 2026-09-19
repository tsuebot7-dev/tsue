"""
"Mening guruhim" qilib belgilangan har bir guruh uchun kuniga bir marta
joriy jadvalni qayta o'qib, avvalgi holat bilan solishtiradi. Agar farq
topilsa (masalan xona/o'qituvchi almashgan, dars qo'shilgan/o'chirilgan),
o'sha guruhni tanlagan barcha foydalanuvchilarga avtomatik xabar
yuboriladi.
"""

import asyncio
import json
import logging

from aiogram.types import FSInputFile

from . import db
from .bot_instance import get_bot
from .room_scraper import build_room_result, fetch_svg_from_url
from .screenshot import take_timetable_screenshot

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 6 * 60 * 60  # har 6 soatda tekshiradi


def _snapshot_key(result: dict) -> str:
    """Solishtirish uchun faqat 'band' (busy) qismini olamiz - shu
    o'zgarsa demak jadval o'zgargan (bo'sh joylar o'zgarishi muhim
    emas)."""
    busy = result.get("busy_slots", [])
    simplified = sorted(
        (s["day"], s["period"], s.get("info", "")) for s in busy
    )
    return json.dumps(simplified, ensure_ascii=False)


async def _check_one_group(group_name: str, url: str):
    try:
        svg_text = await fetch_svg_from_url(url)
        result = build_room_result(0, svg_text)  # room_id shart emas, faqat parsing uchun
        new_snapshot = _snapshot_key(result)
    except Exception as e:
        logger.warning("Guruh %s tekshirilmadi: %s", group_name, e)
        await db.log_error("group_watch", f"{group_name}: {e}")
        return

    old_snapshot = await db.get_group_snapshot(group_name)
    await db.set_group_snapshot(group_name, new_snapshot)

    if old_snapshot is None:
        # Birinchi marta ko'rilyapti - bu "boshlang'ich holat", hali
        # solishtirishga hech narsa yo'q, shuning uchun xabar
        # yubormaymiz.
        return

    if old_snapshot == new_snapshot:
        return  # o'zgarish yo'q

    # O'ZGARISH TOPILDI - kuzatuvchilarga xabar beramiz
    user_ids = await db.get_users_watching_group(group_name)
    if not user_ids:
        return

    bot = get_bot()
    for uid in user_ids:
        try:
            png_path = await take_timetable_screenshot(url)
            photo = FSInputFile(png_path)
            await bot.send_photo(
                uid,
                photo=photo,
                caption=(
                    f"🔔 <b>{group_name}</b> jadvalida o'zgarish aniqlandi!\n\n"
                    f"Yangilangan jadval yuqorida."
                ),
            )
            png_path.unlink(missing_ok=True)
        except Exception:
            logger.exception("Foydalanuvchi %s ga xabar yuborilmadi", uid)
        await asyncio.sleep(0.1)


async def watch_groups_loop():
    logger.info("Guruh o'zgarishlarini kuzatuvchi (almashtirishlar) ishga tushdi.")
    while True:
        try:
            groups = await db.get_watched_group_names()
            for g in groups:
                name = g.get("default_group_name")
                url = g.get("default_group_url")
                if name and url:
                    await _check_one_group(name, url)
                await asyncio.sleep(1)  # guruhlar orasida biroz kutamiz
        except Exception:
            logger.exception("Guruh kuzatuvchisida xatolik.")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

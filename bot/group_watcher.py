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

CHECK_INTERVAL_SECONDS = 24 * 60 * 60  # kuniga bir marta tekshiradi (yetarli va xavfsiz)
BETWEEN_GROUPS_DELAY_SECONDS = 3.0  # guruhlar orasida kutish - saytni zoriqtirmaslik uchun


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

    # O'ZGARISH TOPILDI - kuzatuvchilarga xabar beramiz.
    # Ikkala manba: shaxsiy "Mening guruhim" foydalanuvchilari VA
    # avtomatik jadval sozlangan Telegram guruh chatlari.
    user_ids = await db.get_users_watching_group(group_name)
    chat_ids = await db.get_telegram_groups_watching(group_name)
    if not user_ids and not chat_ids:
        return

    bot = get_bot()

    # MUHIM: skrinshotni faqat BIR MARTA olamiz (TSUE saytiga ortiqcha
    # so'rov yubormaslik uchun), so'ng shu bitta faylni barcha
    # qabul qiluvchilarga yuboramiz.
    try:
        png_path = await take_timetable_screenshot(url)
    except Exception as e:
        logger.warning("O'zgargan guruh %s uchun skrinshot olinmadi: %s", group_name, e)
        await db.log_error("group_watch_screenshot", f"{group_name}: {e}")
        return

    caption = f"🔔 <b>{group_name}</b> jadvalida o'zgarish aniqlandi!\n\nYangilangan jadval yuqorida."
    file_id = None

    try:
        for uid in user_ids:
            try:
                photo = file_id or FSInputFile(png_path)
                msg = await bot.send_photo(uid, photo=photo, caption=caption)
                if file_id is None and msg.photo:
                    file_id = msg.photo[-1].file_id  # keyingilar uchun qayta yuklamasdan shu file_id dan foydalanamiz
            except Exception:
                logger.exception("Foydalanuvchi %s ga xabar yuborilmadi", uid)
            await asyncio.sleep(0.1)

        for chat_id in chat_ids:
            try:
                photo = file_id or FSInputFile(png_path)
                msg = await bot.send_photo(chat_id, photo=photo, caption=caption)
                if file_id is None and msg.photo:
                    file_id = msg.photo[-1].file_id
            except Exception:
                logger.exception("Guruh chat %s ga xabar yuborilmadi", chat_id)
            await asyncio.sleep(0.1)
    finally:
        png_path.unlink(missing_ok=True)


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
                await asyncio.sleep(BETWEEN_GROUPS_DELAY_SECONDS)
        except Exception:
            logger.exception("Guruh kuzatuvchisida xatolik.")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

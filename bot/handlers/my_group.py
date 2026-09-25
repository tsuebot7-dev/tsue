"""
'⭐ Mening guruhim' tugmasi va bosh menyudagi '🎓 Mening jadvalim'
tugmasini boshqaradi.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile

from .. import data_loader, db
from ..keyboards import after_result_kb, caption_with_bot_link, loading_text
from ..screenshot import take_timetable_screenshot
from .rating import maybe_prompt_rating

router = Router(name="my_group")
logger = logging.getLogger(__name__)


@router.callback_query(F.data.startswith("setdefault:"))
async def set_default_group(call: CallbackQuery):
    name = call.data.split(":", 1)[1]
    url = data_loader.store.get_leaf_url("guruh", name)
    if not url:
        await call.answer("Havola topilmadi.", show_alert=True)
        return

    await db.set_default_group(call.from_user.id, "guruh", name, url)
    await call.answer(
        f"⭐ {name} — endi sizning asosiy guruhingiz! "
        f"Bosh menyuda 'Mening jadvalim' tugmasi orqali tezkor kirishingiz mumkin.",
        show_alert=True,
    )


@router.callback_query(F.data == "mygroup")
async def show_my_group(call: CallbackQuery):
    default_group = await db.get_default_group(call.from_user.id)
    if not default_group:
        await call.answer("Hali guruh belgilanmagan.", show_alert=True)
        return

    name = default_group["name"]
    url = default_group["url"]

    await call.answer("⏳ Jadval yuklanmoqda...")
    loading_msg = await call.message.edit_text(loading_text(name, url))

    try:
        png_path = await take_timetable_screenshot(url)
        photo = FSInputFile(png_path)
        caption = await caption_with_bot_link(f"🎓 {name} (Mening guruhim)\n🔗 {url}", call.bot)
        await call.message.answer_photo(
            photo,
            caption=caption,
            reply_markup=after_result_kb(prefix="nav"),
        )
        png_path.unlink(missing_ok=True)
        await db.log_event(call.from_user.id, "view_mygroup", name)
        try:
            await loading_msg.delete()
        except Exception:
            pass

        try:
            await maybe_prompt_rating(call.bot, call.from_user.id, call.message.chat.id)
        except Exception:
            logger.exception("Baholash so'rovini yuborishda xatolik")
    except Exception as e:
        logger.exception("Mening guruhim skrinshotida xatolik")
        await db.log_error("mygroup_screenshot", str(e))
        await call.message.answer(
            f"❌ Jadvalni yuklab bo'lmadi. Xatolik: {e}",
            reply_markup=after_result_kb(prefix="nav"),
        )

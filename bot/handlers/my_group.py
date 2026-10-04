"""
'⭐ Mening guruhim' tugmasi va bosh menyudagi '🎓 Mening jadvalim'
tugmasini boshqaradi.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile

from .. import data_loader, db, reminders, ui
from ..keyboards import after_result_kb, loading_text, schedule_caption
from ..timetable_render import get_timetable_image
from .rating import maybe_prompt_rating

router = Router(name="my_group")
logger = logging.getLogger(__name__)


@router.callback_query(F.data.startswith("setdefault:"))
async def set_default_group(call: CallbackQuery):
    name = ui.cb_value(call.data.split(":", 1)[1], data_loader.store.guruhlar_flat.keys())
    url = data_loader.store.get_leaf_url("guruh", name) if name else None
    if not url:
        await call.answer("Havola topilmadi.", show_alert=True)
        return

    await db.set_default_group(call.from_user.id, "guruh", name, url)
    reminders.snapshot_in_background(url, name)
    await call.answer(
        f"⭐ {name} — asosiy guruhingiz qilib belgilandi!\n\n"
        f"Endi bosh menyudagi \"Mening jadvalim\" tugmasi orqali bir bosishda ochasiz "
        f"va har bir dars oldidan eslatma olasiz.",
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

    await call.answer("⏳ Jadval tayyorlanmoqda…")
    loading_msg = await call.message.edit_text(loading_text(name, url))

    try:
        png_path = await get_timetable_image(url)
        photo = FSInputFile(png_path)
        caption = await schedule_caption("mygroup", name, url, call.bot)
        await call.message.answer_photo(
            photo,
            caption=caption,
            reply_markup=after_result_kb(prefix="nav", url=url, back=False),
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
            ui.error_text(name, url),
            reply_markup=after_result_kb(prefix="nav", url=url, back=False),
        )

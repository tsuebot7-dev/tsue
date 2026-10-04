"""
Skrinshot natijasi ostidagi "💾 Saqlab qo'yish" va "👥 Guruhga sozlash"
tugmalarini boshqaradi.
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from .. import data_loader, db, group_guide, reminders, ui

router = Router(name="save_and_group")


@router.callback_query(F.data.startswith("save:"))
async def save_schedule(call: CallbackQuery):
    parts = call.data.split(":", 2)
    if len(parts) != 3:
        await call.answer("Xatolik yuz berdi.", show_alert=True)
        return

    _, feature, name = parts
    flat = {"guruh": data_loader.store.guruhlar_flat, "ustoz": data_loader.store.ustozlar_flat,
            "xona": data_loader.store.xonalar_flat}.get(feature, {})
    name = ui.cb_value(name, flat.keys())
    url = data_loader.store.get_leaf_url(feature, name) if name else None
    if not url:
        await call.answer("Havola topilmadi.", show_alert=True)
        return

    await db.save_schedule(call.from_user.id, feature, name, url)
    if feature == "guruh":
        # Dars eslatmalari uchun jadval matn ko'rinishida saqlanadi.
        reminders.snapshot_in_background(url, name)
    await call.answer(
        "💾 Saqlandi!\n\nBosh menyudagi \"Saqlanganlar\" bo'limidan topasiz. "
        "Guruh jadvallari uchun dars oldidan eslatma ham keladi.",
        show_alert=True,
    )


@router.callback_query(F.data == "groupinfo")
async def group_info(call: CallbackQuery):
    """Botni Telegram guruhga ulash yo'riqnomasi - rasm, nusxalanadigan
    buyruq va "guruhga qo'shish" tugmasi bilan (qarang: bot/group_guide.py)."""
    await call.answer()
    await group_guide.send_guide(call.bot, call.message.chat.id)


async def _saved_text(user_id: int) -> str:
    items = await db.get_saved_schedules(user_id)
    seen, unique = set(), []
    for it in items:
        if it["url"] not in seen:
            seen.add(it["url"])
            unique.append(it)
    if not unique:
        return (
            "💾 <b>Saqlanganlar</b>\n\n"
            "Hozircha saqlangan jadval yo'q.\n\n"
            "<i>Jadvalni ochib, ostidagi \"💾 Saqlash\" tugmasini bosing — "
            "u shu yerda paydo bo'ladi.</i>"
        )
    icons = {"guruh": "🎓", "ustoz": "👨‍🏫", "xona": "🚪"}
    lines = ["💾 <b>Saqlanganlar</b>", "<i>Saytda ochish uchun nomini bosing</i>", ""]
    for n, it in enumerate(unique[:20], start=1):
        lines.append(f"{n}. {icons.get(it['feature'], '📅')} {ui.link(it['name'], it['url'])}")
    return "\n".join(lines)


@router.message(F.text == "/saqlanganlar")
async def list_saved(message):
    await message.answer(await _saved_text(message.from_user.id))


@router.callback_query(F.data == "saved:list")
async def list_saved_button(call: CallbackQuery):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="nav:home")]])
    await call.answer()
    try:
        await call.message.edit_text(await _saved_text(call.from_user.id), reply_markup=kb)
    except Exception:
        await call.message.answer(await _saved_text(call.from_user.id), reply_markup=kb)

"""
Skrinshot natijasi ostidagi "💾 Saqlab qo'yish" va "👥 Guruhga sozlash"
tugmalarini boshqaradi.
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from .. import data_loader, db

router = Router(name="save_and_group")


@router.callback_query(F.data.startswith("save:"))
async def save_schedule(call: CallbackQuery):
    parts = call.data.split(":", 2)
    if len(parts) != 3:
        await call.answer("Xatolik yuz berdi.", show_alert=True)
        return

    _, feature, name = parts
    url = data_loader.store.get_leaf_url(feature, name)
    if not url:
        await call.answer("Havola topilmadi.", show_alert=True)
        return

    await db.save_schedule(call.from_user.id, feature, name, url)
    await call.answer("✅ Saqlandi! /saqlanganlar buyrug'i orqali ko'rishingiz mumkin.", show_alert=True)


@router.callback_query(F.data == "groupinfo")
async def group_info(call: CallbackQuery):
    text = (
        "👥 <b>Guruhga avtomatik jadval yuborish</b>\n\n"
        "1. Botni kerakli Telegram guruhingizga qo'shing.\n"
        "2. Guruhda <b>@{bot_username} /start</b> buyrug'ini yuboring "
        "(guruh administratorlari yozishi kerak).\n"
        "3. Chiqqan menyudan fakultet → kurs → guruhni tanlang.\n"
        "4. Qaysi kunlari va soatda jadval avtomatik yuborilishini tanlang.\n\n"
        "Shundan so'ng bot tanlangan kunlarda, tanlangan vaqtda guruhga "
        "avtomatik ravishda dars jadvalini yuborib turadi."
    ).format(bot_username=(await call.bot.get_me()).username)

    await call.answer()
    await call.message.answer(text)


@router.message(F.text == "/saqlanganlar")
async def list_saved(message):
    items = await db.get_saved_schedules(message.from_user.id)
    if not items:
        await message.answer("Hozircha saqlangan jadvallaringiz yo'q.")
        return

    lines = ["💾 <b>Saqlangan jadvallaringiz:</b>\n"]
    for it in items[:20]:
        lines.append(f"• {it['name']} — {it['url']}")
    await message.answer("\n".join(lines))

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import db, i18n
from ..keyboards import main_menu_kb

router = Router(name="language")


@router.callback_query(F.data == "lang:menu")
async def show_language_menu(call: CallbackQuery):
    lang = await db.get_language(call.from_user.id)
    b = InlineKeyboardBuilder()
    b.button(text="🇺🇿 O'zbekcha", callback_data="lang:set:uz")
    b.button(text="🇷🇺 Русский", callback_data="lang:set:ru")
    b.adjust(2)
    b.row(InlineKeyboardButton(text=i18n.t("home", lang), callback_data="nav:home"))
    await call.message.edit_text(i18n.t("language_choose", lang), reply_markup=b.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("lang:set:"))
async def set_language(call: CallbackQuery):
    lang = call.data.split(":")[2]
    await db.set_language(call.from_user.id, lang)

    default_group = await db.get_default_group(call.from_user.id)
    group_name = default_group["name"] if default_group else None

    await call.answer(i18n.t("language_saved", lang))
    await call.message.edit_text(
        i18n.t("welcome", lang),
        reply_markup=main_menu_kb(group_name),
    )

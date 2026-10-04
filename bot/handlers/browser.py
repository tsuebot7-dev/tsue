"""
Talabalar, O'qituvchilar va Xonalar bo'limlari bir xil mantiqqa ega:
daraxt bo'ylab (fakultet -> kurs -> guruh, yoki bino -> xona) yurish va
oxirida URL manzilidan skrinshot olib yuborish. Shu sabab bitta umumiy
handler orqali barchasi boshqariladi ("feature" FSM data'da saqlanadi).
"""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import data_loader, db, ui
from ..keyboards import loading_text, nav_kb, schedule_caption
from ..timetable_render import get_timetable_image
from ..states import BrowseStates
from .rating import maybe_prompt_rating
from ..tree_nav import (
    FEATURE_TREES,
    effective_node,
    get_node,
    next_path,
    path_title,
    pop_path,
)

router = Router(name="browser")
logger = logging.getLogger(__name__)


def result_kb(prefix: str, feature: str, name: str, url: str | None = None):
    """Skrinshot yuborilgandan keyin chiqadigan tugmalar: saqlash,
    (guruh uchun) mening guruhim qilish, guruhga ulash, saytda ochish,
    orqaga, bosh menyu."""
    b = InlineKeyboardBuilder()
    b.button(text="💾 Saqlash", callback_data=ui.cb(f"save:{feature}", name))
    if feature == "guruh":
        b.button(text="⭐ Mening guruhim", callback_data=ui.cb("setdefault", name))
        b.button(text="👥 Telegram guruhga ulash", callback_data="groupinfo")
    if url:
        b.row(ui.site_button(url))
    b.row(
        InlineKeyboardButton(text="↩️ Orqaga", callback_data=f"{prefix}:back"),
        InlineKeyboardButton(text="🏠 Bosh menyu", callback_data=f"{prefix}:home"),
    )
    if feature == "guruh":
        b.adjust(2, 1, 1, 2)
    else:
        b.adjust(1, 1, 2)
    return b.as_markup()


async def render_level(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    feature = data["feature"]
    path = data.get("path", [])
    page = data.get("page", 0)

    tree = FEATURE_TREES[feature]()
    node = effective_node(tree, path)
    keys = sorted(node.keys())
    display_names_map = data_loader.load_display_names()
    display_list = [data_loader.display_name_for(k, display_names_map) for k in keys]

    text = path_title(feature, path) + "\n\nKerakli bo'limni tanlang 👇"
    kb = nav_kb(display_list, page, can_go_back=bool(path), prefix="nav")

    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        await call.message.answer(text, reply_markup=kb)


@router.callback_query(F.data.in_(["menu:guruh", "menu:xona"]))
async def open_feature(call: CallbackQuery, state: FSMContext):
    feature = call.data.split(":")[1]
    await state.set_state(BrowseStates.browsing)
    await state.update_data(feature=feature, path=[], page=0)
    await render_level(call, state)
    await call.answer()


@router.callback_query(BrowseStates.browsing, F.data.startswith("nav:idx:"))
async def choose_item(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    feature = data["feature"]
    path = data.get("path", [])

    tree = FEATURE_TREES[feature]()
    raw_node = get_node(tree, path)
    node = effective_node(tree, path)
    names = sorted(node.keys())

    idx = int(call.data.split(":")[2])
    if idx < 0 or idx >= len(names):
        await call.answer("Noto'g'ri tanlov, qayta urinib ko'ring.", show_alert=True)
        return

    chosen_name = names[idx]
    chosen_value = node[chosen_name]

    if isinstance(chosen_value, dict):
        new_path = next_path(path, raw_node, node, chosen_name)
        await state.update_data(path=new_path, page=0)
        await render_level(call, state)
        await call.answer()
        return

    # chosen_value - bu URL (leaf element). Skrinshot olib yuboramiz.
    await call.answer("⏳ Jadval tayyorlanmoqda…")
    loading_msg = await call.message.edit_text(loading_text(chosen_name, chosen_value))

    try:
        png_path = await get_timetable_image(chosen_value)
        photo = FSInputFile(png_path)
        caption = await schedule_caption(feature, chosen_name, chosen_value, call.bot)
        await call.message.answer_photo(
            photo,
            caption=caption,
            reply_markup=result_kb("nav", feature, chosen_name, chosen_value),
        )
        png_path.unlink(missing_ok=True)
        await db.log_event(call.from_user.id, f"view_{feature}", chosen_name)
        if path:
            await db.log_event(call.from_user.id, f"view_{feature}_top", path[0])
        try:
            await loading_msg.delete()
        except Exception:
            pass

        if feature == "guruh":
            try:
                await maybe_prompt_rating(call.bot, call.from_user.id, call.message.chat.id)
            except Exception:
                logger.exception("Baholash so'rovini yuborishda xatolik")
    except Exception as e:
        logger.exception("Skrinshot olishda xatolik: %s", chosen_value)
        await db.log_error(f"screenshot_{feature}", f"{chosen_name} ({chosen_value}): {e}")
        await call.message.answer(
            ui.error_text(chosen_name, chosen_value),
            reply_markup=result_kb("nav", feature, chosen_name, chosen_value),
        )


@router.callback_query(BrowseStates.browsing, F.data == "nav:page:prev")
async def page_prev(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(page=max(0, data.get("page", 0) - 1))
    await render_level(call, state)
    await call.answer()


@router.callback_query(BrowseStates.browsing, F.data == "nav:page:next")
async def page_next(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(page=data.get("page", 0) + 1)
    await render_level(call, state)
    await call.answer()


@router.callback_query(BrowseStates.browsing, F.data == "nav:back")
async def go_back(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    path = pop_path(data.get("path", []))
    await state.update_data(path=path, page=0)
    await render_level(call, state)
    await call.answer()

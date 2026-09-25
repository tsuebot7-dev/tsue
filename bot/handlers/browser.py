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
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import data_loader, db
from ..keyboards import caption_with_bot_link, loading_text, nav_kb
from ..screenshot import take_timetable_screenshot
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


def result_kb(prefix: str, feature: str, name: str):
    """Skrinshot yuborilgandan keyin chiqadigan tugmalar: saqlash,
    guruhga sozlash, (guruh uchun) mening guruhim qilish, orqaga,
    bosh menyu."""
    b = InlineKeyboardBuilder()
    b.button(text="💾 Saqlab qo'yish", callback_data=f"save:{feature}:{name}")
    if feature == "guruh":
        b.button(text="⭐ Mening guruhim", callback_data=f"setdefault:{name}")
    b.button(text="👥 Guruhga sozlash", callback_data="groupinfo")
    b.button(text="🔙 Orqaga", callback_data=f"{prefix}:back")
    b.button(text="🏠 Bosh menyu", callback_data=f"{prefix}:home")
    b.adjust(2, 2, 2)
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

    text = path_title(feature, path) + "\n\nQuyidagilardan birini tanlang:"
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
    await call.answer("⏳ Jadval yuklanmoqda, biroz kuting...")
    loading_msg = await call.message.edit_text(loading_text(chosen_name, chosen_value))

    try:
        png_path = await take_timetable_screenshot(chosen_value)
        photo = FSInputFile(png_path)
        caption = await caption_with_bot_link(f"📅 {chosen_name}\n🔗 {chosen_value}", call.bot)
        await call.message.answer_photo(
            photo,
            caption=caption,
            reply_markup=result_kb("nav", feature, chosen_name),
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
            f"❌ Jadvalni yuklab bo'lmadi. Xatolik: {e}\n\n"
            f"Havola: {chosen_value}",
            reply_markup=result_kb("nav", feature, chosen_name),
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

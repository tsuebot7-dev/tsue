"""
Bot Telegram guruhiga qo'shilib, guruhda /start buyrug'i yuborilganda
ishga tushadigan oqim: fakultet -> kurs -> guruh tanlanadi, so'ng
qaysi kunlari va soatda avtomatik jadval yuborilishi belgilanadi.
Natija bot_data.db dagi group_subscriptions jadvaliga yoziladi va
scheduler.py shu ma'lumot asosida davriy xabar yuboradi.
"""

import json
import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import data_loader, db
from ..keyboards import DAY_LABELS_SHORT, days_toggle_kb, nav_kb, times_kb
from ..states import GroupSetupStates
from ..tree_nav import FEATURE_TREES, effective_node, get_node, next_path, path_title, pop_path

router = Router(name="group_setup")
logger = logging.getLogger(__name__)

FEATURE = "guruh"  # hozircha faqat talaba guruhlari uchun


@router.message(CommandStart(), F.chat.type.in_({"group", "supergroup"}))
async def group_start(message: Message, state: FSMContext):
    await state.set_state(GroupSetupStates.browsing)
    await state.update_data(path=[], page=0)
    await message.answer(
        "👋 Salom! Bu guruhga avtomatik dars jadvali yuborishni sozlaymiz.\n\n"
        "Avval fakultetni tanlang:"
    )
    await render_group_level(message, state)


async def render_group_level(target, state: FSMContext):
    data = await state.get_data()
    path = data.get("path", [])
    page = data.get("page", 0)

    tree = FEATURE_TREES[FEATURE]()
    node = effective_node(tree, path)
    keys = sorted(node.keys())
    display_names_map = data_loader.load_display_names()
    display_list = [data_loader.display_name_for(k, display_names_map) for k in keys]

    text = path_title(FEATURE, path) + "\n\nQuyidagilardan birini tanlang:"
    kb = nav_kb(display_list, page, can_go_back=bool(path), prefix="gs")

    if isinstance(target, Message):
        await target.answer(text, reply_markup=kb)
    else:  # CallbackQuery
        try:
            await target.message.edit_text(text, reply_markup=kb)
        except Exception:
            await target.message.answer(text, reply_markup=kb)


@router.callback_query(GroupSetupStates.browsing, F.data.startswith("gs:idx:"))
async def gs_choose_item(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    path = data.get("path", [])

    tree = FEATURE_TREES[FEATURE]()
    raw_node = get_node(tree, path)
    node = effective_node(tree, path)
    names = sorted(node.keys())

    idx = int(call.data.split(":")[2])
    if idx < 0 or idx >= len(names):
        await call.answer("Noto'g'ri tanlov.", show_alert=True)
        return

    chosen_name = names[idx]
    chosen_value = node[chosen_name]

    if isinstance(chosen_value, dict):
        new_path = next_path(path, raw_node, node, chosen_name)
        await state.update_data(path=new_path, page=0)
        await render_group_level(call, state)
        await call.answer()
        return

    # Guruh tanlandi (leaf). Endi kunlarni tanlashga o'tamiz.
    await state.update_data(chosen_name=chosen_name, chosen_url=chosen_value, selected_days=[])
    await state.set_state(GroupSetupStates.choosing_days)
    await call.message.edit_text(
        f"✅ Guruh: <b>{chosen_name}</b>\n\n"
        f"Endi jadval qaysi kunlari avtomatik yuborilishini tanlang "
        f"(bir nechtasini belgilash mumkin), so'ng \"Saqlash\"ni bosing:",
        reply_markup=days_toggle_kb([]),
    )
    await call.answer()


@router.callback_query(GroupSetupStates.browsing, F.data == "gs:page:prev")
async def gs_page_prev(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(page=max(0, data.get("page", 0) - 1))
    await render_group_level(call, state)
    await call.answer()


@router.callback_query(GroupSetupStates.browsing, F.data == "gs:page:next")
async def gs_page_next(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(page=data.get("page", 0) + 1)
    await render_group_level(call, state)
    await call.answer()


@router.callback_query(GroupSetupStates.browsing, F.data == "gs:back")
async def gs_back(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    path = pop_path(data.get("path", []))
    await state.update_data(path=path, page=0)
    await render_group_level(call, state)
    await call.answer()


@router.callback_query(GroupSetupStates.choosing_days, F.data.startswith("gs:day:"))
async def gs_toggle_day(call: CallbackQuery, state: FSMContext):
    code = call.data.split(":")[2]
    data = await state.get_data()
    selected = data.get("selected_days", [])
    if code in selected:
        selected.remove(code)
    else:
        selected.append(code)
    await state.update_data(selected_days=selected)
    await call.message.edit_reply_markup(reply_markup=days_toggle_kb(selected))
    await call.answer()


@router.callback_query(GroupSetupStates.choosing_days, F.data == "gs:days_done")
async def gs_days_done(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_days", [])
    if not selected:
        await call.answer("Kamida bitta kunni tanlang!", show_alert=True)
        return

    await state.set_state(GroupSetupStates.choosing_time)
    days_text = ", ".join(DAY_LABELS_SHORT.get(c, c) for c in selected)
    await call.message.edit_text(
        f"📅 Tanlangan kunlar: <b>{days_text}</b>\n\n"
        f"Endi qaysi soatda yuborilishini tanlang:",
        reply_markup=times_kb(),
    )
    await call.answer()


@router.callback_query(GroupSetupStates.choosing_time, F.data.startswith("gs:time:"))
async def gs_choose_time(call: CallbackQuery, state: FSMContext):
    time_str = call.data.split(":", 2)[2]
    data = await state.get_data()

    chat = call.message.chat
    await db.upsert_group_subscription(
        chat_id=chat.id,
        chat_title=chat.title or str(chat.id),
        feature=FEATURE,
        name=data["chosen_name"],
        url=data["chosen_url"],
        days=json.dumps(data.get("selected_days", [])),
        post_time=time_str,
        created_by=call.from_user.id,
    )

    days_text = ", ".join(DAY_LABELS_SHORT.get(c, c) for c in data.get("selected_days", []))
    await call.message.edit_text(
        f"✅ <b>Bajarildi!</b>\n\n"
        f"Guruh: <b>{data['chosen_name']}</b>\n"
        f"Kunlar: {days_text}\n"
        f"Vaqt: {time_str}\n\n"
        f"Endi bot shu jadvalni ko'rsatilgan kun va vaqtda avtomatik "
        f"ravishda shu guruhga yuborib turadi."
    )
    await call.answer()
    await state.clear()

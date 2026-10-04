import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import data_loader, db, ui
from ..keyboards import (
    DAYS,
    PERIOD_TIMES,
    days_kb,
    loading_text,
    periods_kb,
    schedule_caption,
)
from ..timetable_render import get_timetable_image
from ..states import FreeRoomStates

router = Router(name="free_rooms")
logger = logging.getLogger(__name__)

DAY_LABELS = dict(DAYS)


def rooms_result_kb(rooms: list):
    """Bo'sh xonalar ro'yxati ostida chiqadigan tugmalar - har bir
    xona uchun bitta, bosilsa o'sha xonaning to'liq jadvalini
    (skrinshotini) ko'rsatadi."""
    b = InlineKeyboardBuilder()
    for idx, room in enumerate(rooms):
        b.button(text=f"🚪 {room['room_name']}", callback_data=f"free:room:{idx}")
    b.adjust(2)
    b.row(
        InlineKeyboardButton(text="🔁 Boshqa vaqt", callback_data="menu:free"),
        InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="free:home"),
    )
    return b.as_markup()


def room_view_kb(url: str | None = None):
    b = InlineKeyboardBuilder()
    if url:
        b.row(ui.site_button(url))
    b.row(
        InlineKeyboardButton(text="↩️ Ro'yxatga qaytish", callback_data="free:list_back"),
        InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="free:home"),
    )
    return b.as_markup()


def buildings_kb():
    b = InlineKeyboardBuilder()
    for name in data_loader.store.buildings():
        label = name if not name[0].isdigit() else f"{name}-bino"
        b.button(text=f"🏢 {label}", callback_data=ui.cb("free:bino", name))
    b.adjust(2)
    b.row(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="free:home"))
    return b.as_markup()


@router.callback_query(F.data == "menu:free")
async def start_free_rooms(call: CallbackQuery, state: FSMContext):
    await state.set_state(FreeRoomStates.choosing_building)
    buildings = data_loader.store.buildings()
    if not buildings:
        await call.message.edit_text(
            "🟢 <b>Bo'sh xonalar</b>\n\n"
            "😕 Hozircha bo'sh xonalar ma'lumoti tayyor emas. "
            "Birozdan keyin qayta urinib ko'ring.",
        )
        await call.answer()
        return
    await call.message.edit_text(
        "🟢 <b>Bo'sh xonalarni topish</b>\n"
        "<i>1-qadam: bino</i>\n\n"
        "Qaysi binodan xona qidiramiz? 👇",
        reply_markup=buildings_kb(),
    )
    await call.answer()


@router.callback_query(FreeRoomStates.choosing_building, F.data.startswith("free:bino:"))
async def choose_building(call: CallbackQuery, state: FSMContext):
    building = ui.cb_value(call.data.split(":", 2)[2], data_loader.store.buildings())
    if building is None:
        await call.answer("Bu menyu eskirgan, qaytadan oching.", show_alert=True)
        return
    await state.update_data(building=building)
    await state.set_state(FreeRoomStates.choosing_day)
    label = building if not building[0].isdigit() else f"{building}-bino"
    await call.message.edit_text(
        f"🟢 <b>Bo'sh xonalarni topish</b>\n"
        f"<i>2-qadam: kun</i>\n\n"
        f"🏢 {ui.esc(label)}\n\n"
        f"Qaysi kun? 👇",
        reply_markup=days_kb(prefix="free"),
    )
    await call.answer()


@router.callback_query(FreeRoomStates.choosing_day, F.data.startswith("free:day:"))
async def choose_day(call: CallbackQuery, state: FSMContext):
    day = call.data.split(":", 2)[2]
    await state.update_data(day=day)
    await state.set_state(FreeRoomStates.choosing_period)
    data = await state.get_data()
    building = data["building"]
    building_label = building if not building[0].isdigit() else f"{building}-bino"
    await call.message.edit_text(
        f"🟢 <b>Bo'sh xonalarni topish</b>\n"
        f"<i>3-qadam: para</i>\n\n"
        f"🏢 {ui.esc(building_label)}  ·  📅 {DAY_LABELS.get(day, day)}\n\n"
        f"Qaysi para? 👇",
        reply_markup=periods_kb(prefix="free"),
    )
    await call.answer()


def _room_list_text(building: str, day: str, period: int, rooms: list) -> str:
    building_label = building if not building[0].isdigit() else f"{building}-bino"
    header = (
        f"🟢 <b>Bo'sh xonalar</b>\n\n"
        f"🏢 {ui.esc(building_label)}\n"
        f"📅 {DAY_LABELS.get(day, day)}\n"
        f"🕐 {period}-para · {PERIOD_TIMES.get(period, '')}\n\n"
    )
    if rooms:
        text = (
            header
            + f"✅ <b>{len(rooms)}</b> ta xona bo'sh.\n\n"
            + "<i>Xona jadvalini ko'rish uchun uni tanlang 👇</i>"
        )
    else:
        text = header + "😕 Afsuski, bu vaqtda bo'sh xona topilmadi. Boshqa vaqtni tanlab ko'ring."
    return text


async def _render_room_list(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    building = data["building"]
    day = data["day"]
    period = data["period"]
    rooms = data.get("rooms", [])

    text = _room_list_text(building, day, period, rooms)
    if rooms:
        kb = rooms_result_kb(rooms)
    else:
        b = InlineKeyboardBuilder()
        b.button(text="🔁 Boshqa vaqt", callback_data="menu:free")
        b.button(text="🏠 Bosh menyu", callback_data="free:home")
        b.adjust(2)
        kb = b.as_markup()

    await state.set_state(FreeRoomStates.viewing_rooms)
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        await call.message.answer(text, reply_markup=kb)


@router.callback_query(FreeRoomStates.choosing_period, F.data.startswith("free:period:"))
async def choose_period(call: CallbackQuery, state: FSMContext):
    period = int(call.data.split(":", 2)[2])
    data = await state.get_data()
    building = data["building"]
    day = data["day"]

    rooms = data_loader.store.free_rooms(building, day, period)
    await db.log_event(call.from_user.id, "free_rooms_search", f"{building}/{day}/{period}")

    await state.update_data(period=period, rooms=rooms)
    await _render_room_list(call, state)
    await call.answer()


@router.callback_query(FreeRoomStates.viewing_rooms, F.data == "free:list_back")
async def back_to_room_list(call: CallbackQuery, state: FSMContext):
    await _render_room_list(call, state)
    await call.answer()


@router.callback_query(FreeRoomStates.viewing_rooms, F.data.startswith("free:room:"))
async def view_room_schedule(call: CallbackQuery, state: FSMContext):
    idx_raw = call.data.split(":", 2)[2]
    try:
        idx = int(idx_raw)
    except ValueError:
        await call.answer("Noto'g'ri tanlov.", show_alert=True)
        return

    data = await state.get_data()
    rooms = data.get("rooms", [])
    if idx < 0 or idx >= len(rooms):
        await call.answer("Bu ro'yxat eskirgan, qayta qidiring.", show_alert=True)
        return

    room = rooms[idx]
    name = room.get("room_name", "")
    url = room.get("url", "")
    if not url:
        await call.answer("Bu xona uchun havola topilmadi.", show_alert=True)
        return

    await call.answer("⏳ Jadval tayyorlanmoqda…")
    loading_msg = await call.message.edit_text(loading_text(name, url))

    try:
        png_path = await get_timetable_image(url)
        photo = FSInputFile(png_path)
        caption = await schedule_caption("free", name, url, call.bot)
        await call.message.answer_photo(
            photo,
            caption=caption,
            reply_markup=room_view_kb(url),
        )
        png_path.unlink(missing_ok=True)
        await db.log_event(call.from_user.id, "view_free_room", name)
        try:
            await loading_msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.exception("Bo'sh xona skrinshotida xatolik: %s", name)
        await db.log_error("screenshot_free_room", f"{name} ({url}): {e}")
        await call.message.answer(
            ui.error_text(name, url),
            reply_markup=room_view_kb(url),
        )

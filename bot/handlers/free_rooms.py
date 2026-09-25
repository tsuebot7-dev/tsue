import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import data_loader, db
from ..keyboards import (
    DAYS,
    PERIOD_TIMES,
    caption_with_bot_link,
    days_kb,
    loading_text,
    periods_kb,
)
from ..screenshot import take_timetable_screenshot
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
        b.button(text=f"📄 {room['room_name']}", callback_data=f"free:room:{idx}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text="🔁 Boshqa vaqt / bino", callback_data="menu:free"))
    b.row(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="free:home"))
    return b.as_markup()


def room_view_kb():
    b = InlineKeyboardBuilder()
    b.button(text="🔙 Ro'yxatga qaytish", callback_data="free:list_back")
    b.button(text="🏠 Bosh menyu", callback_data="free:home")
    b.adjust(1)
    return b.as_markup()


def buildings_kb():
    b = InlineKeyboardBuilder()
    for name in data_loader.store.buildings():
        label = name if not name[0].isdigit() else f"{name}-bino"
        b.button(text=f"🏢 {label}", callback_data=f"free:bino:{name}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="free:home"))
    return b.as_markup()


@router.callback_query(F.data == "menu:free")
async def start_free_rooms(call: CallbackQuery, state: FSMContext):
    await state.set_state(FreeRoomStates.choosing_building)
    buildings = data_loader.store.buildings()
    if not buildings:
        await call.message.edit_text(
            "Hozircha bo'sh xonalar ma'lumoti topilmadi. "
            "Iltimos, keyinroq qayta urinib ko'ring.",
        )
        await call.answer()
        return
    await call.message.edit_text(
        "🟢 Bo'sh xonalarni topish\n\nAvval binoni tanlang:",
        reply_markup=buildings_kb(),
    )
    await call.answer()


@router.callback_query(FreeRoomStates.choosing_building, F.data.startswith("free:bino:"))
async def choose_building(call: CallbackQuery, state: FSMContext):
    building = call.data.split(":", 2)[2]
    await state.update_data(building=building)
    await state.set_state(FreeRoomStates.choosing_day)
    label = building if not building[0].isdigit() else f"{building}-bino"
    await call.message.edit_text(
        f"🏢 {label}\n\nEndi kunni tanlang:",
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
        f"🏢 {building_label}, {DAY_LABELS.get(day, day)}\n\n"
        f"Endi darsni (paraga) tanlang:",
        reply_markup=periods_kb(prefix="free"),
    )
    await call.answer()


def _room_list_text(building: str, day: str, period: int, rooms: list) -> str:
    building_label = building if not building[0].isdigit() else f"{building}-bino"
    header = (
        f"🟢 Bo'sh xonalar\n"
        f"🏢 Bino: {building_label}\n"
        f"📅 Kun: {DAY_LABELS.get(day, day)}\n"
        f"🕐 Para: {period} ({PERIOD_TIMES.get(period, '')})\n\n"
    )
    if rooms:
        lines = [f"✅ {r['room_name']}" for r in rooms]
        text = (
            header
            + f"Jami {len(rooms)} ta bo'sh xona topildi:\n\n"
            + "\n".join(lines)
            + "\n\nJadvalini ko'rish uchun quyidan xonani tanlang:"
        )
    else:
        text = header + "❌ Afsuski, bu vaqtda bo'sh xona topilmadi."
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
        b.button(text="🔁 Boshqa vaqt / bino", callback_data="menu:free")
        b.button(text="🏠 Bosh menyu", callback_data="free:home")
        b.adjust(1)
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

    await call.answer("⏳ Jadval yuklanmoqda...")
    loading_msg = await call.message.edit_text(loading_text(name, url))

    try:
        png_path = await take_timetable_screenshot(url)
        photo = FSInputFile(png_path)
        caption = await caption_with_bot_link(f"🚪 {name} (bo'sh xona)\n🔗 {url}", call.bot)
        await call.message.answer_photo(
            photo,
            caption=caption,
            reply_markup=room_view_kb(),
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
            f"❌ Jadvalni yuklab bo'lmadi. Xatolik: {e}\n\nHavola: {url}",
            reply_markup=room_view_kb(),
        )

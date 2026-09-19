from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import data_loader, db
from ..keyboards import DAYS, PERIOD_TIMES, days_kb, periods_kb
from ..states import FreeRoomStates

router = Router(name="free_rooms")

DAY_LABELS = dict(DAYS)


def buildings_kb():
    b = InlineKeyboardBuilder()
    for name in data_loader.store.buildings():
        label = name if not name[0].isdigit() else f"{name}-bino"
        b.button(text=f"🏢 {label}", callback_data=f"free:bino:{name}")
    b.adjust(2)
    from aiogram.types import InlineKeyboardButton
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


@router.callback_query(FreeRoomStates.choosing_period, F.data.startswith("free:period:"))
async def choose_period(call: CallbackQuery, state: FSMContext):
    period = int(call.data.split(":", 2)[2])
    data = await state.get_data()
    building = data["building"]
    day = data["day"]

    rooms = data_loader.store.free_rooms(building, day, period)
    await db.log_event(call.from_user.id, "free_rooms_search", f"{building}/{day}/{period}")

    building_label = building if not building[0].isdigit() else f"{building}-bino"
    header = (
        f"🟢 Bo'sh xonalar\n"
        f"🏢 Bino: {building_label}\n"
        f"📅 Kun: {DAY_LABELS.get(day, day)}\n"
        f"🕐 Para: {period} ({PERIOD_TIMES.get(period, '')})\n\n"
    )

    if rooms:
        lines = [f"✅ {r['room_name']}" for r in rooms]
        text = header + f"Jami {len(rooms)} ta bo'sh xona topildi:\n\n" + "\n".join(lines)
    else:
        text = header + "❌ Afsuski, bu vaqtda bo'sh xona topilmadi."

    b = InlineKeyboardBuilder()
    b.button(text="🔁 Boshqa vaqt / bino", callback_data="menu:free")
    b.button(text="🏠 Bosh menyu", callback_data="free:home")
    b.adjust(1)

    await call.message.edit_text(text, reply_markup=b.as_markup())
    await call.answer()

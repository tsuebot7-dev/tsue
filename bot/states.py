from aiogram.fsm.state import State, StatesGroup


class BrowseStates(StatesGroup):
    """Talabalar / O'qituvchilar / Xonalar bo'limlari uchun umumiy
    ko'rish holati. `feature` FSM data ichida saqlanadi: 'guruh' | 'ustoz' | 'xona'."""
    browsing = State()


class FreeRoomStates(StatesGroup):
    choosing_building = State()
    choosing_day = State()
    choosing_period = State()
    viewing_rooms = State()


class GroupSetupStates(StatesGroup):
    """Guruhga avtomatik jadval yuborishni sozlash uchun holatlar.
    Bu holat guruh chatining o'zida (chat_id manfiy son) ishlaydi."""
    browsing = State()
    choosing_days = State()
    choosing_time = State()

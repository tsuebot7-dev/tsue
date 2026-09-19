from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import db, i18n
from ..keyboards import main_menu_kb

router = Router(name="start")

# Bu "settings" jadvalida 'start_message' kaliti ostida saqlanadi va
# admin panel orqali tahrirlanishi mumkin. Agar admin o'zgartirmagan
# bo'lsa, foydalanuvchi tili bo'yicha (i18n) matn ko'rsatiladi -
# admin o'z matnini kiritsa, u til balandligidan qat'iy nazar
# ko'rsatiladi (hozircha faqat bitta til uchun qo'llab-quvvatlanadi).
_START_MESSAGE_CUSTOMIZED_MARKER = "__custom__"


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await db.log_event(message.from_user.id, "start")

    lang = await db.get_language(message.from_user.id)
    custom_text = await db.get_setting("start_message")
    text = custom_text if custom_text else i18n.t("welcome", lang)

    default_group = await db.get_default_group(message.from_user.id)
    group_name = default_group["name"] if default_group else None

    await message.answer(text, reply_markup=main_menu_kb(group_name))


@router.callback_query(lambda c: c.data == "nav:home" or c.data == "free:home")
async def go_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await db.get_language(call.from_user.id)
    default_group = await db.get_default_group(call.from_user.id)
    group_name = default_group["name"] if default_group else None
    await call.message.edit_text(
        i18n.t("main_menu_title", lang),
        reply_markup=main_menu_kb(group_name),
    )
    await call.answer()

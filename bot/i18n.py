"""
Botning asosiy (statik) matnlari uchun UZ/RU tarjimalari.

MUHIM: fakultet, guruh, o'qituvchi nomlari kabi ma'lumotlar (JSON
fayllardan keladigan) tarjima qilinmaydi - ular TSUE'ning rasmiy
nomlari, https://tsue.edupage.org saytida qanday bo'lsa shundayligicha
qoladi. Faqat botning o'zi chiqaradigan tugma/xabar matnlari
tarjima qilinadi.
"""

TRANSLATIONS = {
    "welcome": {
        "uz": (
            "Assalomu alaykum{name}! 👋\n\n"
            "📅 <b>TSUE dars jadvali</b>\n"
            "<i>Toshkent davlat iqtisodiyot universiteti</i>\n\n"
            "🎓 Guruh, 👨‍🏫 o'qituvchi va 🚪 xona jadvallari\n"
            "🟢 Bo'sh xonalarni topish\n"
            "🔔 Har bir dars oldidan eslatma\n\n"
            "Kerakli bo'limni tanlang 👇"
        ),
        "ru": (
            "Здравствуйте{name}! 👋\n\n"
            "📅 <b>Расписание TSUE</b>\n"
            "<i>Ташкентский государственный экономический университет</i>\n\n"
            "🎓 Расписание групп, 👨‍🏫 преподавателей и 🚪 аудиторий\n"
            "🟢 Поиск свободных аудиторий\n"
            "🔔 Напоминание перед каждой парой\n\n"
            "Выберите раздел 👇"
        ),
    },
    "menu_students": {"uz": "🎓 Talabalar", "ru": "🎓 Студенты"},
    "menu_teachers": {"uz": "👨‍🏫 O'qituvchilar", "ru": "👨‍🏫 Преподаватели"},
    "menu_rooms": {"uz": "🚪 Xonalar", "ru": "🚪 Аудитории"},
    "menu_free_rooms": {"uz": "🟢 Bo'sh xonalarni topish", "ru": "🟢 Найти свободные аудитории"},
    "menu_my_schedule": {"uz": "🎓 Mening jadvalim", "ru": "🎓 Моё расписание"},
    "menu_language": {"uz": "🌐 Til / Язык", "ru": "🌐 Til / Язык"},
    "back": {"uz": "🔙 Orqaga", "ru": "🔙 Назад"},
    "home": {"uz": "🏠 Bosh menyu", "ru": "🏠 Главное меню"},
    "save": {"uz": "💾 Saqlab qo'yish", "ru": "💾 Сохранить"},
    "set_my_group": {"uz": "⭐ Mening guruhim", "ru": "⭐ Моя группа"},
    "setup_group_chat": {"uz": "👥 Guruhga sozlash", "ru": "👥 Настроить для группы"},
    "choose_option": {"uz": "Quyidagilardan birini tanlang:", "ru": "Выберите один из пунктов:"},
    "main_menu_title": {"uz": "🏠 <b>Bosh menyu</b>\n\nKerakli bo'limni tanlang 👇", "ru": "🏠 <b>Главное меню</b>\n\nВыберите раздел 👇"},
    "loading": {"uz": "⏳ Jadval yuklanmoqda...", "ru": "⏳ Загрузка расписания..."},
    "language_choose": {"uz": "Tilni tanlang:", "ru": "Выберите язык:"},
    "language_saved": {"uz": "✅ Til o'zbekchaga o'zgartirildi.", "ru": "✅ Язык изменён на русский."},
}


def welcome(lang: str, first_name: str | None = None) -> str:
    """Salomlashuv matni - foydalanuvchi ismi bilan."""
    import html

    name = f", <b>{html.escape(first_name, quote=False)}</b>" if first_name else ""
    return t("welcome", lang).replace("{name}", name)


def t(key: str, lang: str = "uz") -> str:
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    return entry.get(lang, entry.get("uz", key))

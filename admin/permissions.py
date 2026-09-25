"""
Admin panelidagi AUTENTIFIKATSIYA (kim ekanini tekshirish) va
QO'SHIMCHA ADMINLAR uchun BO'LIM DARAJASIDAGI (granular) kirish
huquqlarini boshqarish.

Har bir bo'lim uchun 3 daraja mumkin:
  - "none" (yo'q)    - bo'lim UMUMAN ko'rinmaydi/kirib bo'lmaydi
                        (sidebar'da ham yashiriladi)
  - "view" (ko'rish) - faqat ko'rish mumkin, hech narsani o'zgartira/
                        yubora/o'chira olmaydi (har qanday POST/amaliy
                        tugma 403 bilan bloklanadi)
  - "edit" (to'liq)  - to'liq huquq: ko'rish + barcha amallar
                        (saqlash, o'chirish, bloklash, xabar yuborish
                        va hokazo)

ASOSIY ADMIN (.env / Railway'dagi ADMIN_USERNAME/ADMIN_PASSWORD) bu
cheklovlarga UMUMAN BOG'LIQ EMAS - u doim, hamma joyda to'liq huquqqa
ega (bu tekshiruv har bir dependency ichida `is_super_admin` bayrog'i
orqali eng birinchi qilib tekshiriladi).

MUHIM (xavfsizlik): "Adminlar" bo'limining o'zi (yangi admin
qo'shish/o'chirish/huquq berish) BU RO'YXATDA UMUMAN YO'Q va hech
qanday qo'shimcha adminga berilmaydi - faqat asosiy admin kira oladi
(`require_super_admin`). Aks holda, cheklangan huquqli admin o'ziga
(yoki boshqa adminga) o'zi cheksiz huquq berib olishi mumkin bo'lardi
- bu klassik "privilege escalation" zaifligi.
"""

import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from bot import config, db

security = HTTPBasic()

LEVEL_NONE = "none"
LEVEL_VIEW = "view"
LEVEL_EDIT = "edit"

_LEVEL_RANK = {LEVEL_NONE: 0, LEVEL_VIEW: 1, LEVEL_EDIT: 2}

# Bo'lim kaliti -> sidebar/admin-forma uchun ko'rsatiladigan nomi.
# "dashboard" ataylab shu yerda YO'Q - bosh sahifa (statistika) har
# qanday autentifikatsiya qilingan admin uchun doim ochiq, chunki u
# faqat umumiy ko'rsatkichlarni ko'rsatadi va texnik jihatdan
# "bo'lim"lar orasidagi navigatsiya markazi vazifasini bajaradi.
SECTIONS = {
    "data": "📁 Ma'lumotlarni yangilash",
    "users": "👥 Foydalanuvchilar",
    "support": "🛠 Texnik bo'lim",
    "groups": "🏫 Guruhlar",
    "ratings": "⭐ Xizmat reytingi",
    "broadcast": "📢 Reklama yuborish",
    "import_legacy": "📥 Eski botdan import",
    "new_items": "🆕 Yangi topilganlar",
    "titles": "🏷️ Sarlavha nomlari",
    "hierarchy": "🗂️ Ierarxiya",
    "start_message": "💬 /start xabari",
    "errors": "🔴 Xatolar jurnali",
}

LEVEL_LABELS = {
    LEVEL_NONE: "Yo'q",
    LEVEL_VIEW: "Faqat ko'rish",
    LEVEL_EDIT: "To'liq huquq",
}


def normalize_permissions(raw: dict | None) -> dict:
    """Formadan yoki bazadan kelgan xom lug'atni faqat TANIQLI
    bo'limlar va TO'G'RI darajalar bilan tozalab qaytaradi - noma'lum
    kalitlar yoki qiymatlar jimgina tashlab yuboriladi. "none" bo'lgan
    bo'limlar ham saqlanmaydi (lug'atda yo'qligi = "none" bilan bir
    xil, shu bilan saqlangan JSON ixcham bo'ladi)."""
    raw = raw or {}
    cleaned = {}
    for key in SECTIONS:
        level = raw.get(key, LEVEL_NONE)
        if level not in _LEVEL_RANK:
            level = LEVEL_NONE
        if level != LEVEL_NONE:
            cleaned[key] = level
    return cleaned


def has_access(is_super_admin: bool, permissions: dict, section: str, level: str = LEVEL_VIEW) -> bool:
    if is_super_admin:
        return True
    have = (permissions or {}).get(section, LEVEL_NONE)
    return _LEVEL_RANK.get(have, 0) >= _LEVEL_RANK.get(level, 1)


def has_any_access(is_super_admin: bool, permissions: dict, sections: list, level: str = LEVEL_VIEW) -> bool:
    if is_super_admin:
        return True
    return any(has_access(is_super_admin, permissions, s, level) for s in sections)


# ---------------------------------------------------------------- #
# Autentifikatsiya (HTTP Basic Auth) - avvalgi admin/app.py'dagi
# check_auth funksiyasi shu yerga ko'chirildi, chunki permission
# dependency'lari shu tekshiruvga bog'liq va app.py <-> permissions.py
# orasida aylanma import (circular import) bo'lmasligi kerak.
# ---------------------------------------------------------------- #

async def check_auth(request: Request, credentials: HTTPBasicCredentials = Depends(security)) -> str:
    # 1) Asosiy (.env / Railway Variables) admin - CHEKLOVSIZ, to'liq huquq
    correct_username = secrets.compare_digest(credentials.username, config.ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, config.ADMIN_PASSWORD)
    if correct_username and correct_password:
        request.state.admin_username = credentials.username
        request.state.is_super_admin = True
        request.state.admin_permissions = {}
        return credentials.username

    # 2) Baza orqali qo'shilgan qo'shimcha adminlar - huquqlari
    # bo'lim-darajasida cheklangan bo'lishi mumkin.
    if await db.verify_admin_credentials(credentials.username, credentials.password):
        request.state.admin_username = credentials.username
        request.state.is_super_admin = False
        request.state.admin_permissions = await db.get_admin_permissions(credentials.username)
        return credentials.username

    raise HTTPException(
        status_code=401,
        detail="Login yoki parol noto'g'ri",
        headers={"WWW-Authenticate": "Basic"},
    )


def require_permission(section: str, level: str = LEVEL_VIEW):
    """Bitta bo'lim uchun kamida `level` darajali huquq talab
    qiladigan FastAPI dependency yaratadi. Masalan:

        user: str = Depends(require_permission("users", LEVEL_EDIT))
    """

    async def _dep(request: Request, user: str = Depends(check_auth)) -> str:
        is_super = getattr(request.state, "is_super_admin", False)
        perms = getattr(request.state, "admin_permissions", {})
        if not has_access(is_super, perms, section, level):
            label = SECTIONS.get(section, section)
            raise HTTPException(403, f"Sizda “{label}” bo'limi uchun yetarli huquq yo'q.")
        return user

    return _dep


def require_any_permission(sections: list, level: str = LEVEL_VIEW):
    """Bir nechta bo'limdan KAMIDA BITTASIGA `level` darajali huquq
    bo'lsa yetarli bo'lgan holatlar uchun (masalan foydalanuvchi bilan
    yozishma sahifasi - ham "users", ham "support" orqali kirish
    mumkin)."""

    async def _dep(request: Request, user: str = Depends(check_auth)) -> str:
        is_super = getattr(request.state, "is_super_admin", False)
        perms = getattr(request.state, "admin_permissions", {})
        if not has_any_access(is_super, perms, sections, level):
            raise HTTPException(403, "Sizda bu bo'lim uchun yetarli huquq yo'q.")
        return user

    return _dep


async def require_super_admin(request: Request, user: str = Depends(check_auth)) -> str:
    """Faqat asosiy (.env) admin kira oladigan bo'limlar uchun (hozircha
    faqat "Adminlar" bo'limi) - qo'shimcha adminlarga BU HECH QACHON
    berilmaydi, xavfsizlik sababli (yuqoridagi modul docstring'iga
    qarang)."""
    if not getattr(request.state, "is_super_admin", False):
        raise HTTPException(403, "Bu bo'lim faqat asosiy admin uchun ochiq.")
    return user

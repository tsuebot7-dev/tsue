"""
Eski (avvalgi) botning SQLite bazasidan (users, auto_schedules,
saved_schedules, logs jadvallari) foydalanuvchi ma'lumotlarini yangi
tizimga import qiladi.

MUHIM: eski ma'lumotlardagi URL manzillar "num=91" bilan, hozirgi
tizim esa "num=94" bilan ishlaydi (TSUE semestr/jadval ID'sini
almashtirgan) - shuning uchun eski URL'lar endi ishlamaydi. Bu modul
har bir yozuvning NOMI (masalan "BHA-79/23") bo'yicha hozirgi
guruhlar.json/xonalar.json/ustozlar.json fayllaridan YANGI, to'g'ri
ishlaydigan URL'ni qidirib topadi. Agar nom hozirgi faylda topilmasa,
o'sha yozuv "topilmadi" ro'yxatiga tushadi va import qilinmaydi (aks
holda ishlamaydigan eski havola saqlanib qolardi).

free_rooms jadvali IMPORT QILINMAYDI - u eski botda har bir aniq
kalendar sanasi uchun alohida yozib borilgan tarixiy ma'lumot edi,
hozirgi tizim esa haftalik takrorlanuvchi naqshni saqlaydi
(room_scraper.py orqali doimiy yangilanadi) - ikkisi mos kelmaydi va
eskisi endi kerak emas.
"""

import sqlite3

from . import data_loader, db

TUR_TO_FEATURE = {
    "talaba": "guruh",
    "ustoz": "ustoz",
    "xona": "xona",
}

# ESLATMA: eski botda kun qanday raqamlangani aniq hujjatlashtirilmagan.
# Bu yerda 1=Dushanba ... 7=Yakshanba deb qabul qilingan (Markaziy
# Osiyoda bot ishlab chiqishda eng ko'p uchraydigan konvensiya). Agar
# import qilingandan keyin kunlar noto'g'ri chiqsa, admin panelning
# "Guruhlar" bo'limidan o'sha yozuvni o'chirib, guruhda /start orqali
# qaytadan sozlash eng ishonchli yo'l.
DAY_MAP = {1: "mon", 2: "tue", 3: "wed", 4: "thu", 5: "fri", 6: "sat", 7: "sun"}


def _resolve_fresh_url(feature: str, name: str) -> str | None:
    """Nom bo'yicha HOZIRGI (num=94) to'g'ri ishlaydigan URL'ni
    qidiradi. Turli formatlash farqlari uchun moslashtiriladi:
    - katta/kichik harf farqi
    - "FAKULTET NOMI - GURUH" formatidagi eski yozuvlar (faqat
      " - " dan keyingi qismi haqiqiy nom bo'ladi)."""
    if not name:
        return None
    name = name.strip()

    candidates = [name]
    if " - " in name:
        candidates.append(name.rsplit(" - ", 1)[-1].strip())

    flat_map = {
        "guruh": data_loader.store.guruhlar_flat,
        "ustoz": data_loader.store.ustozlar_flat,
        "xona": data_loader.store.xonalar_flat,
    }.get(feature, {})

    for cand in candidates:
        url = flat_map.get(cand)
        if url:
            return url
        cand_lower = cand.lower()
        for k, v in flat_map.items():
            if k.lower() == cand_lower:
                return v

    return None


async def migrate_from_sqlite(file_path: str) -> dict:
    report = {
        "users_migrated": 0,
        "users_skipped": [],
        "groups_migrated": 0,
        "groups_skipped": [],
        "saved_migrated": 0,
        "saved_skipped": [],
        "logs_migrated": 0,
    }

    old_conn = sqlite3.connect(file_path)
    old_conn.row_factory = sqlite3.Row

    existing_tables = {
        r[0] for r in old_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    # --- users -> asosiy (default) guruh/xona/ustoz ---
    if "users" in existing_tables:
        for row in old_conn.execute("SELECT * FROM users").fetchall():
            row = dict(row)
            try:
                user_id = int(row["user_id"])
            except (TypeError, ValueError):
                continue

            feature = TUR_TO_FEATURE.get(row.get("tur"), "guruh")
            name = row.get("malumot") or ""
            fresh_url = _resolve_fresh_url(feature, name)

            username = (row.get("username") or "").lstrip("@") or None
            full_name = row.get("full_name") or ""
            first_name = full_name.split(" ")[0] if full_name else None
            last_name = " ".join(full_name.split(" ")[1:]) or None if full_name else None

            await db.upsert_user(user_id, username, first_name, last_name)

            if fresh_url:
                await db.set_default_group(user_id, feature, name, fresh_url)
                report["users_migrated"] += 1
            else:
                report["users_skipped"].append(f"{name} ({feature}, user_id={user_id})")

    # --- saved_schedules ---
    if "saved_schedules" in existing_tables:
        for row in old_conn.execute("SELECT * FROM saved_schedules").fetchall():
            row = dict(row)
            try:
                user_id = int(row["user_id"])
            except (TypeError, ValueError):
                continue

            feature = TUR_TO_FEATURE.get(row.get("tur"), "guruh")
            name = row.get("nom") or ""
            fresh_url = _resolve_fresh_url(feature, name)

            if fresh_url:
                await db.save_schedule(user_id, feature, name, fresh_url)
                report["saved_migrated"] += 1
            else:
                report["saved_skipped"].append(f"{name} ({feature})")

    # --- auto_schedules -> group_subscriptions ---
    if "auto_schedules" in existing_tables:
        for row in old_conn.execute("SELECT * FROM auto_schedules").fetchall():
            row = dict(row)
            try:
                chat_id = int(row["chat_id"])
            except (TypeError, ValueError):
                continue

            name = row.get("group_name") or ""
            fresh_url = _resolve_fresh_url("guruh", name) if name else None

            day_code = DAY_MAP.get(row.get("day"))
            post_time = row.get("vaqt") or "09:00"

            if fresh_url and day_code:
                import json as _json
                await db.upsert_group_subscription(
                    chat_id=chat_id,
                    chat_title=row.get("chat_title") or str(chat_id),
                    feature="guruh",
                    name=name,
                    url=fresh_url,
                    days=_json.dumps([day_code]),
                    post_time=post_time,
                    created_by=0,
                )
                report["groups_migrated"] += 1
            else:
                report["groups_skipped"].append(
                    f"{row.get('chat_title')} ({name or 'nomsiz'}) - qo'lda qayta sozlash kerak"
                )

    # --- logs -> events (ixtiyoriy, statistikaning tarixiy davomiyligi uchun) ---
    if "logs" in existing_tables:
        for row in old_conn.execute("SELECT * FROM logs").fetchall():
            row = dict(row)
            try:
                user_id = int(row["user_id"])
            except (TypeError, ValueError):
                continue
            await db.log_event(user_id, row.get("action") or "unknown", row.get("data") or "")
            report["logs_migrated"] += 1

    old_conn.close()
    return report

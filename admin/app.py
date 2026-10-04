"""
Sidebar (chap tomonda vertikal menyu) dizaynli admin panel:
- Statistika (dashboard)
- Ma'lumotlarni yangilash (JSON fayllar)
- Foydalanuvchilar (ro'yxat, qidiruv, bloklash)
- Reklama yuborish (barcha foydalanuvchilarga xabar)
- Sarlavha nomlari / Ierarxiya sozlamalari

Ishga tushirish (lokal test uchun):
    uvicorn admin.app:app --reload --port 8000
"""

import asyncio
import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import config, data_loader, db  # noqa: E402
from bot.bot_instance import get_bot  # noqa: E402
from .permissions import (  # noqa: E402
    SECTIONS,
    LEVEL_NONE,
    LEVEL_VIEW,
    LEVEL_EDIT,
    LEVEL_LABELS,
    check_auth,
    normalize_permissions,
    require_permission,
    require_any_permission,
    require_super_admin,
)

app = FastAPI(title="TSUE Bot Admin")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

@app.on_event("startup")
async def _on_startup():
    await db.init_db()

FILES = {
    "guruhlar": config.GURUHLAR_FILE,
    "ustozlar": config.USTOZLAR_FILE,
    "xonalar": config.XONALAR_FILE,
    "boshxonalar": config.BOSHXONALAR_FILE,
}

FILE_TITLES = {
    "guruhlar": "🎓 Guruhlar (talabalar)",
    "ustozlar": "👨‍🏫 O'qituvchilar",
    "xonalar": "🚪 Xonalar",
    "boshxonalar": "🟢 Bo'sh xonalar ma'lumoti",
}

EVENT_LABELS = {
    "start": "Bot ishga tushirildi (/start)",
    "view_guruh": "Talaba jadvali ko'rildi",
    "view_ustoz": "O'qituvchi jadvali ko'rildi",
    "view_xona": "Xona jadvali ko'rildi",
    "view_free_room": "Bo'sh xona jadvali ko'rildi",
    "free_rooms_search": "Bo'sh xona qidiruvi",
    "rating": "Xizmatni baholadi",
    "view_talaba": "Talaba jadvali ko'rildi (eski bot)",
    "view_guruh_top": "Talaba jadvali (fakultetlar hisobi)",
    "view_ustoz_top": "O'qituvchi jadvali (bo'limlar hisobi)",
    "view_xona_top": "Xona jadvali (binolar hisobi)",
    "view_mygroup": "\"Mening jadvalim\" ochildi",
    "free_rooms_search_ai": "Bo'sh xona qidiruvi (AI orqali)",
}

_last_broadcast_result = None


def file_stats(path: Path) -> dict:
    if not path.exists():
        return {"exists": False, "count": 0, "size_kb": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        count = len(data) if isinstance(data, (dict, list)) else 0
    except Exception:
        count = "xato"
    size_kb = round(path.stat().st_size / 1024, 1)
    return {"exists": True, "count": count, "size_kb": size_kb}


# ---------------------------------------------------------------- #
# Bosh sahifa - Statistikaga yo'naltiramiz
# ---------------------------------------------------------------- #

@app.get("/", response_class=HTMLResponse)
async def root(user: str = Depends(check_auth)):
    return RedirectResponse(url="/dashboard")


TASHKENT = __import__("datetime").timedelta(hours=5)

VIEW_GROUPS = {
    "guruh": ("Talaba jadvali", ("view_guruh", "view_mygroup", "view_talaba", "view_guruh_ai")),
    "ustoz": ("O'qituvchi jadvali", ("view_ustoz", "view_ustoz_ai")),
    "xona": ("Xona va bo'sh xona", ("view_xona", "view_free_room", "free_rooms_search", "free_rooms_search_ai")),
}


def _pct(now: int, before: int):
    if not before:
        return None
    return round((now - before) * 100 / before)


async def _dashboard_context(admin_name: str) -> dict:
    import datetime
    from bot import tt_sync

    now = datetime.datetime.utcnow()
    users, events = await db.get_dashboard_raw(now - datetime.timedelta(days=60))
    local_today = (now + TASHKENT).date()

    def window(days_from: int, days_to: int):
        a, b = now - datetime.timedelta(days=days_from), now - datetime.timedelta(days=days_to)
        return [e for e in events if e["created_at"] and a <= e["created_at"] < b]

    last7, prev7 = window(7, 0), window(14, 7)
    active7 = {e["user_id"] for e in last7}
    active_prev = {e["user_id"] for e in prev7}
    views = lambda evs: sum(1 for e in evs if (e["event_type"] or "").startswith(("view_", "free_rooms")))  # noqa: E731
    new7 = sum(1 for u in users if u["first_seen"] and u["first_seen"] >= now - datetime.timedelta(days=7))
    new_prev = sum(1 for u in users if u["first_seen"] and now - datetime.timedelta(days=14) <= u["first_seen"] < now - datetime.timedelta(days=7))
    my_group = sum(1 for u in users if u.get("default_group_name"))
    targets = await db.get_reminder_targets()

    kpis = [
        {"label": "Foydalanuvchilar", "value": len(users), "icon": "users", "tone": "blue",
         "trend": _pct(len(users), len(users) - new7), "note": f"+{new7} so'nggi 7 kun"},
        {"label": "Faol", "value": len(active7), "icon": "pulse", "tone": "green",
         "trend": _pct(len(active7), len(active_prev)), "note": "so'nggi 7 kun"},
        {"label": "Yangi", "value": new7, "icon": "user-plus", "tone": "purple",
         "trend": _pct(new7, new_prev), "note": "so'nggi 7 kun"},
        {"label": "Eslatma oladi", "value": len(targets), "icon": "bell", "tone": "orange",
         "trend": None, "note": f"{my_group} ta \"Mening guruhim\""},
        {"label": "Jadval ko'rishlari", "value": views(last7), "icon": "calendar", "tone": "teal",
         "trend": _pct(views(last7), views(prev7)), "note": "so'nggi 7 kun"},
    ]

    # Kunlik faollik (Toshkent sanasi bo'yicha), 30 kun
    days = [local_today - datetime.timedelta(days=i) for i in range(29, -1, -1)]
    per_day_users = {d: set() for d in days}
    per_day_views = {d: 0 for d in days}
    for e in events:
        if not e["created_at"]:
            continue
        d = (e["created_at"] + TASHKENT).date()
        if d in per_day_users:
            per_day_users[d].add(e["user_id"])
            if (e["event_type"] or "").startswith(("view_", "free_rooms")):
                per_day_views[d] += 1
    chart = {
        "labels": [d.strftime("%d.%m") for d in days],
        "users": [len(per_day_users[d]) for d in days],
        "views": [per_day_views[d] for d in days],
    }

    # Ko'rishlar taqsimoti (30 kun)
    last30 = window(30, 0)
    donut = []
    for key, (label, types) in VIEW_GROUPS.items():
        donut.append({"label": label, "value": sum(1 for e in last30 if e["event_type"] in types)})
    donut_total = sum(d["value"] for d in donut)

    # So'nggi faol foydalanuvchilar
    recent = sorted((u for u in users if u["last_seen"]), key=lambda u: u["last_seen"], reverse=True)[:6]
    recent_rows = []
    for u in recent:
        name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or "—"
        recent_rows.append({
            "id": u["user_id"],
            "name": name,
            "username": u.get("username"),
            "initials": "".join(w[0] for w in name.split()[:2]).upper() if name != "—" else "?",
            "group": u.get("default_group_name") or "—",
            "time": (u["last_seen"] + TASHKENT).strftime("%H:%M") if (u["last_seen"] + TASHKENT).date() == local_today
            else (u["last_seen"] + TASHKENT).strftime("%d.%m"),
            "time_full": (u["last_seen"] + TASHKENT).strftime("%d.%m.%Y %H:%M"),
            "online": now - u["last_seen"] <= datetime.timedelta(minutes=10),
        })

    sync = await tt_sync.get_status()
    feed = []
    if sync.get("at"):
        feed.append({"tone": "green", "text": f"TSUE jadvali sinxronlandi: {sync.get('groups_total', 0)} ta guruh, "
                     f"{sync.get('free_rooms', 0)} ta xona", "time": sync.get("at")})
        if sync.get("changed_groups"):
            feed.append({"tone": "orange", "text": f"{sync['changed_groups']} ta guruh jadvali o'zgardi — xabar yuborildi",
                         "time": sync.get("at")})
    new_items = await db.get_discovered_items()
    if new_items:
        feed.append({"tone": "blue", "text": f"{len(new_items)} ta yangi guruh/xona topildi", "time": None, "href": "/new-items"})
    for err in (await db.get_recent_errors(limit=3)):
        feed.append({"tone": "red", "text": f"Xatolik: {err.get('context')}", "time": err.get("created_at"), "href": "/errors"})
    for item in feed:
        t = item.get("time")
        if isinstance(t, (int, float)):
            item["time"] = (datetime.datetime.utcfromtimestamp(t) + TASHKENT).strftime("%d.%m.%Y %H:%M")
        elif t:
            dt = db._as_dt(t)
            item["time"] = (dt + TASHKENT).strftime("%d.%m.%Y %H:%M") if dt else str(t)

    from bot import bot_instance

    last_activity = max((u["last_seen"] for u in users if u["last_seen"]), default=None)
    bot_online = bot_instance.polling_started_at is not None
    return {
        "admin_name": admin_name,
        "kpis": kpis,
        "chart": chart,
        "donut": donut,
        "donut_total": donut_total,
        "recent": recent_rows,
        "feed": feed[:5],
        "sync_at": (datetime.datetime.utcfromtimestamp(sync["at"]) + TASHKENT).strftime("%d.%m.%Y %H:%M") if sync.get("at") else None,
        "bot_online": bot_online,
        "last_activity": (last_activity + TASHKENT).strftime("%d.%m.%Y %H:%M") if last_activity else "—",
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: str = Depends(check_auth)):
    ctx = await _dashboard_context(getattr(request.state, "admin_username", user) or user)
    return templates.TemplateResponse(request, "dashboard.html", {"active": "dashboard", **ctx})


@app.get("/api/notifications")
async def notifications(request: Request, user: str = Depends(check_auth)):
    """Yuqori paneldagi qo'ng'iroqcha uchun: yangi topilganlar, so'nggi
    24 soatdagi xatolar va javob kutayotgan murojaatlar."""
    import datetime

    items = []
    new_items = await db.get_discovered_items()
    if new_items:
        items.append({"text": f"{len(new_items)} ta yangi guruh/xona topildi", "href": "/new-items", "tone": "blue"})
    day_ago = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    errors = [e for e in await db.get_recent_errors(limit=50)
              if (db._as_dt(e.get("created_at")) or datetime.datetime.min) >= day_ago]
    if errors:
        items.append({"text": f"So'nggi 24 soatda {len(errors)} ta xatolik", "href": "/errors", "tone": "red"})
    try:
        support = await db.get_support_stats()
        waiting = support.get("needs_reply") or 0
        if waiting:
            items.append({"text": f"{waiting} ta murojaat javob kutmoqda", "href": "/support", "tone": "orange"})
    except Exception:
        pass
    return {"count": len(items), "items": items}


# ---------------------------------------------------------------- #
# Ma'lumotlarni yangilash
# ---------------------------------------------------------------- #

@app.get("/data", response_class=HTMLResponse)
async def data_page(request: Request, user: str = Depends(require_permission("data", LEVEL_VIEW))):
    import datetime
    from bot import timetable_data, tt_sync

    stats = {key: file_stats(path) for key, path in FILES.items()}
    status = await tt_sync.get_status()

    def fmt(ts):
        if not ts:
            return "-"
        return (datetime.datetime.utcfromtimestamp(float(ts)) + datetime.timedelta(hours=5)).strftime("%Y-%m-%d %H:%M")

    return templates.TemplateResponse(
        request,
        "data.html",
        {
            "active": "data",
            "files": FILES,
            "titles": FILE_TITLES,
            "stats": stats,
            "sync": status,
            "sync_at": fmt(status.get("at")),
            "loaded_at": fmt(status.get("loaded_at")),
            "refresh_hours": config.TIMETABLE_REFRESH_HOURS,
            "running": tt_sync._lock.locked(),
            "site": {k: (fmt(v) if k != "site_ok" else v) for k, v in timetable_data.site_status().items()},
            "loaded": timetable_data.is_loaded(),
        },
    )


async def _start_sync():
    from bot import tt_sync

    async def _run():
        try:
            await tt_sync.sync(force_download=True)
        except Exception as e:
            await db.log_error("tt_sync_manual", str(e))

    if not tt_sync._lock.locked():
        asyncio.create_task(_run())


@app.post("/data/sync-now")
async def sync_now(user: str = Depends(require_permission("data", LEVEL_EDIT))):
    """TSUE'dan jadvalni (bitta JSON so'rov) hozir yuklab, barcha
    fayllarni va o'zgarishlarni sinxronlaydi."""
    await _start_sync()
    return RedirectResponse(url="/data?sync=1", status_code=303)


# Eski skanerlash tugmalari (saytni minglab marta ochar edi) endi
# xavfsiz JSON sinxronlashni ishga tushiradi.
@app.post("/data/sync-groups-now")
@app.post("/data/scan-now")
@app.post("/data/scan-teachers-now")
@app.post("/data/toggle-scanning")
async def legacy_scan_routes(user: str = Depends(require_permission("data", LEVEL_EDIT))):
    await _start_sync()
    return RedirectResponse(url="/data?sync=1", status_code=303)


@app.get("/file/{name}", response_class=HTMLResponse)
async def view_file(request: Request, name: str, user: str = Depends(require_permission("data", LEVEL_VIEW))):
    if name not in FILES:
        raise HTTPException(404, "Bunday fayl yo'q")
    path = FILES[name]
    content = path.read_text(encoding="utf-8") if path.exists() else "{}"
    return templates.TemplateResponse(
        request,
        "edit_file.html",
        {
            "active": "data",
            "name": name,
            "title": FILE_TITLES.get(name, name),
            "content": content,
            "error": None,
        },
    )


@app.post("/file/{name}", response_class=HTMLResponse)
async def save_file(
    request: Request,
    name: str,
    content: str = Form(...),
    user: str = Depends(require_permission("data", LEVEL_EDIT)),
):
    if name not in FILES:
        raise HTTPException(404, "Bunday fayl yo'q")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        return templates.TemplateResponse(
            request,
            "edit_file.html",
            {
                "active": "data",
                "name": name,
                "title": FILE_TITLES.get(name, name),
                "content": content,
                "error": f"JSON xatosi: {e}",
            },
        )

    path = FILES[name]
    path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    data_loader.store.reload()

    return RedirectResponse(url=f"/file/{name}?saved=1", status_code=303)


@app.post("/file/{name}/upload")
async def upload_file(
    name: str,
    file: UploadFile = File(...),
    user: str = Depends(require_permission("data", LEVEL_EDIT)),
):
    if name not in FILES:
        raise HTTPException(404, "Bunday fayl yo'q")

    raw = await file.read()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"Yuklangan fayl to'g'ri JSON emas: {e}")

    path = FILES[name]
    path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    data_loader.store.reload()

    return RedirectResponse(url=f"/file/{name}?saved=1", status_code=303)


@app.post("/reload")
async def reload_data(user: str = Depends(require_permission("data", LEVEL_EDIT))):
    data_loader.store.reload()
    return RedirectResponse(url="/data?reloaded=1", status_code=303)


# ---------------------------------------------------------------- #
# Sozlamalar: Sarlavha nomlari / Ierarxiya
# ---------------------------------------------------------------- #

@app.get("/hierarchy", response_class=HTMLResponse)
async def view_hierarchy(request: Request, user: str = Depends(require_permission("hierarchy", LEVEL_VIEW))):
    cfg = data_loader.load_hierarchy_config()
    return templates.TemplateResponse(
        request,
        "edit_hierarchy.html",
        {"active": "hierarchy", "content": json.dumps(cfg, ensure_ascii=False, indent=2), "error": None},
    )


@app.post("/hierarchy", response_class=HTMLResponse)
async def save_hierarchy(request: Request, content: str = Form(...), user: str = Depends(require_permission("hierarchy", LEVEL_EDIT))):
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        return templates.TemplateResponse(
            request,
            "edit_hierarchy.html",
            {"active": "hierarchy", "content": content, "error": f"JSON xatosi: {e}"},
        )

    data_loader.save_hierarchy_config(parsed)
    data_loader.store.reload()
    return RedirectResponse(url="/hierarchy?saved=1", status_code=303)


@app.get("/names", response_class=HTMLResponse)
async def view_names(request: Request, user: str = Depends(require_permission("titles", LEVEL_VIEW))):
    names = data_loader.load_display_names()
    return templates.TemplateResponse(
        request,
        "edit_names.html",
        {"active": "names", "content": json.dumps(names, ensure_ascii=False, indent=2), "error": None},
    )


@app.post("/names", response_class=HTMLResponse)
async def save_names(request: Request, content: str = Form(...), user: str = Depends(require_permission("titles", LEVEL_EDIT))):
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("Yuqori darajadagi qiymat dict (obyekt) bo'lishi kerak")
    except (json.JSONDecodeError, ValueError) as e:
        return templates.TemplateResponse(
            request,
            "edit_names.html",
            {"active": "names", "content": content, "error": f"Xatolik: {e}"},
        )

    data_loader.save_display_names(parsed)
    data_loader.store.reload()
    return RedirectResponse(url="/names?saved=1", status_code=303)


# ---------------------------------------------------------------- #
# Foydalanuvchilar
# ---------------------------------------------------------------- #

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, page: int = 0, q: str = "", user: str = Depends(require_permission("users", LEVEL_VIEW))):
    page_size = 20
    users, total = await db.get_users(page=page, page_size=page_size, search=q)
    has_next = (page + 1) * page_size < total
    return templates.TemplateResponse(
        request,
        "users.html",
        {
            "active": "users",
            "users": users,
            "total": total,
            "page": page,
            "has_next": has_next,
            "search": q,
        },
    )


@app.post("/users/{user_id}/toggle-block")
async def toggle_block(
    user_id: int,
    q: str = Form(""),
    page: int = Form(0),
    user: str = Depends(require_permission("users", LEVEL_EDIT)),
):
    currently = await db.is_blocked(user_id)
    await db.set_blocked(user_id, not currently)
    return RedirectResponse(url=f"/users?page={page}&q={q}", status_code=303)


@app.get("/users/{user_id}/chat", response_class=HTMLResponse)
async def user_chat_page(request: Request, user_id: int, ctx: str = "users", user: str = Depends(require_any_permission(["users", "support"], LEVEL_VIEW))):
    u = await db.get_user(user_id)
    if not u:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    messages = await db.get_chat_messages(user_id)
    display_name = (u.get("first_name") or "") + " " + (u.get("last_name") or "")
    display_name = display_name.strip() or (f"@{u['username']}" if u.get("username") else str(user_id))
    back_url = "/support" if ctx == "support" else "/users"
    back_label = "🛠 Texnik bo'lim" if ctx == "support" else "👥 Foydalanuvchilar"
    return templates.TemplateResponse(
        request,
        "user_chat.html",
        {
            "active": "support" if ctx == "support" else "users",
            "user": u,
            "messages": messages,
            "display_name": display_name,
            "error": None,
            "ctx": ctx,
            "back_url": back_url,
            "back_label": back_label,
        },
    )


@app.post("/users/{user_id}/chat/send")
async def user_chat_send(
    user_id: int,
    text: str = Form(""),
    ctx: str = Form("users"),
    photo: UploadFile | None = File(None),
    video: UploadFile | None = File(None),
    document: UploadFile | None = File(None),
    user: str = Depends(require_any_permission(["users", "support"], LEVEL_EDIT)),
):
    from aiogram.types import BufferedInputFile

    bot = get_bot()
    try:
        if photo is not None and photo.filename:
            data = await photo.read()
            await bot.send_photo(user_id, BufferedInputFile(data, filename=photo.filename), caption=text or None)
        elif video is not None and video.filename:
            data = await video.read()
            await bot.send_video(user_id, BufferedInputFile(data, filename=video.filename), caption=text or None)
        elif document is not None and document.filename:
            data = await document.read()
            await bot.send_document(user_id, BufferedInputFile(data, filename=document.filename), caption=text or None)
        elif text.strip():
            await bot.send_message(user_id, text)
        else:
            raise HTTPException(400, "Xabar matni, rasm, video yoki fayldan kamida bittasini kiriting.")
        # Eslatma: yuborilgan xabarni chat_messages jadvaliga yozish
        # endi qo'lda emas - bot/chat_log_middleware.py orqali
        # AVTOMATIK bajariladi (bot.send_* qanday chaqirilishidan
        # qat'iy nazar).
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Xabar yuborib bo'lmadi: {e}")
    return RedirectResponse(url=f"/users/{user_id}/chat?ctx={ctx}", status_code=303)


@app.get("/media/{file_id}")
async def get_media(file_id: str, user: str = Depends(require_any_permission(["users", "support", "groups"], LEVEL_VIEW))):
    """Telegram'da foydalanuvchiga yuborilgan/undan kelgan rasm, video
    yoki faylni (file_id orqali) admin panelda ko'rsatish/yuklab olish
    uchun oqim (stream) sifatida qaytaradi. Fayl serverimizda
    saqlanmaydi - har safar Telegramdan to'g'ridan-to'g'ri olinadi."""
    import mimetypes

    from fastapi.responses import StreamingResponse

    bot = get_bot()
    try:
        tg_file = await bot.get_file(file_id)
        buf = await bot.download_file(tg_file.file_path)
    except Exception as e:
        raise HTTPException(404, f"Fayl topilmadi yoki eskirgan: {e}")

    content_type = mimetypes.guess_type(tg_file.file_path or "")[0] or "application/octet-stream"
    filename = (tg_file.file_path or "fayl").rsplit("/", 1)[-1]
    return StreamingResponse(
        buf,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# ---------------------------------------------------------------- #
# ⭐ Xizmat reytingi (dars jadvalini birinchi ko'rgandan keyin
# so'raladigan 1-5 yulduzli baholash)
# ---------------------------------------------------------------- #

@app.get("/ratings", response_class=HTMLResponse)
async def ratings_page(request: Request, page: int = 0, user: str = Depends(require_permission("ratings", LEVEL_VIEW))):
    page_size = 20
    stats = await db.get_rating_stats()
    ratings, total = await db.get_ratings_list(page=page, page_size=page_size)
    has_next = (page + 1) * page_size < total

    max_bucket = max(stats["distribution"].values()) if stats["distribution"] else 0

    return templates.TemplateResponse(
        request,
        "ratings.html",
        {
            "active": "ratings",
            "stats": stats,
            "max_bucket": max_bucket,
            "ratings": ratings,
            "total": total,
            "page": page,
            "has_next": has_next,
        },
    )


# ---------------------------------------------------------------- #
# 🛠 Texnik bo'lim (foydalanuvchilar bilan yozishmalar ro'yxati -
# "⭐ Xizmat reytingi" xabaridagi "Texnik bo'lim bilan bog'lanish"
# tugmasidan keyin yozilgan, va boshqa har qanday xabarlar shu yerda
# ko'rinadi, chunki botda yagona matnli murojaat kanali shu)
# ---------------------------------------------------------------- #

@app.get("/support", response_class=HTMLResponse)
async def support_page(request: Request, page: int = 0, user: str = Depends(require_permission("support", LEVEL_VIEW))):
    page_size = 20
    stats = await db.get_support_stats()
    threads, total = await db.get_support_threads(page=page, page_size=page_size)
    has_next = (page + 1) * page_size < total

    for t in threads:
        display_name = ((t.get("first_name") or "") + " " + (t.get("last_name") or "")).strip()
        t["display_name"] = display_name or (f"@{t['username']}" if t.get("username") else str(t["user_id"]))

    return templates.TemplateResponse(
        request,
        "support.html",
        {
            "active": "support",
            "stats": stats,
            "threads": threads,
            "total": total,
            "page": page,
            "has_next": has_next,
        },
    )


# ---------------------------------------------------------------- #
# Guruhlar (avtomatik jadval obunalari)
# ---------------------------------------------------------------- #

_group_broadcast_status = None
_group_broadcast_error = None

DAY_LABELS_SHORT_MAP = {
    "mon": "Dush", "tue": "Sesh", "wed": "Chor", "thu": "Pay",
    "fri": "Juma", "sat": "Shan", "sun": "Yaksh",
}


def _format_days(days_json: str) -> str:
    try:
        codes = json.loads(days_json or "[]")
    except json.JSONDecodeError:
        codes = []
    return ", ".join(DAY_LABELS_SHORT_MAP.get(c, c) for c in codes) or "-"


@app.get("/groups", response_class=HTMLResponse)
async def groups_page(request: Request, user: str = Depends(require_permission("groups", LEVEL_VIEW))):
    global _group_broadcast_status, _group_broadcast_error
    raw_groups = await db.get_group_subscriptions()
    for g in raw_groups:
        g["days_display"] = _format_days(g["days"])
    active_count = len([g for g in raw_groups if g["is_active"]])

    status = _group_broadcast_status
    error = _group_broadcast_error
    _group_broadcast_status = None
    _group_broadcast_error = None

    return templates.TemplateResponse(
        request,
        "groups.html",
        {
            "active": "groups",
            "groups": raw_groups,
            "active_group_count": active_count,
            "group_broadcast_status": status,
            "group_broadcast_error": error,
        },
    )


@app.post("/groups/{chat_id}/toggle")
async def group_toggle(chat_id: int, user: str = Depends(require_permission("groups", LEVEL_EDIT))):
    all_groups = await db.get_group_subscriptions()
    subs = {g["chat_id"]: g for g in all_groups}
    current = subs.get(chat_id)
    if current:
        await db.set_group_active(chat_id, not current["is_active"])
    return RedirectResponse(url="/groups", status_code=303)


@app.post("/groups/{chat_id}/delete")
async def group_delete(chat_id: int, user: str = Depends(require_permission("groups", LEVEL_EDIT))):
    await db.delete_group_subscription(chat_id)
    return RedirectResponse(url="/groups", status_code=303)


@app.get("/groups/{chat_id}/chat", response_class=HTMLResponse)
async def group_chat_page(request: Request, chat_id: int, user: str = Depends(require_permission("groups", LEVEL_VIEW))):
    """Berilgan guruh chatidagi yozishmani (bot qabul qilgan/yuborgan
    xabarlar) ko'rsatadi - xuddi "Foydalanuvchilar -> Yozish" sahifasi
    kabi, faqat bu safar bitta odam emas, balki bitta GURUH bilan."""
    all_groups = await db.get_group_subscriptions()
    group = next((g for g in all_groups if g["chat_id"] == chat_id), None)
    if not group:
        raise HTTPException(404, "Guruh topilmadi")
    messages = await db.get_group_chat_messages(chat_id)
    return templates.TemplateResponse(
        request,
        "group_chat.html",
        {
            "active": "groups",
            "group": group,
            "messages": messages,
            "error": None,
        },
    )


@app.post("/groups/{chat_id}/chat/send")
async def group_chat_send(
    chat_id: int,
    text: str = Form(""),
    photo: UploadFile | None = File(None),
    video: UploadFile | None = File(None),
    document: UploadFile | None = File(None),
    user: str = Depends(require_permission("groups", LEVEL_EDIT)),
):
    from aiogram.types import BufferedInputFile

    bot = get_bot()
    try:
        if photo is not None and photo.filename:
            data = await photo.read()
            await bot.send_photo(chat_id, BufferedInputFile(data, filename=photo.filename), caption=text or None)
        elif video is not None and video.filename:
            data = await video.read()
            await bot.send_video(chat_id, BufferedInputFile(data, filename=video.filename), caption=text or None)
        elif document is not None and document.filename:
            data = await document.read()
            await bot.send_document(chat_id, BufferedInputFile(data, filename=document.filename), caption=text or None)
        elif text.strip():
            await bot.send_message(chat_id, text)
        else:
            raise HTTPException(400, "Xabar matni, rasm, video yoki fayldan kamida bittasini kiriting.")
        # Eslatma: yuborilgan xabarni group_chat_messages jadvaliga
        # yozish qo'lda emas - bot/chat_log_middleware.py orqali
        # AVTOMATIK bajariladi.
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Xabar yuborib bo'lmadi: {e}")
    return RedirectResponse(url=f"/groups/{chat_id}/chat", status_code=303)


async def _run_group_broadcast(
    chat_ids: list,
    text: str,
    photo_bytes: bytes | None, photo_filename: str | None,
    video_bytes: bytes | None, video_filename: str | None,
    doc_bytes: bytes | None, doc_filename: str | None,
):
    global _group_broadcast_status
    from aiogram.types import BufferedInputFile

    bot = get_bot()
    sent, failed = 0, 0

    for chat_id in chat_ids:
        try:
            if photo_bytes:
                photo = BufferedInputFile(photo_bytes, filename=photo_filename or "photo.jpg")
                await bot.send_photo(chat_id, photo=photo, caption=text or None)
            elif video_bytes:
                video = BufferedInputFile(video_bytes, filename=video_filename or "video.mp4")
                await bot.send_video(chat_id, video=video, caption=text or None)
            elif doc_bytes:
                doc = BufferedInputFile(doc_bytes, filename=doc_filename or "fayl")
                await bot.send_document(chat_id, document=doc, caption=text or None)
            elif text:
                await bot.send_message(chat_id, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.1)

    _group_broadcast_status = f"✅ Yuborildi: {sent} ta guruhga, ❌ xatolik: {failed} ta."


@app.post("/groups/broadcast")
async def groups_broadcast(
    request: Request,
    text: str = Form(""),
    selected_groups: list[str] = Form([]),
    photo: UploadFile | None = File(None),
    video: UploadFile | None = File(None),
    document: UploadFile | None = File(None),
    user: str = Depends(require_permission("groups", LEVEL_EDIT)),
):
    global _group_broadcast_status, _group_broadcast_error

    if not selected_groups:
        _group_broadcast_error = "Hech qanday guruh tanlanmadi - avval jadvaldan kerakli guruh(lar)ni belgilang."
        return RedirectResponse(url="/groups", status_code=303)

    if not text.strip() and not (photo and photo.filename) and not (video and video.filename) and not (document and document.filename):
        _group_broadcast_error = "Xabar matni, rasm, video yoki fayldan kamida bittasini kiriting."
        return RedirectResponse(url="/groups", status_code=303)

    chat_ids = [int(c) for c in selected_groups]

    photo_bytes = photo_filename = None
    if photo is not None and photo.filename:
        photo_bytes = await photo.read()
        photo_filename = photo.filename

    video_bytes = video_filename = None
    if video is not None and video.filename:
        video_bytes = await video.read()
        video_filename = video.filename

    doc_bytes = doc_filename = None
    if document is not None and document.filename:
        doc_bytes = await document.read()
        doc_filename = document.filename

    _group_broadcast_status = f"📤 Yuborish boshlandi ({len(chat_ids)} ta tanlangan guruhga)..."
    asyncio.create_task(_run_group_broadcast(
        chat_ids, text,
        photo_bytes, photo_filename,
        video_bytes, video_filename,
        doc_bytes, doc_filename,
    ))
    return RedirectResponse(url="/groups", status_code=303)


# ---------------------------------------------------------------- #
# Reklama yuborish
# ---------------------------------------------------------------- #

async def _run_broadcast(text: str, photo_bytes: bytes | None, photo_filename: str | None):
    global _last_broadcast_result
    from aiogram.types import BufferedInputFile

    bot = get_bot()
    user_ids = await db.get_all_user_ids(only_active=True)
    sent, failed = 0, 0

    for uid in user_ids:
        try:
            if photo_bytes:
                photo = BufferedInputFile(photo_bytes, filename=photo_filename or "photo.jpg")
                await bot.send_photo(uid, photo=photo, caption=text)
            else:
                await bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # Telegram flood-limitiga tushmaslik uchun

    _last_broadcast_result = {"sent": sent, "failed": failed, "total": len(user_ids)}


@app.get("/broadcast", response_class=HTMLResponse)
async def broadcast_page(request: Request, user: str = Depends(require_permission("broadcast", LEVEL_VIEW))):
    recipient_count = len(await db.get_all_user_ids(only_active=True))
    return templates.TemplateResponse(
        request,
        "broadcast.html",
        {
            "active": "broadcast",
            "recipient_count": recipient_count,
            "error": None,
            "status_message": None,
            "text": "",
            "last_result": _last_broadcast_result,
        },
    )


@app.post("/broadcast", response_class=HTMLResponse)
async def send_broadcast(
    request: Request,
    text: str = Form(...),
    photo: UploadFile | None = File(None),
    user: str = Depends(require_permission("broadcast", LEVEL_EDIT)),
):
    recipient_count = len(await db.get_all_user_ids(only_active=True))

    if recipient_count == 0:
        return templates.TemplateResponse(
            request,
            "broadcast.html",
            {
                "active": "broadcast",
                "recipient_count": 0,
                "error": "Hozircha hech qanday foydalanuvchi yo'q - yuborish uchun hech kim topilmadi.",
                "status_message": None,
                "text": text,
                "last_result": _last_broadcast_result,
            },
        )

    photo_bytes = None
    photo_filename = None
    if photo is not None and photo.filename:
        photo_bytes = await photo.read()
        photo_filename = photo.filename

    asyncio.create_task(_run_broadcast(text, photo_bytes, photo_filename))

    return templates.TemplateResponse(
        request,
        "broadcast.html",
        {
            "active": "broadcast",
            "recipient_count": recipient_count,
            "error": None,
            "status_message": (
                f"📤 Yuborish boshlandi ({recipient_count} ta foydalanuvchiga). "
                "Bir necha soniyadan keyin sahifani yangilab, natijani ko'rishingiz mumkin."
            ),
            "text": "",
            "last_result": _last_broadcast_result,
        },
    )


# ---------------------------------------------------------------- #
# Xatolar jurnali
# ---------------------------------------------------------------- #

@app.get("/errors", response_class=HTMLResponse)
async def errors_page(request: Request, user: str = Depends(require_permission("errors", LEVEL_VIEW))):
    errors = await db.get_recent_errors(limit=100)
    return templates.TemplateResponse(
        request, "errors.html", {"active": "errors", "errors": errors}
    )


# ---------------------------------------------------------------- #
# /start xabarini tahrirlash
# ---------------------------------------------------------------- #

@app.get("/start-message", response_class=HTMLResponse)
async def start_message_page(request: Request, user: str = Depends(require_permission("start_message", LEVEL_VIEW))):
    from bot import i18n

    current = await db.get_setting("start_message")
    return templates.TemplateResponse(
        request,
        "start_message.html",
        {
            "active": "start-message",
            "current": current,
            "default_text": i18n.t("welcome", "uz") + "\n\n---\n\n" + i18n.t("welcome", "ru"),
        },
    )


@app.post("/start-message", response_class=HTMLResponse)
async def save_start_message(
    text: str = Form(""),
    clear: str = Form(None),
    user: str = Depends(require_permission("start_message", LEVEL_EDIT)),
):
    if clear or not text.strip():
        await db.set_setting("start_message", "")
    else:
        await db.set_setting("start_message", text)
    return RedirectResponse(url="/start-message?saved=1", status_code=303)


# ---------------------------------------------------------------- #
# Kalendar: bot soatini sozlash va dars eslatmalari uchun saqlangan
# jadvallar (qarang: bot/reminders.py)
# ---------------------------------------------------------------- #

WEEKDAY_NAMES_UZ = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]


@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request, user: str = Depends(require_permission("calendar", LEVEL_VIEW))):
    from bot import reminders, timetable_data

    real_now = reminders.real_tashkent_now()
    bot_now = await reminders.bot_now()
    offset_active = abs((bot_now - real_now).total_seconds()) >= 60
    return templates.TemplateResponse(
        request,
        "calendar.html",
        {
            "active": "calendar",
            "error": request.query_params.get("error"),
            "real_now": real_now.strftime("%Y-%m-%d %H:%M"),
            "bot_now": bot_now.strftime("%Y-%m-%d %H:%M"),
            "bot_now_input": bot_now.strftime("%Y-%m-%dT%H:%M"),
            "weekday": WEEKDAY_NAMES_UZ[bot_now.weekday()],
            "week_letter": "AB"[timetable_data.week_index(bot_now.date())],
            "offset_active": offset_active,
            "target_count": len(await db.get_reminder_targets()),
            "snapshot_count": await db.count_schedule_snapshots(),
        },
    )


@app.post("/calendar")
async def calendar_set(
    target: str = Form(...),
    user: str = Depends(require_permission("calendar", LEVEL_EDIT)),
):
    import datetime
    from bot import reminders

    try:
        target_dt = datetime.datetime.fromisoformat(target)
    except ValueError:
        return RedirectResponse(url="/calendar?error=Sana+noto%27g%27ri+formatda", status_code=303)
    await reminders.set_bot_clock(target_dt)
    return RedirectResponse(url="/calendar?saved=1", status_code=303)


@app.post("/calendar/reset")
async def calendar_reset(user: str = Depends(require_permission("calendar", LEVEL_EDIT))):
    from bot import reminders

    await reminders.set_bot_clock(None)
    return RedirectResponse(url="/calendar?reset=1", status_code=303)


@app.post("/calendar/refresh")
async def calendar_refresh(user: str = Depends(require_permission("calendar", LEVEL_EDIT))):
    from bot import reminders

    async def _run():
        try:
            ok, total = await reminders.resnapshot_all()
            if ok < total:
                await db.log_error("calendar_refresh", f"{total} ta jadvaldan {ok} tasi qayta yuklandi.")
        except Exception as e:
            await db.log_error("calendar_refresh", str(e))

    reminders._background_tasks.add(task := asyncio.create_task(_run()))
    task.add_done_callback(reminders._background_tasks.discard)
    return RedirectResponse(url="/calendar?refresh=1", status_code=303)



# ---------------------------------------------------------------- #
# Zaxira: barcha ma'lumotni bitta zip faylda yuklab olish / tiklash.
# Faqat asosiy admin uchun.
# ---------------------------------------------------------------- #

BACKUP_FILES = [
    "bot_data.db", "guruhlar.json", "ustozlar.json", "xonalar.json",
    "boshxonalar.json", "display_names.json", "hierarchy_config.json",
    # TSUE jadvalining oxirgi yuklangan nusxasi. Server TSUE saytiga
    # ulana olmasa (IP bloklangan), shu faylni boshqa joydan (masalan
    # o'z kompyuteringizdan) olib, shu yerdan yuklash mumkin.
    "timetable_cache.json.gz",
]


@app.get("/backup", response_class=HTMLResponse)
async def backup_page(request: Request, user: str = Depends(require_super_admin)):
    files = []
    for name in BACKUP_FILES:
        path = config.DATA_DIR / name
        files.append({
            "name": name,
            "exists": path.exists(),
            "size_kb": round(path.stat().st_size / 1024, 1) if path.exists() else 0,
        })
    stats = await db.get_stats()
    return templates.TemplateResponse(
        request,
        "backup.html",
        {
            "active": "backup",
            "files": files,
            "users": stats.get("total_users", 0),
            "postgres": db.USE_POSTGRES,
            "data_dir": str(config.DATA_DIR),
            "result": request.query_params.get("result"),
            "error": request.query_params.get("error"),
        },
    )


@app.get("/backup/download")
async def backup_download(user: str = Depends(require_super_admin)):
    import datetime
    import io
    import tempfile
    import zipfile

    from fastapi.responses import Response

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if not db.USE_POSTGRES and config.DB_FILE.exists():
            with tempfile.TemporaryDirectory(dir=str(config.DATA_DIR)) as tmp:
                copy_path = os.path.join(tmp, "bot_data.db")
                await asyncio.to_thread(db.backup_sqlite_to, copy_path)
                zf.write(copy_path, "bot_data.db")
        for name in BACKUP_FILES[1:]:
            path = config.DATA_DIR / name
            if path.exists():
                zf.write(path, name)
    stamp = (datetime.datetime.utcnow() + datetime.timedelta(hours=5)).strftime("%Y-%m-%d_%H-%M")
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="tsue_bot_zaxira_{stamp}.zip"'},
    )


@app.post("/backup/restore")
async def backup_restore(file: UploadFile = File(...), user: str = Depends(require_super_admin)):
    import io
    import tempfile
    import urllib.parse
    import zipfile

    from bot import tt_sync

    raw = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return RedirectResponse(url="/backup?error=" + urllib.parse.quote("Fayl zip arxiv emas."), status_code=303)

    # Arxiv ichida fayllar "data/guruhlar.json" kabi papka ichida ham bo'lishi mumkin.
    members = {}
    for info in zf.infolist():
        base = os.path.basename(info.filename)
        if base in BACKUP_FILES and not info.is_dir():
            members[base] = info
    if not members:
        return RedirectResponse(url="/backup?error=" + urllib.parse.quote("Arxivda tanish fayl topilmadi."), status_code=303)

    restored = []
    try:
        # Avval JSON'lar to'g'ri ekanini tekshiramiz, keyin yozamiz.
        payloads = {}
        for name, info in members.items():
            data = zf.read(info)
            if name.endswith(".json"):
                json.loads(data.decode("utf-8"))
            elif name.endswith(".json.gz"):
                import gzip

                cached = json.loads(gzip.decompress(data).decode("utf-8"))
                if "raw" not in cached or "tt_num" not in cached:
                    raise ValueError("timetable_cache.json.gz noto'g'ri formatda.")
            payloads[name] = data
        if "bot_data.db" in payloads:
            if db.USE_POSTGRES:
                raise ValueError("Bot PostgreSQL bilan ishlayapti - SQLite bazani tiklab bo'lmaydi.")
            fd, tmp_path = tempfile.mkstemp(dir=str(config.DATA_DIR), suffix=".db")
            with os.fdopen(fd, "wb") as f:
                f.write(payloads["bot_data.db"])
            await db.restore_sqlite_from(tmp_path)
            restored.append("bot_data.db")
        for name, data in payloads.items():
            if name == "bot_data.db":
                continue
            tmp = config.DATA_DIR / (name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(config.DATA_DIR / name)
            restored.append(name)
    except Exception as e:
        return RedirectResponse(url="/backup?error=" + urllib.parse.quote(f"Tiklab bo'lmadi: {e}"), status_code=303)

    data_loader.store.reload()
    if "timetable_cache.json.gz" in restored:
        # Yangi jadval nusxasi keyingi so'rovda diskdan qayta o'qilsin.
        from bot import timetable_data

        timetable_data._tt.index = {}
        timetable_data._tt.names = {}
        timetable_data._tt.failed_at = 0.0
    # Tiklangan fayllar joriy TSUE jadvali bilan qayta moslansin (saytga
    # yangi so'rovsiz - xotiradagi/keshdagi jadvaldan).
    tt_sync._synced_loaded_at = None
    asyncio.create_task(tt_sync.sync())
    return RedirectResponse(url="/backup?result=" + urllib.parse.quote(", ".join(restored)), status_code=303)


# ---------------------------------------------------------------- #
# Bir nechta admin - har biriga bo'lim-darajasida (granular) kirish
# huquqi berish mumkin (qarang: admin/permissions.py). Bu bo'limning
# o'zi HAR DOIM faqat asosiy (.env) adminga ochiq - qo'shimcha
# adminlarga hech qachon berilmaydi (privilege escalation'dan
# himoya).
# ---------------------------------------------------------------- #

def _admins_context(admins: list, error: str | None = None) -> dict:
    return {
        "active": "admins",
        "admins": admins,
        "super_admin": config.ADMIN_USERNAME,
        "sections": SECTIONS,
        "level_labels": LEVEL_LABELS,
        "level_none": LEVEL_NONE,
        "level_view": LEVEL_VIEW,
        "level_edit": LEVEL_EDIT,
        "error": error,
    }


def _permissions_from_form(form) -> dict:
    """`perm_<bolim_kaliti>` nomli forma maydonlaridan ('none'/'view'/
    'edit' qiymatlari bilan) huquqlar lug'atini yig'ib, tozalab
    qaytaradi."""
    raw = {key: form.get(f"perm_{key}", LEVEL_NONE) for key in SECTIONS}
    return normalize_permissions(raw)


@app.get("/admins", response_class=HTMLResponse)
async def admins_page(request: Request, user: str = Depends(require_super_admin)):
    admins = await db.get_all_admins()
    return templates.TemplateResponse(request, "admins.html", _admins_context(admins))


@app.post("/admins", response_class=HTMLResponse)
async def add_admin_route(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    user: str = Depends(require_super_admin),
):
    username = username.strip()
    form = await request.form()
    permissions = _permissions_from_form(form)

    if not username or not password:
        admins = await db.get_all_admins()
        return templates.TemplateResponse(
            request, "admins.html",
            _admins_context(admins, "Login va parol bo'sh bo'lmasligi kerak."),
        )
    if username == config.ADMIN_USERNAME:
        admins = await db.get_all_admins()
        return templates.TemplateResponse(
            request, "admins.html",
            _admins_context(admins, "Bu login asosiy admin uchun band."),
        )

    await db.add_admin(username, password, permissions)
    return RedirectResponse(url="/admins?added=1", status_code=303)


@app.post("/admins/{username}/delete")
async def delete_admin_route(username: str, user: str = Depends(require_super_admin)):
    await db.remove_admin(username)
    return RedirectResponse(url="/admins?deleted=1", status_code=303)


@app.post("/admins/{username}/permissions")
async def update_admin_permissions_route(
    request: Request,
    username: str,
    user: str = Depends(require_super_admin),
):
    """Mavjud qo'shimcha adminning bo'lim-darajasidagi huquqlarini
    (parolga tegmasdan) yangilaydi. Bu marshrut ham (yuqoridagi
    dependency orqali) faqat asosiy adminga ochiq."""
    form = await request.form()
    permissions = _permissions_from_form(form)
    await db.update_admin_permissions(username, permissions)
    return RedirectResponse(url="/admins?updated=1", status_code=303)


# ---------------------------------------------------------------- #
# Eski botdan ma'lumot import qilish
# ---------------------------------------------------------------- #

@app.get("/import", response_class=HTMLResponse)
async def import_page(request: Request, user: str = Depends(require_permission("import_legacy", LEVEL_VIEW))):
    return templates.TemplateResponse(
        request, "import.html", {"active": "import", "report": None, "error": None}
    )


@app.post("/import", response_class=HTMLResponse)
async def import_old_bot(
    request: Request,
    file: UploadFile = File(...),
    user: str = Depends(require_permission("import_legacy", LEVEL_EDIT)),
):
    import tempfile
    import os as _os
    from bot import migration

    raw = await file.read()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name

        report = await migration.migrate_from_sqlite(tmp_path)

        return templates.TemplateResponse(
            request, "import.html", {"active": "import", "report": report, "error": None}
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "import.html",
            {"active": "import", "report": None, "error": f"Import xatosi: {e}"},
        )
    finally:
        if tmp_path and _os.path.exists(tmp_path):
            _os.remove(tmp_path)


# ---------------------------------------------------------------- #
# Yangi topilgan guruh/o'qituvchi/xona
# ---------------------------------------------------------------- #

@app.get("/new-items", response_class=HTMLResponse)
async def new_items_page(request: Request, user: str = Depends(require_permission("new_items", LEVEL_VIEW))):
    all_items = await db.get_discovered_items()
    items_by_type = {"guruh": [], "ustoz": [], "xona": []}
    for item in all_items:
        items_by_type.setdefault(item["item_type"], []).append(item)
    return templates.TemplateResponse(
        request, "new_items.html", {"active": "new-items", "items_by_type": items_by_type}
    )


@app.post("/new-items/{item_id}/dismiss")
async def dismiss_new_item(item_id: int, user: str = Depends(require_permission("new_items", LEVEL_EDIT))):
    await db.clear_discovered_item(item_id)
    return RedirectResponse(url="/new-items", status_code=303)


@app.post("/new-items/clear/{item_type}")
async def clear_new_items(item_type: str, user: str = Depends(require_permission("new_items", LEVEL_EDIT))):
    await db.clear_all_discovered_items(item_type)
    return RedirectResponse(url="/new-items", status_code=303)

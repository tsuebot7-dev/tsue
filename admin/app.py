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
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import config, data_loader, db  # noqa: E402
from bot.bot_instance import get_bot  # noqa: E402

app = FastAPI(title="TSUE Bot Admin")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
security = HTTPBasic()

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
    "free_rooms_search": "Bo'sh xona qidiruvi",
}

_last_broadcast_result = None


async def check_auth(credentials: HTTPBasicCredentials = Depends(security)):
    # 1) Asosiy (.env / Railway Variables) admin
    correct_username = secrets.compare_digest(credentials.username, config.ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, config.ADMIN_PASSWORD)
    if correct_username and correct_password:
        return credentials.username

    # 2) Baza orqali qo'shilgan qo'shimcha adminlar
    if await db.verify_admin_credentials(credentials.username, credentials.password):
        return credentials.username

    raise HTTPException(
        status_code=401,
        detail="Login yoki parol noto'g'ri",
        headers={"WWW-Authenticate": "Basic"},
    )


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


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: str = Depends(check_auth)):
    stats = await db.get_stats()
    stats_files = {key: file_stats(path) for key, path in FILES.items()}
    top_groups = await db.get_top_viewed("view_guruh", limit=10)
    top_faculties = await db.get_top_viewed("view_guruh_top", limit=10)
    display_names = data_loader.load_display_names()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active": "dashboard",
            "stats": stats,
            "event_labels": EVENT_LABELS,
            "file_stats": stats_files,
            "titles": FILE_TITLES,
            "top_groups": top_groups,
            "top_faculties": top_faculties,
            "names": display_names,
        },
    )


# ---------------------------------------------------------------- #
# Ma'lumotlarni yangilash
# ---------------------------------------------------------------- #

@app.get("/data", response_class=HTMLResponse)
async def data_page(request: Request, user: str = Depends(check_auth)):
    import datetime
    from bot import room_scraper, teacher_scraper

    stats = {key: file_stats(path) for key, path in FILES.items()}

    scan_status = await db.get_setting("room_scan_status", "never")
    scan_progress = await db.get_setting("room_scan_progress", "0")
    scan_total = await db.get_setting("room_scan_total", "0")
    finished_at = await db.get_setting("room_scan_finished_at")
    finished_display = "-"
    if finished_at:
        finished_display = datetime.datetime.fromtimestamp(float(finished_at)).strftime("%Y-%m-%d %H:%M")
    scan_stuck = await room_scraper.is_scan_stuck()

    teacher_scan_status = await db.get_setting("teacher_scan_status", "never")
    teacher_scan_progress = await db.get_setting("teacher_scan_progress", "0")
    teacher_scan_total = await db.get_setting("teacher_scan_total", "0")
    teacher_scan_found = await db.get_setting("teacher_scan_found", "0")
    teacher_finished_at = await db.get_setting("teacher_scan_finished_at")
    teacher_finished_display = "-"
    if teacher_finished_at:
        teacher_finished_display = datetime.datetime.fromtimestamp(
            float(teacher_finished_at)
        ).strftime("%Y-%m-%d %H:%M")
    teacher_scan_stuck = await teacher_scraper.is_scan_stuck()

    return templates.TemplateResponse(
        request,
        "data.html",
        {
            "active": "data",
            "files": FILES,
            "titles": FILE_TITLES,
            "stats": stats,
            "scan_status": scan_status,
            "scan_progress": scan_progress,
            "scan_total": scan_total,
            "scan_finished_at_display": finished_display,
            "scan_stuck": scan_stuck,
            "scan_interval_days": config.ROOM_SCAN_INTERVAL_DAYS,
            "teacher_scan_status": teacher_scan_status,
            "teacher_scan_progress": teacher_scan_progress,
            "teacher_scan_total": teacher_scan_total,
            "teacher_scan_found": teacher_scan_found,
            "teacher_scan_finished_at_display": teacher_finished_display,
            "teacher_scan_interval_days": config.TEACHER_SCAN_INTERVAL_DAYS,
            "teacher_scan_end": config.TEACHER_SCAN_END,
            "teacher_scan_stuck": teacher_scan_stuck,
        },
    )


@app.post("/data/scan-now")
async def scan_now(user: str = Depends(check_auth)):
    from bot import room_scraper  # dinamik import, aylanma importni oldini olish uchun

    status = await db.get_setting("room_scan_status")
    if status not in ("running", "cooldown") or await room_scraper.is_scan_stuck():
        asyncio.create_task(room_scraper.scan_all_rooms())
    return RedirectResponse(url="/data", status_code=303)


@app.post("/data/scan-teachers-now")
async def scan_teachers_now(user: str = Depends(check_auth)):
    from bot import teacher_scraper

    status = await db.get_setting("teacher_scan_status")
    if status not in ("running", "cooldown") or await teacher_scraper.is_scan_stuck():
        asyncio.create_task(teacher_scraper.scan_all_teachers())
    return RedirectResponse(url="/data", status_code=303)


@app.get("/file/{name}", response_class=HTMLResponse)
async def view_file(request: Request, name: str, user: str = Depends(check_auth)):
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
    user: str = Depends(check_auth),
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
    user: str = Depends(check_auth),
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
async def reload_data(user: str = Depends(check_auth)):
    data_loader.store.reload()
    return RedirectResponse(url="/data?reloaded=1", status_code=303)


# ---------------------------------------------------------------- #
# Sozlamalar: Sarlavha nomlari / Ierarxiya
# ---------------------------------------------------------------- #

@app.get("/hierarchy", response_class=HTMLResponse)
async def view_hierarchy(request: Request, user: str = Depends(check_auth)):
    cfg = data_loader.load_hierarchy_config()
    return templates.TemplateResponse(
        request,
        "edit_hierarchy.html",
        {"active": "hierarchy", "content": json.dumps(cfg, ensure_ascii=False, indent=2), "error": None},
    )


@app.post("/hierarchy", response_class=HTMLResponse)
async def save_hierarchy(request: Request, content: str = Form(...), user: str = Depends(check_auth)):
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
async def view_names(request: Request, user: str = Depends(check_auth)):
    names = data_loader.load_display_names()
    return templates.TemplateResponse(
        request,
        "edit_names.html",
        {"active": "names", "content": json.dumps(names, ensure_ascii=False, indent=2), "error": None},
    )


@app.post("/names", response_class=HTMLResponse)
async def save_names(request: Request, content: str = Form(...), user: str = Depends(check_auth)):
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
async def users_page(request: Request, page: int = 0, q: str = "", user: str = Depends(check_auth)):
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
    user: str = Depends(check_auth),
):
    currently = await db.is_blocked(user_id)
    await db.set_blocked(user_id, not currently)
    return RedirectResponse(url=f"/users?page={page}&q={q}", status_code=303)


@app.get("/users/{user_id}/chat", response_class=HTMLResponse)
async def user_chat_page(request: Request, user_id: int, user: str = Depends(check_auth)):
    u = await db.get_user(user_id)
    if not u:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    messages = await db.get_chat_messages(user_id)
    display_name = (u.get("first_name") or "") + " " + (u.get("last_name") or "")
    display_name = display_name.strip() or (f"@{u['username']}" if u.get("username") else str(user_id))
    return templates.TemplateResponse(
        request,
        "user_chat.html",
        {
            "active": "users",
            "user": u,
            "messages": messages,
            "display_name": display_name,
            "error": None,
        },
    )


@app.post("/users/{user_id}/chat/send")
async def user_chat_send(user_id: int, text: str = Form(...), user: str = Depends(check_auth)):
    bot = get_bot()
    try:
        await bot.send_message(user_id, text)
        await db.log_chat_message(user_id, "out", text)
    except Exception as e:
        raise HTTPException(400, f"Xabar yuborib bo'lmadi: {e}")
    return RedirectResponse(url=f"/users/{user_id}/chat", status_code=303)


# ---------------------------------------------------------------- #
# Guruhlar (avtomatik jadval obunalari)
# ---------------------------------------------------------------- #

_group_broadcast_status = None

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
async def groups_page(request: Request, user: str = Depends(check_auth)):
    global _group_broadcast_status
    raw_groups = await db.get_group_subscriptions()
    for g in raw_groups:
        g["days_display"] = _format_days(g["days"])
    active_count = len([g for g in raw_groups if g["is_active"]])

    status = _group_broadcast_status
    _group_broadcast_status = None

    return templates.TemplateResponse(
        request,
        "groups.html",
        {
            "active": "groups",
            "groups": raw_groups,
            "active_group_count": active_count,
            "group_broadcast_status": status,
        },
    )


@app.post("/groups/{chat_id}/toggle")
async def group_toggle(chat_id: int, user: str = Depends(check_auth)):
    all_groups = await db.get_group_subscriptions()
    subs = {g["chat_id"]: g for g in all_groups}
    current = subs.get(chat_id)
    if current:
        await db.set_group_active(chat_id, not current["is_active"])
    return RedirectResponse(url="/groups", status_code=303)


@app.post("/groups/{chat_id}/delete")
async def group_delete(chat_id: int, user: str = Depends(check_auth)):
    await db.delete_group_subscription(chat_id)
    return RedirectResponse(url="/groups", status_code=303)


async def _run_group_broadcast(text: str):
    global _group_broadcast_status
    bot = get_bot()
    groups = await db.get_group_subscriptions(active_only=True)
    sent, failed = 0, 0
    for g in groups:
        try:
            await bot.send_message(g["chat_id"], text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    _group_broadcast_status = f"✅ Yuborildi: {sent} ta guruhga, ❌ xatolik: {failed} ta."


@app.post("/groups/broadcast")
async def groups_broadcast(text: str = Form(...), user: str = Depends(check_auth)):
    global _group_broadcast_status
    _group_broadcast_status = "📤 Yuborish boshlandi..."
    asyncio.create_task(_run_group_broadcast(text))
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
async def broadcast_page(request: Request, user: str = Depends(check_auth)):
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
    user: str = Depends(check_auth),
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
async def errors_page(request: Request, user: str = Depends(check_auth)):
    errors = await db.get_recent_errors(limit=100)
    return templates.TemplateResponse(
        request, "errors.html", {"active": "errors", "errors": errors}
    )


# ---------------------------------------------------------------- #
# /start xabarini tahrirlash
# ---------------------------------------------------------------- #

@app.get("/start-message", response_class=HTMLResponse)
async def start_message_page(request: Request, user: str = Depends(check_auth)):
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
    user: str = Depends(check_auth),
):
    if clear or not text.strip():
        await db.set_setting("start_message", "")
    else:
        await db.set_setting("start_message", text)
    return RedirectResponse(url="/start-message?saved=1", status_code=303)


# ---------------------------------------------------------------- #
# Bir nechta admin
# ---------------------------------------------------------------- #

@app.get("/admins", response_class=HTMLResponse)
async def admins_page(request: Request, user: str = Depends(check_auth)):
    admins = await db.get_all_admins()
    return templates.TemplateResponse(
        request,
        "admins.html",
        {
            "active": "admins",
            "admins": admins,
            "super_admin": config.ADMIN_USERNAME,
            "error": None,
        },
    )


@app.post("/admins", response_class=HTMLResponse)
async def add_admin_route(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    user: str = Depends(check_auth),
):
    username = username.strip()
    if not username or not password:
        admins = await db.get_all_admins()
        return templates.TemplateResponse(
            request,
            "admins.html",
            {
                "active": "admins",
                "admins": admins,
                "super_admin": config.ADMIN_USERNAME,
                "error": "Login va parol bo'sh bo'lmasligi kerak.",
            },
        )
    if username == config.ADMIN_USERNAME:
        admins = await db.get_all_admins()
        return templates.TemplateResponse(
            request,
            "admins.html",
            {
                "active": "admins",
                "admins": admins,
                "super_admin": config.ADMIN_USERNAME,
                "error": "Bu login asosiy admin uchun band.",
            },
        )

    await db.add_admin(username, password)
    return RedirectResponse(url="/admins?added=1", status_code=303)


@app.post("/admins/{username}/delete")
async def delete_admin_route(username: str, user: str = Depends(check_auth)):
    await db.remove_admin(username)
    return RedirectResponse(url="/admins?deleted=1", status_code=303)


# ---------------------------------------------------------------- #
# Eski botdan ma'lumot import qilish
# ---------------------------------------------------------------- #

@app.get("/import", response_class=HTMLResponse)
async def import_page(request: Request, user: str = Depends(check_auth)):
    return templates.TemplateResponse(
        request, "import.html", {"active": "import", "report": None, "error": None}
    )


@app.post("/import", response_class=HTMLResponse)
async def import_old_bot(
    request: Request,
    file: UploadFile = File(...),
    user: str = Depends(check_auth),
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

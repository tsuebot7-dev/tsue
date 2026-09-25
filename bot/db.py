"""
Foydalanuvchilar, guruh obunalari, chat yozishmalari va sozlamalar
shu yerda saqlanadi.

IKKI BACKEND QO'LLAB-QUVVATLANADI:
  - Agar DATABASE_URL berilgan bo'lsa (Railway'da PostgreSQL
    qo'shilganda avtomatik beriladi) -> PostgreSQL (asyncpg orqali,
    connection pool bilan). Bu Railway'ning ephemeral fayl tizimi
    muammosini butunlay hal qiladi - ma'lumotlar alohida baza
    serverida saqlanadi, qayta deploy qilinganda yo'qolmaydi.
  - Aks holda (masalan lokal kompyuterda test qilishda) -> oddiy
    SQLite fayl (bot_data.db). Hech qanday qo'shimcha o'rnatishga
    hojat yo'q.

Barcha funksiyalar ASYNC (await bilan chaqiriladi), chunki
asyncpg to'liq asinxron ishlaydi va bot/admin panel ham asinxron
(aiogram + FastAPI).
"""

import datetime
import hashlib
import json
import os
import sqlite3
import threading

from . import config

USE_POSTGRES = bool(config.DATABASE_URL)

if USE_POSTGRES:
    import asyncpg

_pg_pool = None  # asyncpg.Pool

_sqlite_lock = threading.Lock()
_sqlite_conn: sqlite3.Connection | None = None


def _get_sqlite_conn() -> sqlite3.Connection:
    global _sqlite_conn
    if _sqlite_conn is None:
        _sqlite_conn = sqlite3.connect(str(config.DB_FILE), check_same_thread=False)
        _sqlite_conn.row_factory = sqlite3.Row
    return _sqlite_conn


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


# ================================================================ #
# Baza ulanishini ishga tushirish / jadvallarni yaratish
# ================================================================ #

async def init_db():
    if USE_POSTGRES:
        global _pg_pool
        if _pg_pool is not None:
            return  # allaqachon ishga tushirilgan (masalan run.py bot+admin birga)
        _pg_pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=1, max_size=5)
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    first_seen TIMESTAMP,
                    last_seen TIMESTAMP,
                    message_count INTEGER DEFAULT 0,
                    is_blocked BOOLEAN DEFAULT FALSE
                );

                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    event_type TEXT,
                    detail TEXT,
                    created_at TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
                CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);

                CREATE TABLE IF NOT EXISTS saved_schedules (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    feature TEXT,
                    name TEXT,
                    url TEXT,
                    saved_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS group_subscriptions (
                    chat_id BIGINT PRIMARY KEY,
                    chat_title TEXT,
                    feature TEXT,
                    name TEXT,
                    url TEXT,
                    days TEXT,
                    post_time TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_by BIGINT,
                    created_at TIMESTAMP,
                    last_sent_date TEXT
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    direction TEXT,
                    text TEXT,
                    created_at TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_messages(user_id);

                CREATE TABLE IF NOT EXISTS group_chat_messages (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT,
                    direction TEXT,
                    sender_user_id BIGINT,
                    sender_name TEXT,
                    text TEXT,
                    msg_type TEXT DEFAULT 'text',
                    file_id TEXT,
                    created_at TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_group_chat_chat_id ON group_chat_messages(chat_id);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS group_snapshots (
                    group_name TEXT PRIMARY KEY,
                    snapshot TEXT,
                    updated_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS error_logs (
                    id SERIAL PRIMARY KEY,
                    context TEXT,
                    message TEXT,
                    created_at TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_error_created ON error_logs(created_at);

                CREATE TABLE IF NOT EXISTS admins (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT,
                    created_at TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS discovered_items (
                    id SERIAL PRIMARY KEY,
                    item_type TEXT,
                    name TEXT,
                    url TEXT,
                    discovered_at TIMESTAMP,
                    UNIQUE(item_type, name)
                );

                CREATE TABLE IF NOT EXISTS ratings (
                    user_id BIGINT PRIMARY KEY,
                    rating INTEGER,
                    prompted_at TIMESTAMP,
                    rated_at TIMESTAMP
                );
                """
            )
            async with _pg_pool.acquire() as conn2:
                for col, coltype in [
                    ("default_feature", "TEXT"),
                    ("default_group_name", "TEXT"),
                    ("default_group_url", "TEXT"),
                    ("language", "TEXT DEFAULT 'uz'"),
                ]:
                    await conn2.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {coltype}")
                for col, coltype in [
                    ("msg_type", "TEXT DEFAULT 'text'"),
                    ("file_id", "TEXT"),
                ]:
                    await conn2.execute(f"ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS {col} {coltype}")
                for col, coltype in [
                    ("permissions", "TEXT DEFAULT '{}'"),
                ]:
                    await conn2.execute(f"ALTER TABLE admins ADD COLUMN IF NOT EXISTS {col} {coltype}")
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    first_seen TEXT,
                    last_seen TEXT,
                    message_count INTEGER DEFAULT 0,
                    is_blocked INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    event_type TEXT,
                    detail TEXT,
                    created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
                CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);

                CREATE TABLE IF NOT EXISTS saved_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    feature TEXT,
                    name TEXT,
                    url TEXT,
                    saved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS group_subscriptions (
                    chat_id INTEGER PRIMARY KEY,
                    chat_title TEXT,
                    feature TEXT,
                    name TEXT,
                    url TEXT,
                    days TEXT,
                    post_time TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_by INTEGER,
                    created_at TEXT,
                    last_sent_date TEXT
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    direction TEXT,
                    text TEXT,
                    created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_chat_user ON chat_messages(user_id);

                CREATE TABLE IF NOT EXISTS group_chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    direction TEXT,
                    sender_user_id INTEGER,
                    sender_name TEXT,
                    text TEXT,
                    msg_type TEXT DEFAULT 'text',
                    file_id TEXT,
                    created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_group_chat_chat_id ON group_chat_messages(chat_id);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS group_snapshots (
                    group_name TEXT PRIMARY KEY,
                    snapshot TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS error_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    context TEXT,
                    message TEXT,
                    created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_error_created ON error_logs(created_at);

                CREATE TABLE IF NOT EXISTS admins (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS discovered_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_type TEXT,
                    name TEXT,
                    url TEXT,
                    discovered_at TEXT,
                    UNIQUE(item_type, name)
                );

                CREATE TABLE IF NOT EXISTS ratings (
                    user_id INTEGER PRIMARY KEY,
                    rating INTEGER,
                    prompted_at TEXT,
                    rated_at TEXT
                );
                """
            )
            conn.commit()

            # SQLite'da ALTER TABLE ADD COLUMN IF NOT EXISTS yo'q, shuning
            # uchun avval qaysi ustunlar bor-yo'qligini tekshirib, faqat
            # yo'qlarini qo'shamiz (bir necha marta ishga tushirilsa ham
            # xato bermasligi uchun).
            existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
            for col, coltype in [
                ("default_feature", "TEXT"),
                ("default_group_name", "TEXT"),
                ("default_group_url", "TEXT"),
                ("language", "TEXT DEFAULT 'uz'"),
            ]:
                if col not in existing_cols:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {coltype}")

            existing_chat_cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
            for col, coltype in [
                ("msg_type", "TEXT DEFAULT 'text'"),
                ("file_id", "TEXT"),
            ]:
                if col not in existing_chat_cols:
                    conn.execute(f"ALTER TABLE chat_messages ADD COLUMN {col} {coltype}")

            existing_admin_cols = {row[1] for row in conn.execute("PRAGMA table_info(admins)").fetchall()}
            for col, coltype in [
                ("permissions", "TEXT DEFAULT '{}'"),
            ]:
                if col not in existing_admin_cols:
                    conn.execute(f"ALTER TABLE admins ADD COLUMN {col} {coltype}")
            conn.commit()


async def close_db():
    global _pg_pool
    if USE_POSTGRES and _pg_pool is not None:
        await _pg_pool.close()
        _pg_pool = None


# ================================================================ #
# Foydalanuvchilar
# ================================================================ #

async def upsert_user(user_id: int, username: str | None, first_name: str | None, last_name: str | None):
    now = _now()
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_name, first_seen, last_seen, message_count, is_blocked)
                VALUES ($1, $2, $3, $4, $5, $5, 1, FALSE)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    last_seen = EXCLUDED.last_seen,
                    message_count = users.message_count + 1
                """,
                user_id, username, first_name, last_name, now,
            )
    else:
        conn = _get_sqlite_conn()
        now_s = now.isoformat(timespec="seconds")
        with _sqlite_lock:
            cur = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
            exists = cur.fetchone() is not None
            if exists:
                conn.execute(
                    """UPDATE users SET username=?, first_name=?, last_name=?,
                       last_seen=?, message_count = message_count + 1
                       WHERE user_id=?""",
                    (username, first_name, last_name, now_s, user_id),
                )
            else:
                conn.execute(
                    """INSERT INTO users (user_id, username, first_name, last_name,
                       first_seen, last_seen, message_count, is_blocked)
                       VALUES (?, ?, ?, ?, ?, ?, 1, 0)""",
                    (user_id, username, first_name, last_name, now_s, now_s),
                )
            conn.commit()


async def is_blocked(user_id: int) -> bool:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT is_blocked FROM users WHERE user_id=$1", user_id)
            return bool(row["is_blocked"]) if row else False
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return bool(row["is_blocked"]) if row else False


async def set_blocked(user_id: int, blocked: bool):
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute("UPDATE users SET is_blocked=$1 WHERE user_id=$2", blocked, user_id)
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute("UPDATE users SET is_blocked=? WHERE user_id=?", (1 if blocked else 0, user_id))
            conn.commit()


async def get_user(user_id: int) -> dict | None:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
            return dict(row) if row else None
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


async def get_users(page: int = 0, page_size: int = 20, search: str = ""):
    offset = page * page_size
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            if search:
                like = f"%{search}%"
                rows = await conn.fetch(
                    """SELECT * FROM users
                       WHERE CAST(user_id AS TEXT) LIKE $1 OR username LIKE $1 OR first_name LIKE $1
                       ORDER BY last_seen DESC LIMIT $2 OFFSET $3""",
                    like, page_size, offset,
                )
                total = await conn.fetchval(
                    """SELECT COUNT(*) FROM users
                       WHERE CAST(user_id AS TEXT) LIKE $1 OR username LIKE $1 OR first_name LIKE $1""",
                    like,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM users ORDER BY last_seen DESC LIMIT $1 OFFSET $2",
                    page_size, offset,
                )
                total = await conn.fetchval("SELECT COUNT(*) FROM users")
            return [dict(r) for r in rows], total
    else:
        conn = _get_sqlite_conn()
        if search:
            like = f"%{search}%"
            cur = conn.execute(
                """SELECT * FROM users
                   WHERE CAST(user_id AS TEXT) LIKE ? OR username LIKE ? OR first_name LIKE ?
                   ORDER BY last_seen DESC LIMIT ? OFFSET ?""",
                (like, like, like, page_size, offset),
            )
            total = conn.execute(
                """SELECT COUNT(*) FROM users
                   WHERE CAST(user_id AS TEXT) LIKE ? OR username LIKE ? OR first_name LIKE ?""",
                (like, like, like),
            ).fetchone()[0]
        else:
            cur = conn.execute(
                "SELECT * FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?",
                (page_size, offset),
            )
            total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return [dict(r) for r in cur.fetchall()], total


async def get_all_user_ids(only_active: bool = True) -> list:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            if only_active:
                rows = await conn.fetch("SELECT user_id FROM users WHERE is_blocked = FALSE")
            else:
                rows = await conn.fetch("SELECT user_id FROM users")
            return [r["user_id"] for r in rows]
    else:
        conn = _get_sqlite_conn()
        if only_active:
            cur = conn.execute("SELECT user_id FROM users WHERE is_blocked = 0")
        else:
            cur = conn.execute("SELECT user_id FROM users")
        return [r["user_id"] for r in cur.fetchall()]


# ================================================================ #
# Statistika
# ================================================================ #

async def get_stats() -> dict:
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)

    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
            blocked_users = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_blocked=TRUE")
            new_today = await conn.fetchval("SELECT COUNT(*) FROM users WHERE first_seen >= $1", today)
            new_week = await conn.fetchval("SELECT COUNT(*) FROM users WHERE first_seen >= $1", week_ago)
            active_today = await conn.fetchval("SELECT COUNT(*) FROM users WHERE last_seen >= $1", today)
            total_events = await conn.fetchval("SELECT COUNT(*) FROM events")
            events_today = await conn.fetchval("SELECT COUNT(*) FROM events WHERE created_at >= $1", today)
            top_rows = await conn.fetch(
                "SELECT event_type, COUNT(*) as cnt FROM events GROUP BY event_type ORDER BY cnt DESC LIMIT 10"
            )
            top_events = [dict(r) for r in top_rows]
    else:
        conn = _get_sqlite_conn()
        today_s = today.isoformat()
        week_ago_s = week_ago.isoformat()
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        blocked_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_blocked=1").fetchone()[0]
        new_today = conn.execute("SELECT COUNT(*) FROM users WHERE first_seen >= ?", (today_s,)).fetchone()[0]
        new_week = conn.execute("SELECT COUNT(*) FROM users WHERE first_seen >= ?", (week_ago_s,)).fetchone()[0]
        active_today = conn.execute("SELECT COUNT(*) FROM users WHERE last_seen >= ?", (today_s,)).fetchone()[0]
        total_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        events_today = conn.execute("SELECT COUNT(*) FROM events WHERE created_at >= ?", (today_s,)).fetchone()[0]
        top_events = [
            dict(r) for r in conn.execute(
                "SELECT event_type, COUNT(*) as cnt FROM events GROUP BY event_type ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
        ]

    return {
        "total_users": total_users,
        "blocked_users": blocked_users,
        "new_today": new_today,
        "new_week": new_week,
        "active_today": active_today,
        "total_events": total_events,
        "events_today": events_today,
        "top_events": top_events,
    }


async def log_event(user_id: int, event_type: str, detail: str = ""):
    now = _now()
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO events (user_id, event_type, detail, created_at) VALUES ($1, $2, $3, $4)",
                user_id, event_type, detail, now,
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                "INSERT INTO events (user_id, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
                (user_id, event_type, detail, now.isoformat(timespec="seconds")),
            )
            conn.commit()


# ================================================================ #
# Saqlangan jadvallar
# ================================================================ #

async def save_schedule(user_id: int, feature: str, name: str, url: str):
    now = _now()
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO saved_schedules (user_id, feature, name, url, saved_at) VALUES ($1, $2, $3, $4, $5)",
                user_id, feature, name, url, now,
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                "INSERT INTO saved_schedules (user_id, feature, name, url, saved_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, feature, name, url, now.isoformat(timespec="seconds")),
            )
            conn.commit()


async def get_saved_schedules(user_id: int) -> list:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM saved_schedules WHERE user_id=$1 ORDER BY saved_at DESC", user_id
            )
            return [dict(r) for r in rows]
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute(
            "SELECT * FROM saved_schedules WHERE user_id=? ORDER BY saved_at DESC", (user_id,)
        )
        return [dict(r) for r in cur.fetchall()]


# ================================================================ #
# Guruh obunalari
# ================================================================ #

async def upsert_group_subscription(
    chat_id: int, chat_title: str, feature: str, name: str, url: str,
    days: str, post_time: str, created_by: int,
):
    now = _now()
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO group_subscriptions
                    (chat_id, chat_title, feature, name, url, days, post_time, is_active, created_by, created_at, last_sent_date)
                VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, $8, $9, NULL)
                ON CONFLICT (chat_id) DO UPDATE SET
                    chat_title=EXCLUDED.chat_title, feature=EXCLUDED.feature,
                    name=EXCLUDED.name, url=EXCLUDED.url, days=EXCLUDED.days,
                    post_time=EXCLUDED.post_time, is_active=TRUE,
                    created_by=EXCLUDED.created_by
                """,
                chat_id, chat_title, feature, name, url, days, post_time, created_by, now,
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                """INSERT INTO group_subscriptions
                   (chat_id, chat_title, feature, name, url, days, post_time,
                    is_active, created_by, created_at, last_sent_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL)
                   ON CONFLICT(chat_id) DO UPDATE SET
                     chat_title=excluded.chat_title, feature=excluded.feature,
                     name=excluded.name, url=excluded.url, days=excluded.days,
                     post_time=excluded.post_time, is_active=1,
                     created_by=excluded.created_by""",
                (chat_id, chat_title, feature, name, url, days, post_time, created_by,
                 now.isoformat(timespec="seconds")),
            )
            conn.commit()


async def get_group_subscriptions(active_only: bool = False) -> list:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            if active_only:
                rows = await conn.fetch("SELECT * FROM group_subscriptions WHERE is_active=TRUE")
            else:
                rows = await conn.fetch("SELECT * FROM group_subscriptions ORDER BY created_at DESC")
            return [dict(r) for r in rows]
    else:
        conn = _get_sqlite_conn()
        if active_only:
            cur = conn.execute("SELECT * FROM group_subscriptions WHERE is_active=1")
        else:
            cur = conn.execute("SELECT * FROM group_subscriptions ORDER BY created_at DESC")
        return [dict(r) for r in cur.fetchall()]


async def set_group_active(chat_id: int, active: bool):
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute("UPDATE group_subscriptions SET is_active=$1 WHERE chat_id=$2", active, chat_id)
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                "UPDATE group_subscriptions SET is_active=? WHERE chat_id=?",
                (1 if active else 0, chat_id),
            )
            conn.commit()


async def delete_group_subscription(chat_id: int):
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM group_subscriptions WHERE chat_id=$1", chat_id)
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute("DELETE FROM group_subscriptions WHERE chat_id=?", (chat_id,))
            conn.commit()


async def mark_group_sent_today(chat_id: int, date_str: str):
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                "UPDATE group_subscriptions SET last_sent_date=$1 WHERE chat_id=$2", date_str, chat_id
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                "UPDATE group_subscriptions SET last_sent_date=? WHERE chat_id=?",
                (date_str, chat_id),
            )
            conn.commit()


# ================================================================ #
# Admin <-> foydalanuvchi chat
# ================================================================ #

async def log_chat_message(
    user_id: int, direction: str, text: str,
    msg_type: str = "text", file_id: str | None = None,
):
    """Foydalanuvchi bilan bo'lgan bitta xabarni (matn, rasm, video yoki
    fayl) chat_messages jadvaliga yozadi. msg_type: 'text' | 'photo' |
    'video' | 'document'. file_id - media uchun Telegram file_id
    (admin panelda keyinchalik qayta ko'rsatish/yuklab olish uchun)."""
    now = _now()
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO chat_messages (user_id, direction, text, created_at, msg_type, file_id) VALUES ($1, $2, $3, $4, $5, $6)",
                user_id, direction, text, now, msg_type, file_id,
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                "INSERT INTO chat_messages (user_id, direction, text, created_at, msg_type, file_id) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, direction, text, now.isoformat(timespec="seconds"), msg_type, file_id),
            )
            conn.commit()


async def get_chat_messages(user_id: int, limit: int = 200) -> list:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM chat_messages WHERE user_id=$1 ORDER BY id ASC LIMIT $2", user_id, limit
            )
            return [dict(r) for r in rows]
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute(
            "SELECT * FROM chat_messages WHERE user_id=? ORDER BY id ASC LIMIT ?", (user_id, limit)
        )
        return [dict(r) for r in cur.fetchall()]


# ================================================================ #
# Admin <-> GURUH chati (bot Telegram guruhiga qo'shilgan bo'lsa,
# o'sha guruhdagi yozishmalar - xuddi shaxsiy chat kabi, lekin
# chat_id bo'yicha va har bir kiruvchi xabarning kim yozganini
# (sender_name) ham saqlab)
# ================================================================ #

async def log_group_chat_message(
    chat_id: int, direction: str, text: str,
    msg_type: str = "text", file_id: str | None = None,
    sender_user_id: int | None = None, sender_name: str | None = None,
):
    """Guruh chatidagi bitta xabarni group_chat_messages jadvaliga
    yozadi. direction: 'in' (guruh a'zosidan botga - MUHIM: Telegram
    "privacy mode" yoqilgan bo'lsa, bot faqat buyruqlar/o'ziga
    yo'llangan/javob xabarlarini oladi, guruhdagi HAR BIR xabarni emas)
    yoki 'out' (bot guruhga yuborgan - avtomatik jadval posti, qo'lda
    yuborilgan broadcast va h.k.). sender_user_id/sender_name faqat
    'in' uchun to'ldiriladi (kim yozganini admin panelda ko'rsatish
    uchun)."""
    now = _now()
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO group_chat_messages
                   (chat_id, direction, sender_user_id, sender_name, text, msg_type, file_id, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                chat_id, direction, sender_user_id, sender_name, text, msg_type, file_id, now,
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                """INSERT INTO group_chat_messages
                   (chat_id, direction, sender_user_id, sender_name, text, msg_type, file_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (chat_id, direction, sender_user_id, sender_name, text, msg_type, file_id,
                 now.isoformat(timespec="seconds")),
            )
            conn.commit()


async def get_group_chat_messages(chat_id: int, limit: int = 200) -> list:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM group_chat_messages WHERE chat_id=$1 ORDER BY id ASC LIMIT $2",
                chat_id, limit,
            )
            return [dict(r) for r in rows]
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute(
            "SELECT * FROM group_chat_messages WHERE chat_id=? ORDER BY id ASC LIMIT ?",
            (chat_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


_LAST_MESSAGE_CTE = """
WITH last_ids AS (
    SELECT user_id, MAX(id) AS max_id FROM chat_messages GROUP BY user_id
)
SELECT cm.user_id, cm.direction AS last_direction, cm.text AS last_text,
       cm.msg_type AS last_msg_type, cm.created_at AS last_at,
       u.username, u.first_name, u.last_name
FROM last_ids li
JOIN chat_messages cm ON cm.id = li.max_id
LEFT JOIN users u ON u.user_id = li.user_id
"""


async def get_support_threads(page: int = 0, page_size: int = 20):
    """Har bir foydalanuvchi bilan bo'lgan yozishmani BITTA "suhbat"
    (thread) sifatida, eng so'nggi xabar vaqti bo'yicha tartiblab
    qaytaradi - admin panelning "🛠 Texnik bo'lim" sahifasi uchun.
    Har bir qatorda so'nggi xabar kimdan ekani (foydalanuvchidanmi -
    javob kutilmoqda, yoki admindanmi - javob berilgan) ko'rinadi."""
    offset = page * page_size
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                _LAST_MESSAGE_CTE + " ORDER BY cm.created_at DESC LIMIT $1 OFFSET $2",
                page_size, offset,
            )
            total = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM chat_messages")
            return [dict(r) for r in rows], total
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute(
            _LAST_MESSAGE_CTE + " ORDER BY cm.created_at DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        )
        total = conn.execute("SELECT COUNT(DISTINCT user_id) FROM chat_messages").fetchone()[0]
        return [dict(r) for r in cur.fetchall()], total


async def get_support_stats() -> dict:
    """Jami suhbatlar soni va ulardan nechtasida so'nggi xabar
    FOYDALANUVCHIDAN kelib, hali admin javob bermaganini qaytaradi."""
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            total_threads = await conn.fetchval("SELECT COUNT(DISTINCT user_id) FROM chat_messages")
            needs_reply = await conn.fetchval(
                f"SELECT COUNT(*) FROM ({_LAST_MESSAGE_CTE}) t WHERE last_direction = 'in'"
            )
    else:
        conn = _get_sqlite_conn()
        total_threads = conn.execute("SELECT COUNT(DISTINCT user_id) FROM chat_messages").fetchone()[0]
        needs_reply = conn.execute(
            f"SELECT COUNT(*) FROM ({_LAST_MESSAGE_CTE}) t WHERE last_direction = 'in'"
        ).fetchone()[0]
    return {"total_threads": total_threads or 0, "needs_reply": needs_reply or 0}


# ================================================================ #
# Umumiy sozlamalar (kalit-qiymat)
# ================================================================ #

async def get_setting(key: str, default=None):
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            val = await conn.fetchval("SELECT value FROM settings WHERE key=$1", key)
            return val if val is not None else default
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default


async def set_setting(key: str, value: str):
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO settings (key, value) VALUES ($1, $2)
                   ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value""",
                key, value,
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            conn.commit()


# ================================================================ #
# "Mening guruhim" (standart/tezkor jadval)
# ================================================================ #

async def set_default_group(user_id: int, feature: str, name: str, url: str):
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET default_feature=$1, default_group_name=$2, default_group_url=$3 WHERE user_id=$4",
                feature, name, url, user_id,
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                "UPDATE users SET default_feature=?, default_group_name=?, default_group_url=? WHERE user_id=?",
                (feature, name, url, user_id),
            )
            conn.commit()


async def get_default_group(user_id: int) -> dict | None:
    u = await get_user(user_id)
    if not u or not u.get("default_group_name"):
        return None
    return {
        "feature": u.get("default_feature"),
        "name": u.get("default_group_name"),
        "url": u.get("default_group_url"),
    }


async def get_watched_group_names() -> list:
    """'Mening guruhim' sifatida foydalanuvchilar belgilagan guruhlar
    VA Telegram guruh chatlarida avtomatik jadval yuborish sozlangan
    guruhlar - ikkalasining birlashmasi (takrorlanmas nomlar bo'yicha).
    Almashtirishlarni kuzatish shu ro'yxat bo'ylab amalga oshiriladi
    (barcha 1290 guruhni emas, faqat odamlar qiziqqanlarini)."""
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT default_group_name, default_group_url FROM users
                WHERE default_group_name IS NOT NULL
                UNION
                SELECT name, url FROM group_subscriptions
                WHERE is_active = TRUE AND name IS NOT NULL
                """
            )
            return [{"default_group_name": r[0], "default_group_url": r[1]} for r in rows]
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute(
            """
            SELECT default_group_name, default_group_url FROM users
            WHERE default_group_name IS NOT NULL
            UNION
            SELECT name, url FROM group_subscriptions
            WHERE is_active = 1 AND name IS NOT NULL
            """
        )
        return [{"default_group_name": r[0], "default_group_url": r[1]} for r in cur.fetchall()]


async def get_users_watching_group(group_name: str) -> list:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id FROM users WHERE default_group_name=$1 AND is_blocked=FALSE", group_name
            )
            return [r["user_id"] for r in rows]
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute(
            "SELECT user_id FROM users WHERE default_group_name=? AND is_blocked=0", (group_name,)
        )
        return [r["user_id"] for r in cur.fetchall()]


async def get_telegram_groups_watching(group_name: str) -> list:
    """Berilgan guruh nomiga avtomatik jadval yuborish sozlangan,
    FAOL Telegram guruh chatlari ro'yxatini (chat_id) qaytaradi -
    jadval o'zgarganda ularga ham xabar berish uchun."""
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT chat_id FROM group_subscriptions WHERE name=$1 AND is_active=TRUE", group_name
            )
            return [r["chat_id"] for r in rows]
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute(
            "SELECT chat_id FROM group_subscriptions WHERE name=? AND is_active=1", (group_name,)
        )
        return [r["chat_id"] for r in cur.fetchall()]


# ================================================================ #
# Til (UZ/RU)
# ================================================================ #

async def set_language(user_id: int, lang: str):
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute("UPDATE users SET language=$1 WHERE user_id=$2", lang, user_id)
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute("UPDATE users SET language=? WHERE user_id=?", (lang, user_id))
            conn.commit()


async def get_language(user_id: int) -> str:
    u = await get_user(user_id)
    return (u.get("language") if u else None) or "uz"


# ================================================================ #
# Guruh jadvali "suratlari" (almashtirishlarni aniqlash uchun)
# ================================================================ #

async def get_group_snapshot(group_name: str) -> str | None:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT snapshot FROM group_snapshots WHERE group_name=$1", group_name
            )
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute("SELECT snapshot FROM group_snapshots WHERE group_name=?", (group_name,))
        row = cur.fetchone()
        return row["snapshot"] if row else None


async def set_group_snapshot(group_name: str, snapshot: str):
    now = _now()
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO group_snapshots (group_name, snapshot, updated_at) VALUES ($1, $2, $3)
                   ON CONFLICT (group_name) DO UPDATE SET snapshot=EXCLUDED.snapshot, updated_at=EXCLUDED.updated_at""",
                group_name, snapshot, now,
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                """INSERT INTO group_snapshots (group_name, snapshot, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(group_name) DO UPDATE SET snapshot=excluded.snapshot, updated_at=excluded.updated_at""",
                (group_name, snapshot, now.isoformat(timespec="seconds")),
            )
            conn.commit()


# ================================================================ #
# Xatolar jurnali
# ================================================================ #

async def log_error(context: str, message: str):
    now = _now()
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO error_logs (context, message, created_at) VALUES ($1, $2, $3)",
                context, message, now,
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                "INSERT INTO error_logs (context, message, created_at) VALUES (?, ?, ?)",
                (context, message, now.isoformat(timespec="seconds")),
            )
            conn.commit()


async def get_recent_errors(limit: int = 50) -> list:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM error_logs ORDER BY id DESC LIMIT $1", limit
            )
            return [dict(r) for r in rows]
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute("SELECT * FROM error_logs ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]


async def get_top_viewed(event_type: str, limit: int = 10) -> list:
    """Eng ko'p ko'rilgan guruh/fakultet/xonalarni events jadvalidan
    'detail' ustuni bo'yicha guruhlab chiqaradi."""
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT detail, COUNT(*) as cnt FROM events WHERE event_type=$1 "
                "GROUP BY detail ORDER BY cnt DESC LIMIT $2",
                event_type, limit,
            )
            return [dict(r) for r in rows]
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute(
            "SELECT detail, COUNT(*) as cnt FROM events WHERE event_type=? "
            "GROUP BY detail ORDER BY cnt DESC LIMIT ?",
            (event_type, limit),
        )
        return [dict(r) for r in cur.fetchall()]


# ================================================================ #
# Bir nechta admin
# ================================================================ #

def _hash_password(password: str, salt: bytes | None = None) -> str:
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return salt.hex() + ":" + digest.hex()


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
    except (ValueError, AttributeError):
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return check.hex() == digest_hex


def _serialize_permissions(permissions: dict | None) -> str:
    return json.dumps(permissions or {}, ensure_ascii=False)


def _deserialize_permissions(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


async def add_admin(username: str, password: str, permissions: dict | None = None):
    """Yangi qo'shimcha admin qo'shadi (yoki username allaqachon bor
    bo'lsa, parolini yangilaydi - permissions esa FAQAT shu chaqiruvda
    berilgan bo'lsa yangilanadi, aks holda mavjudi saqlanib qoladi,
    chunki ba'zan faqat parolni almashtirish kerak bo'lishi mumkin)."""
    now = _now()
    pw_hash = _hash_password(password)
    perms_json = _serialize_permissions(permissions)
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO admins (username, password_hash, created_at, permissions)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (username) DO UPDATE
                   SET password_hash=EXCLUDED.password_hash""",
                username, pw_hash, now, perms_json,
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                """INSERT INTO admins (username, password_hash, created_at, permissions)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash""",
                (username, pw_hash, now.isoformat(timespec="seconds"), perms_json),
            )
            conn.commit()


async def remove_admin(username: str):
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM admins WHERE username=$1", username)
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute("DELETE FROM admins WHERE username=?", (username,))
            conn.commit()


async def update_admin_permissions(username: str, permissions: dict):
    """Mavjud qo'shimcha adminning bo'lim-darajasidagi huquqlarini
    yangilaydi (parolga tegmaydi)."""
    perms_json = _serialize_permissions(permissions)
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                "UPDATE admins SET permissions=$1 WHERE username=$2", perms_json, username
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                "UPDATE admins SET permissions=? WHERE username=?", (perms_json, username)
            )
            conn.commit()


async def get_admin_permissions(username: str) -> dict:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            raw = await conn.fetchval("SELECT permissions FROM admins WHERE username=$1", username)
    else:
        conn = _get_sqlite_conn()
        row = conn.execute("SELECT permissions FROM admins WHERE username=?", (username,)).fetchone()
        raw = row["permissions"] if row else None
    return _deserialize_permissions(raw)


async def get_all_admins() -> list:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT username, created_at, permissions FROM admins ORDER BY created_at"
            )
            result = [dict(r) for r in rows]
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute(
            "SELECT username, created_at, permissions FROM admins ORDER BY created_at"
        )
        result = [dict(r) for r in cur.fetchall()]
    for r in result:
        r["permissions"] = _deserialize_permissions(r.get("permissions"))
    return result


async def verify_admin_credentials(username: str, password: str) -> bool:
    """Baza ichidagi qo'shimcha adminlar ro'yxatidan tekshiradi
    (asosiy .env admin bundan tashqari, alohida check_auth ichida
    tekshiriladi)."""
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            stored = await conn.fetchval("SELECT password_hash FROM admins WHERE username=$1", username)
    else:
        conn = _get_sqlite_conn()
        row = conn.execute("SELECT password_hash FROM admins WHERE username=?", (username,)).fetchone()
        stored = row["password_hash"] if row else None

    if not stored:
        return False
    return _verify_password(password, stored)


# ================================================================ #
# Yangi topilgan narsalar (skanerlashda faylda yo'q, lekin saytda
# topilgan guruh/o'qituvchi/xona) - admin panelda ko'rish uchun
# ================================================================ #

async def add_discovered_item(item_type: str, name: str, url: str):
    now = _now()
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO discovered_items (item_type, name, url, discovered_at)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (item_type, name) DO UPDATE SET url=EXCLUDED.url, discovered_at=EXCLUDED.discovered_at""",
                item_type, name, url, now,
            )
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute(
                """INSERT INTO discovered_items (item_type, name, url, discovered_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(item_type, name) DO UPDATE SET url=excluded.url, discovered_at=excluded.discovered_at""",
                (item_type, name, url, now.isoformat(timespec="seconds")),
            )
            conn.commit()


async def get_discovered_items(item_type: str = None) -> list:
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            if item_type:
                rows = await conn.fetch(
                    "SELECT * FROM discovered_items WHERE item_type=$1 ORDER BY discovered_at DESC", item_type
                )
            else:
                rows = await conn.fetch("SELECT * FROM discovered_items ORDER BY item_type, discovered_at DESC")
            return [dict(r) for r in rows]
    else:
        conn = _get_sqlite_conn()
        if item_type:
            cur = conn.execute(
                "SELECT * FROM discovered_items WHERE item_type=? ORDER BY discovered_at DESC", (item_type,)
            )
        else:
            cur = conn.execute("SELECT * FROM discovered_items ORDER BY item_type, discovered_at DESC")
        return [dict(r) for r in cur.fetchall()]


async def clear_discovered_item(item_id: int):
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM discovered_items WHERE id=$1", item_id)
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            conn.execute("DELETE FROM discovered_items WHERE id=?", (item_id,))
            conn.commit()


async def clear_all_discovered_items(item_type: str = None):
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            if item_type:
                await conn.execute("DELETE FROM discovered_items WHERE item_type=$1", item_type)
            else:
                await conn.execute("DELETE FROM discovered_items")
    else:
        conn = _get_sqlite_conn()
        with _sqlite_lock:
            if item_type:
                conn.execute("DELETE FROM discovered_items WHERE item_type=?", (item_type,))
            else:
                conn.execute("DELETE FROM discovered_items")
            conn.commit()


# ================================================================ #
# Xizmatni baholash (⭐ 1-5) - dars jadvalini birinchi marta
# ko'rgandan keyin foydalanuvchiga FAQAT BIR MARTA yuboriladigan
# so'rov va uning natijalari.
# ================================================================ #

async def mark_rating_prompted(user_id: int) -> bool:
    """Foydalanuvchi uchun baholash so'rovi hali yuborilmagan bo'lsa,
    shu yerda "band" qilib qo'yamiz va True qaytaramiz (demak, ENDI
    xabarni yuborish kerak). Agar allaqachon (yoki xuddi shu
    daqiqada, boshqa so'rov orqali) band qilingan bo'lsa, False
    qaytaradi - shunda ikki marta yuborib yubormaymiz (race-safe:
    tekshirib keyin yozish o'rniga, to'g'ridan-to'g'ri "faqat band
    bo'lmasa yoz" amalidan foydalanamiz)."""
    now = _now()
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            result = await conn.execute(
                "INSERT INTO ratings (user_id, prompted_at) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
                user_id, now,
            )
            # asyncpg "INSERT 0 1" (yozildi) yoki "INSERT 0 0" (band edi) qaytaradi.
            return result.strip().endswith(" 1")
    else:
        conn = _get_sqlite_conn()
        now_s = now.isoformat(timespec="seconds")
        with _sqlite_lock:
            cur = conn.execute(
                "INSERT OR IGNORE INTO ratings (user_id, prompted_at) VALUES (?, ?)",
                (user_id, now_s),
            )
            conn.commit()
            return cur.rowcount > 0


async def set_rating(user_id: int, rating: int):
    """Foydalanuvchi yulduz bosganda baholashni saqlaydi. Agar
    negadir oldin 'band' qilinmagan bo'lsa ham (masalan eski xabar),
    yozuvni o'zi yaratib qo'yadi (upsert)."""
    now = _now()
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ratings (user_id, rating, prompted_at, rated_at)
                VALUES ($1, $2, $3, $3)
                ON CONFLICT (user_id) DO UPDATE SET rating = EXCLUDED.rating, rated_at = EXCLUDED.rated_at
                """,
                user_id, rating, now,
            )
    else:
        conn = _get_sqlite_conn()
        now_s = now.isoformat(timespec="seconds")
        with _sqlite_lock:
            conn.execute(
                """
                INSERT INTO ratings (user_id, rating, prompted_at, rated_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET rating=excluded.rating, rated_at=excluded.rated_at
                """,
                (user_id, rating, now_s, now_s),
            )
            conn.commit()


async def get_rating_stats() -> dict:
    """O'rtacha baho, jami baholaganlar soni, jami so'rov yuborilganlar
    soni va har bir yulduz (1-5) bo'yicha taqsimotni qaytaradi."""
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            total_prompted = await conn.fetchval("SELECT COUNT(*) FROM ratings")
            avg_row = await conn.fetchrow(
                "SELECT AVG(rating)::float AS avg, COUNT(*) AS cnt FROM ratings WHERE rating IS NOT NULL"
            )
            dist_rows = await conn.fetch(
                "SELECT rating, COUNT(*) AS cnt FROM ratings WHERE rating IS NOT NULL GROUP BY rating"
            )
    else:
        conn = _get_sqlite_conn()
        total_prompted = conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]
        row = conn.execute(
            "SELECT AVG(rating) AS avg, COUNT(*) AS cnt FROM ratings WHERE rating IS NOT NULL"
        ).fetchone()
        avg_row = {"avg": row["avg"], "cnt": row["cnt"]}
        dist_rows = conn.execute(
            "SELECT rating, COUNT(*) AS cnt FROM ratings WHERE rating IS NOT NULL GROUP BY rating"
        ).fetchall()

    distribution = {n: 0 for n in range(1, 6)}
    for r in dist_rows:
        distribution[int(r["rating"])] = r["cnt"]

    total_rated = avg_row["cnt"] or 0
    average = round(avg_row["avg"], 2) if avg_row["avg"] is not None else None

    return {
        "average": average,
        "total_rated": total_rated,
        "total_prompted": total_prompted,
        "distribution": distribution,
    }


async def get_ratings_list(page: int = 0, page_size: int = 20):
    """Kim nechi yulduz bosganini (baholagan foydalanuvchilar ro'yxatini),
    eng yangisidan boshlab, sahifalab qaytaradi."""
    offset = page * page_size
    if USE_POSTGRES:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.user_id, r.rating, r.rated_at, u.username, u.first_name, u.last_name
                FROM ratings r
                LEFT JOIN users u ON u.user_id = r.user_id
                WHERE r.rating IS NOT NULL
                ORDER BY r.rated_at DESC
                LIMIT $1 OFFSET $2
                """,
                page_size, offset,
            )
            total = await conn.fetchval("SELECT COUNT(*) FROM ratings WHERE rating IS NOT NULL")
            return [dict(r) for r in rows], total
    else:
        conn = _get_sqlite_conn()
        cur = conn.execute(
            """
            SELECT r.user_id, r.rating, r.rated_at, u.username, u.first_name, u.last_name
            FROM ratings r
            LEFT JOIN users u ON u.user_id = r.user_id
            WHERE r.rating IS NOT NULL
            ORDER BY r.rated_at DESC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        )
        total = conn.execute("SELECT COUNT(*) FROM ratings WHERE rating IS NOT NULL").fetchone()[0]
        return [dict(r) for r in cur.fetchall()], total

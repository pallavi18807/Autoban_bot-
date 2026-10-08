from __future__ import annotations
import time
import aiosqlite


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            authorized INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            grace_seconds INTEGER NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT 'Left the group',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS whitelist (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY(chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS tracked_members (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            last_seen INTEGER NOT NULL,
            PRIMARY KEY(chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS pending_leaves (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            due_at INTEGER NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY(chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS ban_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            success INTEGER NOT NULL,
            error TEXT,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS banned_profiles (
            chat_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY(chat_id, user_id)
        );
        """)
        # Backward-compatible migration for databases created by older builds.
        try:
            await self.conn.execute("ALTER TABLE tracked_members ADD COLUMN last_name TEXT")
            await self.conn.commit()
        except Exception:
            pass
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()
            self.conn = None

    async def _execute(self, sql, params=()):
        if not self.conn:
            raise RuntimeError("Database is not connected")
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur

    async def ensure_group(self, chat_id: int, default_grace: int):
        now = int(time.time())
        await self._execute(
            "INSERT OR IGNORE INTO groups(chat_id,authorized,enabled,grace_seconds,reason,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (chat_id, 0, 1, default_grace, "Left the group", now, now),
        )

    async def get_group(self, chat_id: int):
        cur = await self.conn.execute("SELECT * FROM groups WHERE chat_id=?", (chat_id,))
        return await cur.fetchone()

    async def set_group(self, chat_id: int, **fields):
        if not fields:
            return
        fields["updated_at"] = int(time.time())
        cols = ", ".join(f"{k}=?" for k in fields)
        await self._execute(f"UPDATE groups SET {cols} WHERE chat_id=?", tuple(fields.values()) + (chat_id,))

    async def track_member(self, chat_id: int, user_id: int, username: str | None, first_name: str | None, last_name: str | None = None):
        await self._execute(
            "INSERT INTO tracked_members(chat_id,user_id,username,first_name,last_name,last_seen) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(chat_id,user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, last_name=excluded.last_name, last_seen=excluded.last_seen",
            (chat_id, user_id, username, first_name, last_name, int(time.time())),
        )

    async def untrack_member(self, chat_id: int, user_id: int):
        await self._execute("DELETE FROM tracked_members WHERE chat_id=? AND user_id=?", (chat_id, user_id))

    async def get_tracked_member(self, chat_id: int, user_id: int):
        cur = await self.conn.execute(
            "SELECT * FROM tracked_members WHERE chat_id=? AND user_id=?",
            (chat_id, user_id),
        )
        return await cur.fetchone()

    async def find_tracked_by_username(self, chat_id: int, username: str):
        username = username.strip().lstrip("@").lower()
        cur = await self.conn.execute(
            "SELECT * FROM tracked_members WHERE chat_id=? AND lower(username)=? ORDER BY last_seen DESC LIMIT 1",
            (chat_id, username),
        )
        return await cur.fetchone()

    async def tracked_members(self, limit: int):
        cur = await self.conn.execute("SELECT * FROM tracked_members ORDER BY last_seen DESC LIMIT ?", (limit,))
        return await cur.fetchall()

    async def is_whitelisted(self, chat_id: int, user_id: int) -> bool:
        cur = await self.conn.execute("SELECT 1 FROM whitelist WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        return await cur.fetchone() is not None

    async def set_whitelist(self, chat_id: int, user_id: int, enabled: bool):
        if enabled:
            await self._execute("INSERT OR IGNORE INTO whitelist(chat_id,user_id) VALUES(?,?)", (chat_id, user_id))
        else:
            await self._execute("DELETE FROM whitelist WHERE chat_id=? AND user_id=?", (chat_id, user_id))

    async def add_pending(self, chat_id: int, user_id: int, due_at: int, reason: str):
        await self._execute(
            "INSERT INTO pending_leaves(chat_id,user_id,due_at,reason) VALUES(?,?,?,?) "
            "ON CONFLICT(chat_id,user_id) DO UPDATE SET due_at=excluded.due_at, reason=excluded.reason",
            (chat_id, user_id, due_at, reason),
        )

    async def remove_pending(self, chat_id: int, user_id: int):
        await self._execute("DELETE FROM pending_leaves WHERE chat_id=? AND user_id=?", (chat_id, user_id))

    async def pending(self, chat_id: int, user_id: int):
        cur = await self.conn.execute("SELECT * FROM pending_leaves WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        return await cur.fetchone()

    async def due_pending(self, now: int, limit: int = 100):
        cur = await self.conn.execute("SELECT * FROM pending_leaves WHERE due_at<=? ORDER BY due_at LIMIT ?", (now, limit))
        return await cur.fetchall()


    async def save_banned_profile(self, chat_id: int, user_id: int, username: str | None, first_name: str | None, last_name: str | None):
        now = int(time.time())
        await self._execute(
            "INSERT INTO banned_profiles(chat_id,user_id,username,first_name,last_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(chat_id,user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, last_name=excluded.last_name, updated_at=excluded.updated_at",
            (chat_id, user_id, username, first_name, last_name, now, now),
        )

    async def find_banned_by_username(self, chat_id: int, username: str):
        username = username.strip().lstrip("@").lower()
        cur = await self.conn.execute(
            "SELECT * FROM banned_profiles WHERE chat_id=? AND lower(username)=? ORDER BY updated_at DESC LIMIT 1",
            (chat_id, username),
        )
        return await cur.fetchone()

    async def get_banned_profile(self, chat_id: int, user_id: int):
        cur = await self.conn.execute(
            "SELECT * FROM banned_profiles WHERE chat_id=? AND user_id=?",
            (chat_id, user_id),
        )
        return await cur.fetchone()

    async def remove_banned_profile(self, chat_id: int, user_id: int):
        await self._execute("DELETE FROM banned_profiles WHERE chat_id=? AND user_id=?", (chat_id, user_id))

    async def log_ban(self, chat_id: int, user_id: int, reason: str, success: bool, error: str | None):
        await self._execute(
            "INSERT INTO ban_log(chat_id,user_id,reason,success,error,created_at) VALUES(?,?,?,?,?,?)",
            (chat_id, user_id, reason, int(success), error, int(time.time())),
        )

from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_id: int
    database_path: str
    default_grace_seconds: int
    watcher_interval_seconds: int
    watcher_batch_size: int
    bot_message_delete_seconds: int
    log_level: str


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is missing in .env")
    owner_id = _int_env("OWNER_ID", 0)
    if owner_id <= 0:
        raise RuntimeError("OWNER_ID is missing or invalid in .env")
    return Config(
        bot_token=token,
        owner_id=owner_id,
        database_path=os.getenv("DATABASE_PATH", "bot_data.sqlite3").strip() or "bot_data.sqlite3",
        default_grace_seconds=max(0, _int_env("DEFAULT_GRACE_SECONDS", 0)),
        watcher_interval_seconds=max(5, _int_env("WATCHER_INTERVAL_SECONDS", 20)),
        watcher_batch_size=max(10, _int_env("WATCHER_BATCH_SIZE", 50)),
        bot_message_delete_seconds=max(0, _int_env("BOT_MESSAGE_DELETE_SECONDS", 10)),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )

from __future__ import annotations
import asyncio
import logging
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter

log = logging.getLogger(__name__)


async def ban_user(bot: Bot, chat_id: int, user_id: int, retries: int = 4) -> tuple[bool, str]:
    last_error = "unknown error"
    for attempt in range(retries):
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id, revoke_messages=False)
            return True, "banned"
        except TelegramRetryAfter as exc:
            last_error = f"retry_after: {exc.retry_after}s"
            await asyncio.sleep(float(exc.retry_after))
        except (TelegramNetworkError,) as exc:
            last_error = f"network: {exc}"
            await asyncio.sleep(min(2 ** attempt, 8))
        except TelegramForbiddenError as exc:
            return False, f"forbidden: {exc}"
        except TelegramBadRequest as exc:
            return False, f"bad_request: {exc.message}"
        except TelegramAPIError as exc:
            return False, f"telegram_api: {exc}"
        except Exception as exc:
            last_error = f"unexpected: {exc}"
            await asyncio.sleep(min(2 ** attempt, 8))
    return False, last_error

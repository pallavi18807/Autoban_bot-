import asyncio
import logging
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError

log = logging.getLogger(__name__)


async def notify(bot: Bot, chat_id: int, text: str, delete_after: int = 10, parse_mode: str | None = None):
    try:
        msg = await bot.send_message(chat_id, text, parse_mode=parse_mode)
        if delete_after > 0:
            await asyncio.sleep(delete_after)
            try:
                await bot.delete_message(chat_id, msg.message_id)
            except TelegramAPIError:
                pass
    except (TelegramNetworkError, TelegramAPIError) as exc:
        log.warning("Notification failed: %s", exc)

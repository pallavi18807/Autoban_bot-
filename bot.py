from __future__ import annotations
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError, TelegramConflictError
from aiogram.types import BotCommand
from config import load_config
from database import Database
from handlers.membership import router as membership_router
from handlers.commands import router as commands_router
from handlers.membership import process_leave
import time


async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Start bot"),
        BotCommand(command="help", description="Show help"),
        BotCommand(command="authorize", description="Authorize this group"),
        BotCommand(command="status", description="Show protection status"),
        BotCommand(command="grace", description="Set grace seconds"),
        BotCommand(command="on", description="Turn protection on"),
        BotCommand(command="off", description="Turn protection off"),
        BotCommand(command="whitelist", description="Whitelist a user"),
        BotCommand(command="unwhitelist", description="Remove whitelist"),
        BotCommand(command="unban", description="Unban a user"),
        BotCommand(command="test", description="Check ban permission"),
    ])


async def pending_recovery_worker(bot: Bot, db: Database, cfg):
    log = logging.getLogger("pending_recovery")
    while True:
        try:
            rows = await db.due_pending(int(time.time()), 100)
            for row in rows:
                try:
                    await process_leave(bot, db, cfg, row["chat_id"], row["user_id"], row["reason"])
                except Exception as exc:
                    log.exception("Pending leave recovery failed chat=%s user=%s: %s", row["chat_id"], row["user_id"], exc)
        except Exception as exc:
            log.exception("Pending recovery worker error: %s", exc)
        await asyncio.sleep(5)


async def main():
    cfg = load_config()
    logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    log = logging.getLogger("auto_leave_guard")
    db = Database(cfg.database_path)
    await db.connect()
    bot = Bot(cfg.bot_token)
    dp = Dispatcher()
    dp["db"] = db
    dp["cfg"] = cfg
    dp.include_router(membership_router)
    dp.include_router(commands_router)
    try:
        me = await bot.get_me()
        log.info("BOT STARTED | id=%s | username=@%s", me.id, me.username)
        await set_commands(bot)
        recovery_task = asyncio.create_task(pending_recovery_worker(bot, db, cfg))
        await bot.delete_webhook(drop_pending_updates=False)
        log.info("POLLING READY | allowed_updates=message,chat_member,my_chat_member,callback_query")
        while True:
            try:
                await dp.start_polling(bot, allowed_updates=["message", "chat_member", "my_chat_member", "callback_query"])
            except TelegramConflictError:
                log.error("Another process is already polling this bot token. Stop all other bot processes, then restart.")
                await asyncio.sleep(10)
            except TelegramNetworkError as exc:
                log.error("Polling network error: %s. Reconnecting...", exc)
                await asyncio.sleep(5)
    finally:
        if "recovery_task" in locals():
            recovery_task.cancel()
            try:
                await recovery_task
            except asyncio.CancelledError:
                pass
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

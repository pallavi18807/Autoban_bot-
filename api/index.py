from fastapi import FastAPI, Request, HTTPException
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from config import load_config
from database import Database
from handlers.membership import router as membership_router
from handlers.commands import router as commands_router

import logging
import os


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

log = logging.getLogger("auto_leave_guard_vercel")

cfg = load_config()

bot = Bot(cfg.bot_token)

dp = Dispatcher()

db = Database(cfg.database_path)

dp["db"] = db
dp["cfg"] = cfg

dp.include_router(membership_router)
dp.include_router(commands_router)

app = FastAPI()


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "auto_leave_guard_bot"
    }


@app.post("/webhook")
async def webhook(request: Request):
    secret = os.getenv("WEBHOOK_SECRET")

    if secret:
        telegram_secret = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token"
        )

        if telegram_secret != secret:
            raise HTTPException(status_code=403, detail="Invalid webhook secret")

    try:
        data = await request.json()

        update = Update.model_validate(
            data,
            context={"bot": bot},
        )

        await dp.feed_update(
            bot,
            update,
            db=db,
            cfg=cfg,
        )

        return {"ok": True}

    except Exception as exc:
        log.exception("Webhook processing failed: %s", exc)
        raise HTTPException(status_code=500, detail="Webhook processing failed")
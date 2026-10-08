from __future__ import annotations
from html import escape
import asyncio
import logging
import time
from aiogram import Bot, Router, F
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import ChatMemberUpdated, Message
from database import Database
from config import Config
from services.ban_service import ban_user
from services.security import bot_can_ban
from services.notifier import notify

router = Router(name="membership")
log = logging.getLogger(__name__)
_locks: dict[tuple[int,int], asyncio.Lock] = {}
_seen_events: set[tuple[int,int,int,str]] = set()


def _lock(chat_id, user_id):
    return _locks.setdefault((chat_id, user_id), asyncio.Lock())


async def process_leave(bot: Bot, db: Database, cfg: Config, chat_id: int, user_id: int, reason: str = "Left the group"):
    key = (chat_id, user_id)
    async with _lock(chat_id, user_id):
        group = await db.get_group(chat_id)
        profile = await db.get_tracked_member(chat_id, user_id)
        first_name = (profile["first_name"] if profile else None) or ""
        last_name = (profile["last_name"] if profile and "last_name" in profile.keys() else None) or ""
        display_name = escape(" ".join(part for part in (first_name, last_name) if part).strip() or "Unknown")
        username = (profile["username"] if profile else None)
        username_text = escape(f"@{username}" if username else "No username")
        if not group or not group["authorized"] or not group["enabled"]:
            return
        if await db.is_whitelisted(chat_id, user_id):
            log.info("Leave ignored: whitelisted chat=%s user=%s", chat_id, user_id)
            await db.remove_pending(chat_id, user_id)
            return
        ok, why = await bot_can_ban(bot, chat_id)
        if not ok:
            log.error("Cannot auto-ban chat=%s user=%s: %s", chat_id, user_id, why)
            await notify(bot, chat_id, f"⚠️ <b>AUTO-BAN FAILED</b>\n\n👤 Name: <b>{display_name}</b>\n🔗 Username: <code>{username_text}</code>\n🆔 User ID: <code>{user_id}</code>\n⚠️ Reason: {why}", cfg.bot_message_delete_seconds, "HTML")
            return
        # Recheck immediately before ban. If the member rejoined during grace, do nothing.
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status != ChatMemberStatus.LEFT:
                await db.remove_pending(chat_id, user_id)
                return
        except Exception as exc:
            log.warning("Pre-ban status check failed chat=%s user=%s: %s", chat_id, user_id, exc)
        success, err = await ban_user(bot, chat_id, user_id)
        if success:
            await db.save_banned_profile(
                chat_id,
                user_id,
                profile["username"] if profile else None,
                profile["first_name"] if profile else None,
                profile["last_name"] if profile and "last_name" in profile.keys() else None,
            )
        await db.log_ban(chat_id, user_id, reason, success, None if success else err)
        await db.remove_pending(chat_id, user_id)
        if success:
            log.warning("AUTO BAN SUCCESS chat=%s user=%s", chat_id, user_id)
            await notify(bot, chat_id, f"🔨 <b>MEMBER LEFT — USER BANNED</b>\n\n👤 Name: <b>{display_name}</b>\n🔗 Username: <code>{username_text}</code>\n🆔 User ID: <code>{user_id}</code>\n📝 Reason: {reason}", cfg.bot_message_delete_seconds, "HTML")
        else:
            log.error("AUTO BAN FAILED chat=%s user=%s: %s", chat_id, user_id, err)
            await notify(bot, chat_id, f"⚠️ <b>MEMBER LEFT — AUTO-BAN FAILED</b>\n\n👤 Name: <b>{display_name}</b>\n🔗 Username: <code>{username_text}</code>\n🆔 User ID: <code>{user_id}</code>\n⚠️ Error: {err}", cfg.bot_message_delete_seconds, "HTML")


async def schedule_leave(bot: Bot, db: Database, cfg: Config, chat_id: int, user_id: int, reason: str):
    group = await db.get_group(chat_id)
    if not group or not group["authorized"] or not group["enabled"]:
        return
    grace = max(0, int(group["grace_seconds"]))
    if grace == 0:
        log.warning("LEAVE IMMEDIATE PATH chat=%s user=%s", chat_id, user_id)
        await process_leave(bot, db, cfg, chat_id, user_id, reason)
        return
    due = int(time.time()) + grace
    await db.add_pending(chat_id, user_id, due, reason)
    log.warning("LEAVE QUEUED chat=%s user=%s grace=%ss", chat_id, user_id, grace)
    await asyncio.sleep(grace)
    pending = await db.pending(chat_id, user_id)
    if pending:
        await process_leave(bot, db, cfg, chat_id, user_id, pending["reason"])


@router.chat_member()
async def on_chat_member_update(event: ChatMemberUpdated, bot: Bot, db: Database, cfg: Config):
    chat = event.chat
    if chat.type != ChatType.SUPERGROUP:
        return
    target = event.new_chat_member.user
    old = event.old_chat_member
    new = event.new_chat_member
    log.info("CHAT_MEMBER_UPDATE chat=%s user=%s old=%s new=%s", chat.id, target.id, old.status, new.status)
    if target.is_bot:
        return
    if new.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        await db.track_member(chat.id, target.id, target.username, target.first_name, target.last_name)
        await db.remove_pending(chat.id, target.id)
        return
    if new.status == ChatMemberStatus.LEFT:
        if old.status not in {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED}:
            return
        if await db.is_whitelisted(chat.id, target.id):
            return
        await schedule_leave(bot, db, cfg, chat.id, target.id, "Voluntarily left the group")


@router.message(F.left_chat_member)
async def on_leave_service_message(message: Message, bot: Bot, db: Database, cfg: Config):
    if not message.chat or message.chat.type != ChatType.SUPERGROUP or not message.left_chat_member:
        return
    target = message.left_chat_member
    if target.is_bot:
        return
    if message.from_user and message.from_user.id != target.id:
        # Usually an admin/bot action rather than voluntary leave.
        return
    await schedule_leave(bot, db, cfg, message.chat.id, target.id, "Voluntarily left the group")

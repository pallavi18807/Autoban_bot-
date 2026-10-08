from __future__ import annotations
from html import escape
import asyncio
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ChatType, ChatMemberStatus
from database import Database
from config import Config
from services.security import is_group_creator, is_bot_owner, bot_can_ban
from services.ban_service import ban_user

router = Router(name="commands")


async def bot_reply(message: Message, cfg: Config, text: str, parse_mode: str | None = None):
    """Send a bot reply and remove only the bot message after the configured delay.

    User command messages are never deleted by this helper.
    """
    try:
        sent = await message.answer(text, parse_mode=parse_mode)
        delay = max(0, int(cfg.bot_message_delete_seconds))
        if delay:
            await asyncio.sleep(delay)
            try:
                await sent.delete()
            except Exception:
                pass
        return sent
    except Exception:
        return None


def parse_user_id(value: str) -> int | None:
    value = value.strip()
    if value.startswith("@"):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def clean_username(value: str) -> str:
    return value.strip().lstrip("@").lower()


async def ensure_group(message: Message, db: Database, cfg: Config):
    if message.chat.type != ChatType.SUPERGROUP:
        await bot_reply(message, cfg, "⚠️ This bot requires a Telegram supergroup.")
        return False
    await db.ensure_group(message.chat.id, cfg.default_grace_seconds)
    return True


async def is_mod(message: Message, bot) -> bool:
    if message.chat.type != ChatType.SUPERGROUP or not message.from_user:
        return False
    try:
        m = await bot.get_chat_member(message.chat.id, message.from_user.id)
        return m.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
    except Exception:
        return False


@router.message(Command("start"))
async def start(message: Message, cfg: Config):
    await bot_reply(message, cfg, "🛡️ Auto Leave Guard\n\nNormal member leaves → automatic ban.\nUse /help for commands.")


@router.message(Command("help"))
async def help_cmd(message: Message, cfg: Config):
    await bot_reply(message, cfg, 
        "🛡️ Auto Leave Guard\n\n"
        "/authorize — group owner or bot owner\n"
        "/on /off — enable/disable protection\n"
        "/grace 0 — instant ban\n"
        "/grace 10 — 10 second grace\n"
        "/reason <text> — custom ban reason\n"
        "/whitelist <id> — whitelist user\n"
        "/unwhitelist <id> — remove whitelist\n"
        "/unban <id|@username> — unban user\n"
        "/status — protection status\n"
        "/test — check bot ban permission"
    )


@router.message(Command("authorize"))
async def authorize(message: Message, bot, db: Database, cfg: Config):
    if not await ensure_group(message, db, cfg): return
    user_id = message.from_user.id if message.from_user else 0
    # Authorization is allowed for either the Telegram group creator or the configured bot owner.
    if not (await is_group_creator(bot, message.chat.id, user_id) or user_id == cfg.owner_id):
        await bot_reply(message, cfg, "❌ Only the group owner or bot owner can authorize this bot.")
        return
    await db.set_group(message.chat.id, authorized=1, enabled=1)
    await bot_reply(message, cfg, "✅ Group authorized. Auto leave-ban protection is ON.")


@router.message(Command("on"))
async def on_cmd(message: Message, bot, db: Database, cfg: Config):
    if not await ensure_group(message, db, cfg): return
    if not await is_mod(message, bot): return
    await db.set_group(message.chat.id, enabled=1)
    await bot_reply(message, cfg, "🟢 Protection ON")


@router.message(Command("off"))
async def off_cmd(message: Message, bot, db: Database, cfg: Config):
    if not await ensure_group(message, db, cfg): return
    if not await is_group_creator(bot, message.chat.id, message.from_user.id):
        await bot_reply(message, cfg, "❌ Only the group owner can disable protection.")
        return
    await db.set_group(message.chat.id, enabled=0)
    await bot_reply(message, cfg, "🔴 Protection OFF")


@router.message(Command("grace"))
async def grace_cmd(message: Message, bot, db: Database, cfg: Config):
    if not await ensure_group(message, db, cfg): return
    if not await is_mod(message, bot): return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await bot_reply(message, cfg, "Usage: /grace 0\n0 = instant, e.g. /grace 10")
        return
    seconds = max(0, min(int(parts[1]), 3600))
    await db.set_group(message.chat.id, grace_seconds=seconds)
    await bot_reply(message, cfg, f"⏱ Grace time set to {seconds} seconds.")


@router.message(Command("reason"))
async def reason_cmd(message: Message, bot, db: Database, cfg: Config):
    if not await ensure_group(message, db, cfg): return
    if not await is_group_creator(bot, message.chat.id, message.from_user.id): return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await bot_reply(message, cfg, "Usage: /reason <ban reason>")
        return
    await db.set_group(message.chat.id, reason=parts[1][:300])
    await bot_reply(message, cfg, "✅ Default ban reason updated.")


@router.message(Command("whitelist"))
async def whitelist_cmd(message: Message, bot, db: Database, cfg: Config):
    if not await ensure_group(message, db, cfg): return
    if not await is_mod(message, bot): return
    parts = message.text.split(maxsplit=1)
    uid = parse_user_id(parts[1]) if len(parts) == 2 else None
    if uid is None:
        await bot_reply(message, cfg, "Use numeric user ID: /whitelist 123456789")
        return
    await db.set_whitelist(message.chat.id, uid, True)
    await bot_reply(message, cfg, f"✅ User {uid} added to whitelist.")


@router.message(Command("unwhitelist"))
async def unwhitelist_cmd(message: Message, bot, db: Database, cfg: Config):
    if not await ensure_group(message, db, cfg): return
    if not await is_mod(message, bot): return
    parts = message.text.split(maxsplit=1)
    uid = parse_user_id(parts[1]) if len(parts) == 2 else None
    if uid is None:
        await bot_reply(message, cfg, "Use numeric user ID: /unwhitelist 123456789")
        return
    await db.set_whitelist(message.chat.id, uid, False)
    await bot_reply(message, cfg, f"✅ User {uid} removed from whitelist.")


@router.message(Command("unban"))
async def unban_cmd(message: Message, bot, db: Database, cfg: Config):
    if not await ensure_group(message, db, cfg):
        return
    requester_id = message.from_user.id if message.from_user else 0
    if not (await is_mod(message, bot) or requester_id == cfg.owner_id):
        await bot_reply(message, cfg, "❌ Only a group admin/owner or bot owner can unban users.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        await bot_reply(message, cfg, "Usage: /unban <user_id|@username>\nExample: /unban 123456789 or /unban @john")
        return

    raw = parts[1].strip()
    uid = parse_user_id(raw)
    profile = None

    if uid is None:
        username = clean_username(raw)
        if not username:
            await bot_reply(message, cfg, "❌ Invalid username.")
            return
        # Look in the persistent banned-user table first. This survives the member leaving.
        profile = await db.find_banned_by_username(message.chat.id, username)
        if not profile:
            profile = await db.find_tracked_by_username(message.chat.id, username)
        if not profile:
            await bot_reply(message, cfg, 
                f"❌ I don't have a saved user ID for @{username}.\n\n"
                "This username must have been seen by the bot before the ban, or use the numeric user ID."
            )
            return
        uid = int(profile["user_id"])

    if profile is None:
        profile = await db.get_banned_profile(message.chat.id, uid)
    if profile is None:
        profile = await db.get_tracked_member(message.chat.id, uid)

    first_name = (profile["first_name"] if profile else None) or ""
    last_name = (profile["last_name"] if profile and "last_name" in profile.keys() else None) or ""
    display_name = escape(" ".join(part for part in (first_name, last_name) if part).strip() or "Unknown")
    username = (profile["username"] if profile else None)
    username_text = escape(f"@{username}" if username else "No username")

    try:
        await bot.unban_chat_member(message.chat.id, uid, only_if_banned=True)
        await db.remove_banned_profile(message.chat.id, uid)
        await bot_reply(message, cfg, 
            "✅ <b>User Unbanned</b>\n\n"
            f"👤 Name: <b>{display_name}</b>\n"
            f"🔗 Username: <code>{username_text}</code>\n"
            f"🆔 User ID: <code>{uid}</code>",
            parse_mode="HTML",
        )
    except Exception as exc:
        await bot_reply(message, cfg, 
            "❌ <b>Unban Failed</b>\n\n"
            f"👤 Name: <b>{display_name}</b>\n"
            f"🔗 Username: <code>{username_text}</code>\n"
            f"🆔 User ID: <code>{uid}</code>\n"
            f"⚠️ Error: <code>{escape(str(exc))}</code>",
            parse_mode="HTML",
        )


@router.message(Command("test"))
async def test_cmd(message: Message, bot, db: Database, cfg: Config):
    if not await ensure_group(message, db, cfg): return
    if not await is_mod(message, bot): return
    ok, why = await bot_can_ban(bot, message.chat.id)
    await bot_reply(message, cfg, ("✅ Ban permission OK." if ok else f"❌ Ban check failed: {why}"))


@router.message(Command("status"))
async def status_cmd(message: Message, bot, db: Database, cfg: Config):
    if not await ensure_group(message, db, cfg): return
    group = await db.get_group(message.chat.id)
    ok, why = await bot_can_ban(bot, message.chat.id)
    text = (
        "🛡️ <b>Auto Leave Guard Status</b>\n\n"
        f"Protection: {'🟢 ON' if group['enabled'] else '🔴 OFF'}\n"
        f"Authorized: {'✅' if group['authorized'] else '❌'}\n"
        f"Grace: <code>{group['grace_seconds']}s</code>\n"
        f"Ban permission: {'✅ OK' if ok else '❌ ' + why}"
    )
    await bot_reply(message, cfg, text, parse_mode="HTML")

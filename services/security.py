from aiogram import Bot
from aiogram.enums import ChatMemberStatus, ChatType


async def bot_can_ban(bot: Bot, chat_id: int) -> tuple[bool, str]:
    chat = await bot.get_chat(chat_id)
    if chat.type != ChatType.SUPERGROUP:
        return False, "Auto-ban requires a Telegram supergroup. Convert the group to a supergroup."
    me = await bot.get_chat_member(chat_id, (await bot.get_me()).id)
    if me.status != ChatMemberStatus.ADMINISTRATOR:
        return False, "Bot is not an administrator."
    if not me.can_restrict_members:
        return False, "Bot lacks 'Ban Users / Restrict Members' permission."
    return True, "ok"


async def is_group_creator(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return m.status == ChatMemberStatus.CREATOR
    except Exception:
        return False


def is_bot_owner(user_id: int, owner_id: int) -> bool:
    """Return True when the requester is the configured bot owner."""
    return bool(user_id and owner_id and user_id == owner_id)

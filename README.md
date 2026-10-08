# Telegram Auto Leave Guard Bot — Complete Build

## What it does
A normal member leaves a protected Telegram **supergroup** -> the bot detects the leave -> optionally waits for the configured grace period -> rechecks the member -> bans them with `ban_chat_member` so they cannot rejoin until unbanned.

## Important Telegram requirement
This bot requires a **supergroup** and the bot must be an administrator with **Ban Users / Restrict Members** permission. Basic groups cannot use the Bot API ban flow reliably; convert the group to a supergroup.

## Setup on Windows
1. Install Python 3.10+.
2. Open PowerShell in this folder.
3. Run:
   `python -m pip install -r requirements.txt`
4. Copy `.env.example` to `.env`.
5. Put your bot token and owner numeric Telegram ID in `.env`.
6. Add the bot to the target supergroup as administrator and enable **Ban Users / Restrict Members**.
7. Start:
   `python bot.py`

## First group setup
Run as the group creator:
`/authorize`

Then check:
`/test`
`/status`

For instant ban:
`/grace 0`

For 10 seconds:
`/grace 10`

## Commands
- `/authorize` — group creator only
- `/on`, `/off` — protection toggle
- `/grace N` — 0..3600 seconds
- `/reason TEXT` — default ban reason
- `/whitelist USER_ID`
- `/unwhitelist USER_ID`
- `/unban USER_ID`
- `/status`
- `/test`

## Why this build is reliable
The primary leave detector is the Telegram `chat_member` update. A second `left_chat_member` service-message handler is included. Before banning after grace time, the bot calls `get_chat_member` again so a member who rejoined is not banned accidentally.

The code logs every important step. If `/test` says permission is OK but a leave produces no `CHAT_MEMBER_UPDATE` log, the issue is Telegram update delivery or a different process using the same bot token—not the ban API call.

## Do not run two copies
Only one polling process should use the same bot token. If two copies run, Telegram can report a polling conflict.

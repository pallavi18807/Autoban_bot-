# Leave -> Ban workflow

1. Member is in a Telegram supergroup.
2. Telegram sends a `chat_member` update when the member leaves.
3. Bot checks that the new status is `LEFT` and the old status was `MEMBER` or `RESTRICTED`.
4. If grace is 0, the bot immediately checks status and calls `ban_chat_member`.
5. If grace is greater than 0, the bot waits, checks status again, then bans only if the user is still `LEFT`.
6. Ban failure is logged and a failure notification is sent.
7. Successful ban is logged and a success notification is sent.

"""Post to a Telegram group through a bot.

Setup: message @BotFather in Telegram, send /newbot, and copy the token it gives you.
Add the bot to your group and send /start@YourBotName there (bots only see messages
addressed to them). Callout then finds the group itself (find_groups) by asking Telegram
which chats the bot was added to or messaged in.
"""

from __future__ import annotations

import re

from .posting import Reply, Sender, post_json

API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4096  # Telegram's limit for one message
TOKEN = re.compile(r"^\d{5,}:[\w-]{30,}$")
CHAT_ID = re.compile(r"^-?\d{3,}$")


def _explain(status: int, data: dict) -> str:
    desc = str(data.get("description") or "") if isinstance(data, dict) else ""
    if status == 401:
        return "Telegram doesn't recognize this bot token. Copy it again from @BotFather."
    if status == 403:
        return "The bot isn't in that group anymore (or was blocked). Add it to the group again."
    if status == 400 and "chat not found" in desc.lower():
        return "Telegram can't find that group. Add the bot to the group, then click Find my group."
    return f"Telegram answered {status}" + (f": {desc}" if desc else ".")


def sender(token: str, chat_id: str, post=None) -> Sender:
    """A function that sends one message to this group. `post` is swappable for tests."""
    url = API.format(token=token, method="sendMessage")

    def send(text: str) -> Reply:
        payload = {"chat_id": chat_id, "text": text[:MAX_LEN], "disable_web_page_preview": True}
        status, data = (post or post_json)(url, payload)
        if status == 429:
            wait = (data.get("parameters") or {}).get("retry_after", 1) if isinstance(data, dict) else 1
            return Reply(False, "Telegram is rate-limiting messages.", float(wait or 1))
        if status >= 300 or not data.get("ok", True):
            return Reply(False, _explain(status, data))
        return Reply(True)

    return send


def find_groups(token: str, post=None) -> dict:
    """Ask Telegram which groups the bot has been added to or messaged in recently.

    Returns {"ok": True, "groups": [{"id": "-100…", "title": "…"}]} newest first,
    or {"ok": False, "error": "…"}.
    """
    try:
        status, data = (post or post_json)(API.format(token=token, method="getUpdates"), {"limit": 100})
    except Exception as e:
        return {"ok": False, "error": f"Couldn't reach Telegram: {e}"}
    if status >= 300 or not data.get("ok"):
        return {"ok": False, "error": _explain(status, data)}
    seen: dict[str, str] = {}
    for update in reversed(data.get("result") or []):  # newest first
        for key in ("my_chat_member", "message", "channel_post", "edited_message"):
            chat = (update.get(key) or {}).get("chat") or {}
            if chat.get("type") in ("group", "supergroup", "channel") and chat.get("id") is not None:
                seen.setdefault(str(chat["id"]), str(chat.get("title") or "Unnamed group"))
    return {"ok": True, "groups": [{"id": cid, "title": title} for cid, title in seen.items()]}


def format_post(badge: str, text: str) -> str:
    return f"{badge} · {text}"

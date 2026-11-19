"""Post to a Discord channel through a webhook link."""

from __future__ import annotations

from .posting import Reply, Sender, post_json

MAX_LEN = 2000  # Discord's limit for one message


def _explain(status: int, data: dict) -> str:
    if status in (401, 404):
        return "Discord says this webhook doesn't exist. It may have been deleted: copy a new webhook link."
    msg = data.get("message") if isinstance(data, dict) else None
    return f"Discord answered {status}" + (f": {msg}" if msg else ".")


def sender(url: str, post=None) -> Sender:
    """A function that sends one message to this webhook. `post` is swappable for tests."""

    def send(text: str) -> Reply:
        payload = {"content": text[:MAX_LEN], "allowed_mentions": {"parse": []}}  # never ping anyone
        status, data = (post or post_json)(url, payload)
        if status == 429:
            return Reply(False, "Discord is rate-limiting messages.", float(data.get("retry_after", 1) or 1))
        if status >= 300:
            return Reply(False, _explain(status, data))
        return Reply(True)

    return send


def format_post(badge: str, text: str) -> str:
    return f"**{badge}** · {text}" if badge == "LIVE" else f"{badge} · {text}"

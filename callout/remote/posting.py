"""Deliver messages to a chat service on a background thread.

Posting never holds up an order: messages queue up here and go out one by one.
If the service rate-limits, we wait as long as it asks. If it fails, the message
is dropped and the error reported, never retried forever.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from .. import __version__

USER_AGENT = f"Callout/{__version__} (+https://github.com/aidangao1/callout)"


@dataclass
class Reply:
    ok: bool
    error: str = ""
    retry_after: float | None = None  # set when the service says "slow down"


Sender = Callable[[str], Reply]


def post_json(url: str, payload: dict, timeout: float = 10) -> tuple[int, dict]:
    """POST JSON and return (HTTP status, JSON body or {})."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


class QueuedPoster:
    """Queue messages for one destination and deliver them in order on a background thread."""

    def __init__(self, name: str, send: Sender, on_error: Callable[[str], None] | None = None, max_queue: int = 50):
        self.name = name
        self._send = send
        self._on_error = on_error or (lambda msg: None)
        self._q: queue.Queue = queue.Queue(maxsize=max_queue)
        self._thread = threading.Thread(target=self._run, name=f"post-{name.lower()}", daemon=True)
        self._thread.start()

    def post(self, text: str) -> None:
        """Queue a message. Never blocks; if the queue is full the message is dropped."""
        try:
            self._q.put_nowait(text)
        except queue.Full:
            self._on_error(f"{self.name} posts are backing up; some were skipped.")

    def close(self, wait: float = 2.0) -> None:
        self._q.put(None)
        self._thread.join(wait)

    def _run(self) -> None:
        while (text := self._q.get()) is not None:
            for _attempt in range(3):
                try:
                    reply = self._send(text)
                except Exception as e:  # offline, DNS, TLS...
                    reply = Reply(False, f"Couldn't reach {self.name}: {e}")
                if reply.retry_after is not None:
                    time.sleep(min(reply.retry_after, 10))
                    continue
                if not reply.ok:
                    self._on_error(reply.error)
                break


def send_once(name: str, send: Sender, text: str) -> dict:
    """Send one message now and report what happened (for the Settings screen's test buttons)."""
    try:
        reply = send(text)
    except Exception as e:
        return {"ok": False, "error": f"Couldn't reach {name}: {e}"}
    if reply.retry_after is not None:
        return {"ok": False, "error": f"{name} is rate-limiting messages. Try again in a moment."}
    return {"ok": True} if reply.ok else {"ok": False, "error": reply.error}

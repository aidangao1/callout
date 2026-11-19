"""Callout's side of the phone link.

Keeps a websocket open to the relay, reconnecting by itself, and passes sealed frames
between the session and the phone. See phone_protocol.py for what's inside a frame.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from .phone_protocol import Channel, Pairing, ProtocolError

# What the screen shows for each state.
STATUS_TEXT = {
    "off": "Not paired",
    "connecting": "Connecting to the relay…",
    "waiting": "Waiting for the phone",
    "connected": "Phone connected",
    "offline": "Can't reach the relay. Retrying…",
}


class PhoneLink:
    def __init__(
        self,
        pairing: Pairing,
        on_message: Callable[[dict], Any],
        on_status: Callable[[str, str], None] | None = None,
        connect=None,
    ):
        self.pairing = pairing
        self._on_message = on_message
        self._on_status = on_status or (lambda status, detail: None)
        self._connect = connect
        self._ws = None
        self._channel: Channel | None = None
        self._stopped = False
        self.status = "connecting"
        self.detail = ""
        self.bad_frames = 0

    def _set(self, status: str, detail: str = "") -> None:
        if (status, detail) != (self.status, self.detail):
            self.status, self.detail = status, detail
            self._on_status(status, detail)

    @property
    def phone_present(self) -> bool:
        return self.status == "connected"

    async def run(self) -> None:
        """Stay connected until stop(). Backs off up to 30 s between attempts."""
        if self._connect is None:
            from websockets.asyncio.client import connect

            self._connect = connect
        delay = 1.0
        while not self._stopped:
            self._set("connecting")
            try:
                async with self._connect(
                    self.pairing.socket_url("pc"), max_size=2**20, ping_interval=20, open_timeout=10, close_timeout=2
                ) as ws:
                    self._ws, self._channel = ws, Channel(self.pairing, "pc")
                    self._set("waiting")
                    delay = 1.0
                    async for frame in ws:
                        await self._receive(frame)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # network down, relay restarting, DNS...
                self._set("offline", str(e)[:120])
            finally:
                self._ws = None
            if self._stopped:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)
        self._set("off")

    async def _receive(self, frame) -> None:
        if isinstance(frame, str):  # plain notes from the relay itself, never commands
            try:
                note = json.loads(frame)
            except ValueError:
                return
            if note.get("relay") == "peer":
                self._set("connected" if note.get("present") else "waiting")
            return
        try:
            msg = self._channel.open(frame)
        except ProtocolError as e:
            self.bad_frames += 1
            self._set(self.status, str(e))
            return
        result = self._on_message(msg)
        if asyncio.iscoroutine(result):
            await result

    async def send(self, kind: str, **payload) -> bool:
        """Seal and send one message to the phone. False if there's no connection right now."""
        ws, ch = self._ws, self._channel
        if ws is None or ch is None:
            return False
        try:
            await ws.send(ch.seal(kind, **payload))
            return True
        except Exception:
            return False

    async def stop(self) -> None:
        self._stopped = True
        ws = self._ws
        if ws is not None:
            await ws.close()

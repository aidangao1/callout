"""A local stand-in for the Cloudflare relay (relay/worker.js), with the same behavior:
one PC and one phone per room, frames passed through untouched, presence notes as text."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlparse

from websockets.asyncio.server import serve


class FakeRelay:
    def __init__(self):
        self.rooms: dict[str, dict] = {}
        self.frames: list[bytes] = []  # everything that passed through, to check it's ciphertext
        self.server = None
        self.port = 0

    async def start(self) -> str:
        self.server = await serve(self._handle, "127.0.0.1", 0, max_size=2**20)
        self.port = self.server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{self.port}"

    async def stop(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, ws):
        u = urlparse(ws.request.path)
        role = parse_qs(u.query).get("role", [""])[0]
        if not u.path.startswith("/room/") or role not in ("pc", "phone"):
            await ws.close(1008, "bad request")
            return
        room = self.rooms.setdefault(u.path[6:], {})
        other = "phone" if role == "pc" else "pc"
        if role in room:
            await room[role].close(1000, "replaced")
        room[role] = ws
        await self._note(ws, other in room)
        if other in room:
            await self._note(room[other], True)
        try:
            async for frame in ws:
                if isinstance(frame, bytes) and other in room:
                    self.frames.append(frame)
                    await room[other].send(frame)
        finally:
            if room.get(role) is ws:
                del room[role]
                if other in room:
                    await self._note(room[other], False)

    @staticmethod
    async def _note(ws, present: bool):
        try:
            await ws.send(json.dumps({"relay": "peer", "present": present}))
        except Exception:
            pass


async def drain(ws, timeout=0.2):
    """Read whatever arrives within timeout."""
    out = []
    try:
        while True:
            out.append(await asyncio.wait_for(ws.recv(), timeout))
    except (TimeoutError, Exception):
        return out

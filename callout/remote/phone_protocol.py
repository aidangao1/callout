"""The phone link's wire format: pairing, end-to-end encryption, and replay protection.

The phone and the PC never connect to each other directly. Both connect out to a small
relay (relay/ in this repo) and meet in a "room". Everything they send is sealed with a
key that only exists on the two devices: it travels inside the pairing QR code, after
the "#" of the link, which browsers and apps never send to any server. So the relay
only ever sees ciphertext, and can't read or invent a command.

A frame on the wire is: 24-byte nonce + NaCl secretbox(JSON). The JSON always carries
the sender ("pc" or "phone"), a per-connection id, a counter and a timestamp, so an
old or repeated frame (say, a captured "confirm") is refused.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlparse

from nacl.exceptions import CryptoError
from nacl.secret import SecretBox

MAX_SKEW_S = 120  # how far apart the phone's and the PC's clocks may be
VERSION = 1


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Pairing:
    relay: str  # https://callout-relay.example.workers.dev
    room: str  # random, url-safe, 22 chars
    key: bytes  # 32 random bytes

    @classmethod
    def new(cls, relay: str) -> Pairing:
        return cls(relay.rstrip("/"), _b64(secrets.token_bytes(16)), secrets.token_bytes(SecretBox.KEY_SIZE))

    def link(self) -> str:
        """What the QR code holds. Opening it on a phone shows the relay's test page; the app reads it too."""
        return f"{self.relay}/pair#" + urlencode({"v": VERSION, "r": self.room, "k": _b64(self.key)})

    @classmethod
    def from_link(cls, link: str) -> Pairing:
        u = urlparse(link)
        q = {k: v[0] for k, v in parse_qs(u.fragment).items()}
        try:
            key = _unb64(q["k"])
            room = q["r"]
        except (KeyError, ValueError) as e:
            raise ProtocolError("That isn't a Callout pairing link.") from e
        if len(key) != SecretBox.KEY_SIZE or len(room) < 16:
            raise ProtocolError("That isn't a Callout pairing link.")
        return cls(f"{u.scheme}://{u.netloc}", room, key)

    def socket_url(self, role: str) -> str:
        """The relay's websocket address for one side of this room."""
        base = self.relay.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        return f"{base}/room/{self.room}?role={role}"

    def to_config(self) -> dict:
        return {"relay": self.relay, "room": self.room, "key": _b64(self.key)}

    @classmethod
    def from_config(cls, relay: str, room: str, key: str) -> Pairing | None:
        if not (relay and room and key):
            return None
        return cls(relay.rstrip("/"), room, _unb64(key))


class Channel:
    """Seals frames we send and opens frames we receive, for one side of a pairing."""

    def __init__(self, pairing: Pairing, me: str, clock=time.time):
        if me not in ("pc", "phone"):
            raise ValueError(me)
        self.me = me
        self.peer = "phone" if me == "pc" else "pc"
        self._box = SecretBox(pairing.key)
        self._clock = clock
        self._id = _b64(secrets.token_bytes(6))  # this connection; a reconnect gets a new one
        self._n = 0
        self._seen: dict[str, int] = {}  # peer connection id -> highest counter seen

    def seal(self, kind: str, **payload) -> bytes:
        self._n += 1
        msg = {"from": self.me, "id": self._id, "n": self._n, "ts": round(self._clock() * 1000), "t": kind, **payload}
        return bytes(self._box.encrypt(json.dumps(msg, separators=(",", ":")).encode()))

    def open(self, frame: bytes) -> dict:
        """Decrypt and check one frame. Raises ProtocolError for anything forged, stale or replayed."""
        try:
            msg = json.loads(self._box.decrypt(bytes(frame)))
        except (CryptoError, ValueError, TypeError) as e:
            raise ProtocolError("A message couldn't be decrypted. Pair the phone again.") from e
        if not isinstance(msg, dict) or msg.get("from") != self.peer:
            raise ProtocolError("A message came from the wrong side.")
        if abs(self._clock() * 1000 - float(msg.get("ts", 0))) > MAX_SKEW_S * 1000:
            raise ProtocolError("A message was too old (or the phone's clock is wrong).")
        cid, n = str(msg.get("id", "")), int(msg.get("n", 0))
        if n <= self._seen.get(cid, 0):
            raise ProtocolError("A message was repeated.")
        self._seen[cid] = n
        if len(self._seen) > 64:  # forget long-gone connections
            self._seen = dict(list(self._seen.items())[-32:])
        return msg


def pcm_to_b64(pcm: bytes) -> str:
    return base64.b64encode(pcm).decode()


def b64_to_pcm(s: str) -> bytes:
    return base64.b64decode(s)

"""Turn IBKR's raw error messages into short, plain sentences Callout can say out loud."""

from __future__ import annotations

import re

# ib_async formats order errors as "Error 201, reqId 13: <text>, contract: Future(...)".
_RAW = re.compile(r"^(?:Error|Warning)\s+(-?\d+),\s*reqId\s+-?\d+:\s*(.*?)(?:,\s*contract:.*)?$", re.S)

_RULES: list[tuple[tuple[str, ...], str]] = [
    (
        ("equity with loan", "initial margin", "maintenance margin", "buying power", "insufficient", "margin"),
        "Not enough buying power for this order.",
    ),
    (
        ("trading permission", "no permission", "not have permission", "permissions"),
        "This account doesn't have permission to trade this contract.",
    ),
    (("read-only", "read only"), "TWS is set to read-only. Untick Read-Only API in TWS's API settings."),
    (
        ("size limit", "value limit", "precaution", "exceeds the", "percentage constraint"),
        "TWS's precaution limits stopped this order. Check Presets in TWS.",
    ),
    (
        (
            "exchange is closed",
            "market is closed",
            "outside of trading hours",
            "outside regular trading hours",
            "not open for trading",
            "trading hours",
        ),
        "The exchange is closed for this contract.",
    ),
    (
        ("market data", "not subscribed"),
        "This account has no market data for this contract. Check market data in IBKR's Client Portal.",
    ),
    (("no security definition",), "IBKR doesn't recognize this contract."),
    (("duplicate order id",), "IBKR rejected a duplicate order ID. Restart Callout and try again."),
]

_CODES = {
    200: "IBKR doesn't recognize this contract.",
    103: "IBKR rejected a duplicate order ID. Restart Callout and try again.",
    1100: "TWS lost its connection to IBKR.",
    10167: "This account has no market data for this contract. Check market data in IBKR's Client Portal.",
    10168: "This account has no market data for this contract. Check market data in IBKR's Client Portal.",
}


def split_raw(raw: str) -> tuple[int | None, str]:
    """('Error 201, reqId 13: Order rejected - reason: ...') -> (201, 'Order rejected - reason: ...')."""
    m = _RAW.match((raw or "").strip())
    if not m:
        return None, (raw or "").strip()
    return int(m.group(1)), m.group(2).strip()


def plain_reason(code: int | None, text: str) -> str:
    """A short sentence for an IBKR error, falling back to IBKR's own reason, tidied up."""
    low = (text or "").lower()
    for keys, sentence in _RULES:
        if any(k in low for k in keys):
            return sentence
    if code in _CODES:
        return _CODES[code]
    reason = re.sub(r"^\s*order rejected\s*-\s*reason\s*:\s*", "", text or "", flags=re.I)
    reason = re.sub(r"<[^>]+>", " ", reason)  # IBKR sometimes sends HTML
    reason = re.sub(r"\s+", " ", reason).strip(" .")
    if not reason:
        return "IBKR rejected the order."
    letters = [c for c in reason if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:  # SHOUTING IN ALL CAPS
        reason = reason.lower()
    if len(reason) > 160:
        reason = reason[:157].rsplit(" ", 1)[0] + "…"
    return "IBKR: " + reason[0].upper() + reason[1:] + ("" if reason.endswith("…") else ".")


def plain_from_raw(raw: str) -> str:
    code, text = split_raw(raw)
    return plain_reason(code, text)

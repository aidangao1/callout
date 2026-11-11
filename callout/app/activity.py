"""How log records read in the Activity list."""

from __future__ import annotations

from ..trading.contracts import describe_position


def pretty_intent(intent: str | None) -> str:
    if not intent:
        return ""
    parts = intent.split()
    return " ".join([parts[0].capitalize()] + parts[1:])


def _fmt_ms(ms: float | None) -> str:
    if ms is None:
        return ""
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:.0f} ms"


def feed_row(rec: dict) -> dict | None:
    """Turn one log record into an Activity row, or None for records the screen skips."""
    ev = rec.get("event")
    ts = (rec.get("ts") or "")[11:19]
    row = {"time": ts, "kind": "", "text": "", "meta": "", "cat": "orders", "strong": False}
    if ev == "heard":
        row["cat"] = "voice"
        text = rec.get("text", "")
        if rec.get("source") == "ui":
            row.update(kind="Button", text=pretty_intent(rec.get("intent")) or text)
        elif rec.get("rejected"):
            row.update(kind="Rejected", text=(f'"{text}" · ' if text else "") + f"{rec['rejected']}, nothing sent")
        elif not rec.get("intent"):
            row.update(kind="Rejected", text=f'"{text}" · not a command, nothing sent')
        else:
            row.update(
                kind="Heard", text=f'"{text}" → {pretty_intent(rec.get("intent"))}', meta=_fmt_ms(rec.get("stt_ms"))
            )
    elif ev == "awaiting_confirm":
        extra = ""
        if "position" in rec:
            extra = f" · {describe_position(rec['position'])} → {describe_position(rec['resulting'])}"
        row.update(kind="Read back", text=pretty_intent(rec.get("intent")) + extra)
    elif ev == "confirmed":
        row.update(kind="Confirmed", text=pretty_intent(rec.get("intent")))
    elif ev == "cancelled":
        why = {
            "user": "you cancelled",
            "timeout": "not confirmed in time",
            "new_command": "replaced by a new command",
            "unclear_input": "unclear speech",
        }.get(rec.get("by"), rec.get("by", ""))
        row.update(kind="Cancelled", text=f"{pretty_intent(rec.get('intent'))} · {why}")
    elif ev == "blocked":
        row.update(kind="Blocked", text=str(rec.get("reason", "")))
    elif ev == "order_result":
        status = rec.get("status", "")
        if status == "Filled":
            verb = "Bought" if rec.get("action") == "BUY" else "Sold"
            price = rec.get("avg_price")
            row.update(
                kind="Filled",
                strong=True,
                text=f"{verb} {rec.get('filled')} {rec.get('contract')}" + (f" at {price:.2f}" if price else ""),
            )
        else:
            row.update(
                kind=status or "Order",
                strong=True,
                text=rec.get("message") or f"{rec.get('action')} {rec.get('quantity')} {rec.get('contract')}",
            )
        row["meta"] = _fmt_ms(rec.get("release_to_done_ms", rec.get("send_to_done_ms")))
    elif ev == "position_mismatch":
        broker, expected = describe_position(rec.get("broker", 0)), describe_position(rec.get("expected", 0))
        row.update(kind="Warning", strong=True, text=f"Broker shows {broker}, expected {expected}")
    elif ev == "orders_cancelled":
        n = int(rec.get("requested") or 0)
        if not n:
            return None  # leftover orders get their own Warning row from flatten_result
        row.update(kind="Orders", text=f"Cancelled {n} working order{'s' if n > 1 else ''}")
    elif ev == "flatten_result":
        n = int(rec.get("still_working") or 0)
        if not n:
            return None
        row.update(
            kind="Warning", strong=True, text=f"{n} order{'s' if n > 1 else ''} still working in TWS. Cancel in TWS."
        )
    elif ev == "flatten_incomplete":
        row.update(kind="Warning", strong=True, text="Flatten incomplete. Check TWS.")
    elif ev == "startup":
        row.update(
            kind="Connected", cat="system", text=f"{rec.get('account')} · {rec.get('broker')} · {rec.get('mode')}"
        )
    elif ev == "disconnected":
        row.update(kind="Connection", cat="system", strong=True, text="Lost connection to the broker")
    elif ev == "contract_roll":
        row.update(kind="Roll", cat="system", text=f"{rec.get('old')} → {rec.get('new')}")
    elif ev == "contract_roll_deferred":
        row.update(kind="Roll", cat="system", text=f"Waiting until you're flat in {rec.get('old')}")
    elif ev == "broker_error":
        row.update(kind="Broker", cat="system", text=f"[{rec.get('code')}] {rec.get('message')}")
    elif ev in ("error", "connect_failed"):
        row.update(kind="Error", cat="system", strong=True, text=str(rec.get("error", "")))
    else:
        return None
    return row

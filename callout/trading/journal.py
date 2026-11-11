"""Append-only JSONL log: one line per event, one file per day.

Every utterance, decision, order and fill lands here with millisecond
timestamps, so live behaviour can be audited trade by trade.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .market_hours import ET


class Journal:
    def __init__(self, log_dir: str | Path, session: str = ""):
        self.dir = Path(log_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session = session

    def path_for(self, ts: datetime) -> Path:
        return self.dir / f"callout-{ts:%Y-%m-%d}.jsonl"

    def log(self, event: str, **fields: Any) -> dict:
        ts = datetime.now(ET)
        record = {"ts": ts.isoformat(timespec="milliseconds"), "event": event, "session": self.session, **fields}
        with self.path_for(ts).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        return record


class NullJournal(Journal):
    def __init__(self):  # noqa: D401 - no files written
        self.records: list[dict] = []
        self.session = "test"

    def log(self, event: str, **fields: Any) -> dict:
        record = {"event": event, **fields}
        self.records.append(record)
        return record

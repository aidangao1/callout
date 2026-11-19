"""Open Callout when Windows starts.

Works the way Windows intends: a small launcher file in your Startup folder
(Win+R, shell:startup). Turning it off deletes that one file. Nothing else changes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

LAUNCHER = "Callout.cmd"


def startup_folder() -> Path | None:
    """Windows' per-user Startup folder, or None on other systems."""
    if sys.platform != "win32" and "CALLOUT_STARTUP_DIR" not in os.environ:
        return None
    override = os.environ.get("CALLOUT_STARTUP_DIR")  # tests point this at a temporary folder
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def supported() -> bool:
    return startup_folder() is not None


def is_enabled() -> bool:
    folder = startup_folder()
    return bool(folder and (folder / LAUNCHER).exists())


def set_enabled(on: bool, root: Path) -> None:
    """Add or remove the launcher. `root` is the Callout folder (where start.bat is)."""
    folder = startup_folder()
    if folder is None:
        raise OSError("Opening Callout at startup only works on Windows.")
    launcher = folder / LAUNCHER
    if not on:
        launcher.unlink(missing_ok=True)
        return
    start = root / "start.bat"
    if not start.exists():
        raise OSError(f"Can't find start.bat in {root}.")
    folder.mkdir(parents=True, exist_ok=True)
    # Starts minimized, from the Callout folder, the same way double-clicking start.bat does.
    launcher.write_text(
        "@echo off\r\n"
        "rem Opens Callout when you sign in to Windows. Turn it off in Callout: Settings > Phone.\r\n"
        f'start "Callout" /min /d "{root}" "{start}"\r\n',
        encoding="utf-8",
    )

"""Swap in a downloaded Callout release, reinstall, and reopen Callout.

The app copies this file into .update/ and runs it after its window closes. It imports
nothing from Callout on purpose: it replaces the very files Callout runs from.

Your settings (config.toml), logs, speech models and the Python environment (.venv) are
never touched. If anything goes wrong, the previous version is put back.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

KEEP = {"config.toml", "logs", "models", ".venv", ".git", ".update", ".update-backup"}
# Files older versions had at the top level that have since moved or gone.
OBSOLETE = ["mic-test.bat", "check-connection.bat", "start-console.bat", "config.example.toml"]


def wait_for_exit(pid: int, timeout: float = 120) -> bool:
    if pid <= 0:
        return True
    end = time.monotonic() + timeout
    if sys.platform == "win32":
        import ctypes

        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)  # type: ignore[attr-defined]
        if not handle:
            return True  # already gone
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000)) == 0  # type: ignore[attr-defined]
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.2)
    return False


def _remove(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    elif p.exists() or p.is_symlink():
        p.unlink()


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        shutil.copy2(src, dst)


def swap(root: Path, release: Path, backup: Path, say) -> list[str]:
    """Move the current files into backup and copy the release in. Returns the names installed."""
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(parents=True)
    names = [p.name for p in release.iterdir() if p.name not in KEEP]
    if "callout" not in names or "pyproject.toml" not in names:
        raise RuntimeError("The release folder is incomplete.")
    old = [n for n in names if (root / n).exists() or (root / n).is_symlink()]
    if (release / "troubleshooting").is_dir():
        old += [n for n in OBSOLETE if (root / n).exists() and n not in names]
    for n in old:
        shutil.move(str(root / n), str(backup / n))
    say(f"Backed up {len(old)} items to {backup.name}.")
    for n in names:
        _copy(release / n, root / n)
    say(f"Copied in {len(names)} items.")
    return names


def roll_back(root: Path, backup: Path, installed: list[str], say) -> None:
    for n in installed:
        try:
            _remove(root / n)
        except OSError as e:
            say(f"  couldn't remove {n}: {e}")
    for p in backup.iterdir():
        try:
            _remove(root / p.name)
            shutil.move(str(p), str(root / p.name))
        except OSError as e:
            say(f"  couldn't restore {p.name}: {e}")
    say("Put the previous version back.")


def reopen(root: Path, python: str) -> None:
    if sys.platform == "win32" and (root / "start.bat").exists():
        subprocess.Popen(["cmd", "/c", "start", "", "start.bat"], cwd=str(root))
    else:
        subprocess.Popen([python, "-m", "callout", "app"], cwd=str(root), start_new_session=True)


def install(a, root: Path, release: Path, log, log_path: Path, say) -> bool:
    """Swap the files and reinstall. On any failure, put the previous version back."""
    backup = root / ".update-backup"
    installed: list[str] = []
    try:
        installed = swap(root, release, backup, say)
        say("Installing. This can take a minute...")
        cmd = a.pip or [a.python, "-m", "pip", "install", "--disable-pip-version-check", "-e", str(root)]
        r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
        log.write(r.stdout + r.stderr)
        if r.returncode != 0:
            raise RuntimeError(f"Installing failed (exit {r.returncode}). Details are in {log_path.name}.")
    except Exception as e:
        say(f"Update failed: {e}")
        roll_back(root, backup, installed, say)
        return False
    say(f"Done. Callout {a.version} is installed.")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--release", required=True, type=Path)
    ap.add_argument("--version", required=True)
    ap.add_argument("--wait-pid", type=int, default=0)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--pip", nargs="*", help="command that reinstalls (default: python -m pip install -e <root>)")
    ap.add_argument("--no-restart", action="store_true")
    a = ap.parse_args(argv)
    root, release = a.root.resolve(), a.release.resolve()

    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    log_path = logs / f"update-{datetime.now():%Y%m%d-%H%M%S}.log"
    with open(log_path, "a", encoding="utf-8") as log:

        def say(msg: str) -> None:
            line = f"[{datetime.now():%H:%M:%S}] {msg}"
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()

        say(f"Updating Callout to {a.version}. Keep this window open; it closes by itself.")
        if not wait_for_exit(a.wait_pid):
            say("Callout didn't close. Close it, then run start.bat. Nothing was changed.")
            return 1
        ok = install(a, root, release, log, log_path, say)

    staging = root / ".update"
    if ok and staging in release.parents:
        shutil.rmtree(staging, ignore_errors=True)  # the download; the backup stays until next time
    if not a.no_restart:
        reopen(root, a.python)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

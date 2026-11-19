"""Updating Callout from its GitHub releases, from inside the app.

check() asks GitHub for the newest release. prepare() downloads it, makes sure it really is
Callout at that version, and unpacks it into .update/ inside the Callout folder. The swap
happens after the window closes, in apply_update.py, which runs on its own so it can replace
the files the app runs from.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .. import __version__

LATEST = "https://api.github.com/repos/{repo}/releases/latest"
USER_AGENT = f"Callout/{__version__} (+https://github.com/aidangao1/callout)"
MAX_DOWNLOAD = 50 * 1024 * 1024
STAGING = ".update"


class UpdateError(Exception):
    pass


@dataclass
class Release:
    version: str  # "0.10.0"
    tag: str  # as tagged on GitHub, e.g. "0.10.0" or "v0.10.0"
    notes: str
    page: str  # the release page on GitHub
    zip_url: str


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v0.10.0' or '0.10.0' -> (0, 10, 0). Anything else (betas, words) -> None."""
    m = re.fullmatch(r"[vV]?(\d+(?:\.\d+){1,3})", (text or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(tag: str, current: str = __version__) -> bool:
    new, cur = parse_version(tag), parse_version(current)
    if new is None or cur is None:
        return False
    width = max(len(new), len(cur))
    return new + (0,) * (width - len(new)) > cur + (0,) * (width - len(cur))


def _request(url: str, accept: str, timeout: float):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def _get_json(url: str) -> dict:
    with _request(url, "application/vnd.github+json", 10) as r:
        return json.loads(r.read())


def latest_release(repo: str, get_json=None) -> Release | None:
    """The newest published release, or None if the repo has none yet."""
    try:
        data = (get_json or _get_json)(LATEST.format(repo=repo))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise UpdateError(f"GitHub answered {e.code}.") from e
    except (OSError, ValueError) as e:
        raise UpdateError(f"Couldn't reach GitHub: {e}") from e
    tag = str(data.get("tag_name") or "")
    version = parse_version(tag)
    if version is None or not data.get("zipball_url"):
        return None
    return Release(
        version=".".join(map(str, version)),
        tag=tag,
        notes=str(data.get("body") or "").strip(),
        page=str(data.get("html_url") or ""),
        zip_url=str(data["zipball_url"]),
    )


# ---- is this install one we can update? ---------------------------------------------------------


def install_root() -> Path:
    """The Callout folder: the one with install.bat, pyproject.toml and the callout package."""
    return Path(__file__).resolve().parents[2]


def why_not_updatable(root: Path) -> str | None:
    """None if the app can update itself here, else a sentence saying how to update instead."""
    if not ((root / "pyproject.toml").is_file() and (root / "callout" / "__init__.py").is_file()):
        return "Callout is installed as a Python package here. Update it with pip."
    if (root / ".git").exists():
        return "This copy of Callout is a git checkout. Update it with git pull."
    return None


# ---- download and unpack ------------------------------------------------------------------------


def download(url: str, dest: Path, opener=None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (opener or _request)(url, "*/*", 60) as r, open(dest, "wb") as f:
            total = 0
            while chunk := r.read(1 << 16):
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise UpdateError("The download is far bigger than a Callout release. Stopped.")
                f.write(chunk)
    except UpdateError:
        dest.unlink(missing_ok=True)
        raise
    except OSError as e:
        dest.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {e}") from e
    return dest


def unpack(zip_path: Path, version: str, into: Path) -> Path:
    """Unpack a release zip and check it's Callout at `version`. Returns the release's folder."""
    if into.exists():
        shutil.rmtree(into)
    into.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                p = Path(name)
                if p.is_absolute() or ".." in p.parts or ":" in name:
                    raise UpdateError("The download contains unsafe file paths. Stopped.")
            z.extractall(into)
    except zipfile.BadZipFile as e:
        raise UpdateError("The download isn't a valid zip file.") from e
    tops = [p for p in into.iterdir() if p.is_dir()]
    root = tops[0] if len(tops) == 1 and not (into / "pyproject.toml").exists() else into
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        init = (root / "callout" / "__init__.py").read_text(encoding="utf-8")
    except (OSError, KeyError, tomllib.TOMLDecodeError) as e:
        raise UpdateError("The download doesn't look like Callout.") from e
    m = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    if project.get("name") != "callout" or not m:
        raise UpdateError("The download doesn't look like Callout.")
    if parse_version(m.group(1)) != parse_version(version) or project.get("version") != m.group(1):
        raise UpdateError(f"The release is tagged {version} but contains version {m.group(1)}. Not installing it.")
    return root


def prepare(release: Release, root: Path, opener=None) -> Path:
    """Download and unpack a release into <root>/.update. Returns the unpacked release folder."""
    staging = root / STAGING
    zip_path = download(release.zip_url, staging / f"callout-{release.version}.zip", opener)
    return unpack(zip_path, release.version, staging / release.version)


def clean_staging(root: Path) -> None:
    """Remove leftovers from an earlier update (called at startup)."""
    shutil.rmtree(root / STAGING, ignore_errors=True)


# ---- hand over to apply_update.py ------------------------------------------------------------------


def launch_apply(root: Path, release_dir: Path, version: str, pid: int, restart: bool = True) -> subprocess.Popen:
    """Start apply_update.py on its own, in its own console window on Windows. It waits for this
    process to exit, swaps in the release, reinstalls, and reopens Callout."""
    script = root / STAGING / "apply_update.py"
    shutil.copyfile(Path(__file__).with_name("apply_update.py"), script)
    cmd = [
        sys.executable,
        str(script),
        "--root",
        str(root),
        "--release",
        str(release_dir),
        "--version",
        version,
        "--wait-pid",
        str(pid),
    ]
    if not restart:
        cmd.append("--no-restart")
    kw: dict = {"cwd": str(root)}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(cmd, **kw)

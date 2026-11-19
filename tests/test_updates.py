"""Updating from GitHub releases: version checks, the downloaded zip, the file swap and rollback."""

import io
import sys
import time
import zipfile

import pytest

from callout import __version__
from callout.app import apply_update, updates
from callout.app.session import Session
from callout.app.updates import Release, UpdateError, is_newer, latest_release, parse_version, unpack
from callout.config import load_config


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


# ---- versions ----------------------------------------------------------------------------------


def test_versions():
    assert parse_version("v0.10.0") == (0, 10, 0) == parse_version("0.10.0")
    assert parse_version("0.10.0-beta") is None and parse_version("latest") is None
    assert is_newer("0.10.0", "0.9.0") and is_newer("v1.0", "0.10.0") and is_newer("0.10.1", "0.10")
    assert not is_newer("0.9.0", "0.10.0") and not is_newer("0.10.0", "0.10.0") and not is_newer("junk", "0.1")


def test_latest_release_from_github():
    data = {
        "tag_name": "v9.1.0",
        "body": "Notes",
        "html_url": "https://github.com/a/b/releases/v9.1.0",
        "zipball_url": "https://api.github.com/repos/a/b/zipball/v9.1.0",
    }
    rel = latest_release("a/b", get_json=lambda url: data)
    assert rel.version == "9.1.0" and rel.tag == "v9.1.0" and rel.notes == "Notes"
    assert latest_release("a/b", get_json=lambda url: {**data, "tag_name": "nightly"}) is None

    def offline(url):
        raise OSError("no network")

    with pytest.raises(UpdateError, match="Couldn't reach GitHub"):
        latest_release("a/b", get_json=offline)


# ---- the downloaded zip ------------------------------------------------------------------------


def make_release(version: str, *, inner_version: str | None = None, extra: dict | None = None) -> bytes:
    """A zip shaped like GitHub's source zipball for a Callout release."""
    v = inner_version or version
    top = "aidangao1-callout-abc1234/"
    files = {
        "pyproject.toml": f'[project]\nname = "callout"\nversion = "{v}"\n',
        "callout/__init__.py": f'__version__ = "{v}"\n',
        "callout/app/new_module.py": "NEW = True\n",
        "install.bat": "new install\n",
        "README.md": f"Callout {v}\n",
        "troubleshooting/mic-test.bat": "new mic test\n",
        **(extra or {}),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(top + name, text)
    return buf.getvalue()


def test_unpack_checks_it_is_callout_at_that_version(tmp_path):
    zp = tmp_path / "r.zip"
    zp.write_bytes(make_release("9.1.0"))
    folder = unpack(zp, "9.1.0", tmp_path / "out")
    assert (folder / "callout" / "app" / "new_module.py").exists()

    zp.write_bytes(make_release("9.1.0", inner_version="0.1.0"))
    with pytest.raises(UpdateError, match="tagged 9.1.0 but contains version 0.1.0"):
        unpack(zp, "9.1.0", tmp_path / "out")

    zp.write_bytes(make_release("9.1.0", extra={"../escape.txt": "x"}))
    with pytest.raises(UpdateError, match="unsafe"):
        unpack(zp, "9.1.0", tmp_path / "out")


def test_download_size_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "MAX_DOWNLOAD", 10)

    def opener(url, accept, timeout):
        return io.BytesIO(b"x" * 100)

    with pytest.raises(UpdateError, match="bigger"):
        updates.download("https://example/zip", tmp_path / "d.zip", opener)
    assert not (tmp_path / "d.zip").exists()


def test_only_plain_installs_update_themselves(tmp_path):
    assert "pip" in updates.why_not_updatable(tmp_path)
    (tmp_path / "pyproject.toml").write_text("")
    (tmp_path / "callout").mkdir()
    (tmp_path / "callout" / "__init__.py").write_text("")
    assert updates.why_not_updatable(tmp_path) is None
    (tmp_path / ".git").mkdir()
    assert "git pull" in updates.why_not_updatable(tmp_path)


# ---- swapping the files ------------------------------------------------------------------------


@pytest.fixture
def install(tmp_path):
    """An existing Callout folder, as install.bat leaves it, with user files that must survive."""
    root = tmp_path / "Callout"
    files = {
        "pyproject.toml": '[project]\nname = "callout"\nversion = "0.2.2"\n',
        "callout/__init__.py": '__version__ = "0.2.2"\n',
        "callout/old_module.py": "OLD = True\n",
        "install.bat": "old install\n",
        "README.md": "old readme\n",
        "mic-test.bat": "old mic test at the top level\n",
        "config.toml": "[broker]\nport = 7497\n",
        "logs/callout-2026-11-15.jsonl": "{}\n",
        ".venv/marker": "venv\n",
        "my-notes.txt": "the user's own file\n",
    }
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    zp = tmp_path / "release.zip"
    zp.write_bytes(make_release("9.1.0"))
    release = unpack(zp, "9.1.0", root / ".update" / "9.1.0")
    return root, release, tmp_path


def run_apply(root, release, tmp_path, pip_exit=0):
    fake_pip = tmp_path / "fake_pip.py"
    fake_pip.write_text(f"import sys; print('pip ran'); sys.exit({pip_exit})\n")
    args = ["--root", str(root), "--release", str(release), "--version", "9.1.0", "--no-restart"]
    return apply_update.main([*args, "--pip", sys.executable, str(fake_pip)])


def test_update_swaps_code_and_keeps_settings_logs_and_python(install):
    root, release, tmp_path = install
    assert run_apply(root, release, tmp_path) == 0
    assert (root / "callout" / "app" / "new_module.py").exists()
    assert not (root / "callout" / "old_module.py").exists()  # the whole package is replaced
    assert (root / "install.bat").read_text() == "new install\n"
    assert (root / "troubleshooting" / "mic-test.bat").exists() and not (root / "mic-test.bat").exists()
    assert (root / "config.toml").read_text() == "[broker]\nport = 7497\n"
    assert (root / "logs" / "callout-2026-11-15.jsonl").exists()
    assert (root / ".venv" / "marker").exists() and (root / "my-notes.txt").exists()
    assert (root / ".update-backup" / "callout" / "old_module.py").exists()
    assert not (root / ".update").exists()
    log = next((root / "logs").glob("update-*.log")).read_text()
    assert "pip ran" in log and "Done. Callout 9.1.0 is installed." in log


def test_failed_install_puts_the_old_version_back(install):
    root, release, tmp_path = install
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file() and ".update" not in p.parts}
    assert run_apply(root, release, tmp_path, pip_exit=1) == 1
    after = {
        p.relative_to(root): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
        and ".update" not in p.parts
        and ".update-backup" not in p.parts
        and not p.name.startswith("update-")
    }
    assert after == before
    log = next((root / "logs").glob("update-*.log")).read_text()
    assert "Installing failed" in log and "Put the previous version back." in log


# ---- from the app ------------------------------------------------------------------------------


@pytest.fixture
def session(tmp_path, monkeypatch):
    cfg = load_config(None)
    cfg.log_dir = str(tmp_path / "logs")
    cfg.safety.check_market_hours = False
    cfg.safety.min_seconds_between_orders = 0
    rel = Release("99.0.0", "99.0.0", "Better", "https://github.com/x", "https://api.github.com/zip")
    monkeypatch.setattr(updates, "latest_release", lambda repo: rel)
    monkeypatch.setattr(updates, "why_not_updatable", lambda root: None)
    prepared = []
    monkeypatch.setattr(updates, "prepare", lambda r, root: prepared.append(r) or tmp_path / "unpacked")
    s = Session(cfg, tmp_path / "config.toml", use_sim=True, audio=False, tts=False)
    s.start()
    assert wait_for(lambda: s.snapshot().get("connected"))
    yield s, prepared
    s.stop()


def test_app_finds_update_and_installs_only_when_flat(session):
    s, prepared = session
    view = s.check_for_update()
    assert view["state"] == "available" and view["version"] == "99.0.0" and view["current"] == __version__
    assert view["blocked"] == ""

    s.command("buy es")
    assert wait_for(lambda: s.snapshot().get("pending"))
    assert "Confirm or cancel" in s.install_update()["error"]
    s.command("confirm")
    assert wait_for(lambda: s.snapshot()["instruments"][0]["qty"] == 1)
    assert "Close your position" in s.install_update()["error"]
    assert prepared == []

    s.command("flatten")
    assert wait_for(lambda: s.snapshot()["instruments"][0]["qty"] == 0)
    time.sleep(0.3)
    assert s.install_update() == {"ok": True}
    assert s.update_ready[1] == "99.0.0"
    assert wait_for(lambda: s.snapshot()["update"]["state"] == "ready")


def test_no_update_when_already_current(session, monkeypatch):
    s, _ = session
    rel = Release(__version__, __version__, "", "", "https://api.github.com/zip")
    monkeypatch.setattr(updates, "latest_release", lambda repo: rel)
    assert s.check_for_update()["state"] == "current"
    assert not s.install_update()["ok"]

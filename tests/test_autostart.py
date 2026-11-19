"""Opening Callout when Windows starts, and the built-in relay address."""

import pytest

from callout import config
from callout.app import autostart
from callout.config import load_config


def test_startup_launcher_is_added_and_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLOUT_STARTUP_DIR", str(tmp_path / "Startup"))
    root = tmp_path / "Callout"
    root.mkdir()
    (root / "start.bat").write_text("@echo off\r\n")
    assert autostart.supported() and not autostart.is_enabled()

    autostart.set_enabled(True, root)
    launcher = (tmp_path / "Startup" / "Callout.cmd").read_text()
    assert autostart.is_enabled()
    assert f'/d "{root}"' in launcher and "/min" in launcher and str(root / "start.bat") in launcher

    autostart.set_enabled(False, root)
    assert not autostart.is_enabled() and not (tmp_path / "Startup" / "Callout.cmd").exists()


def test_startup_needs_start_bat(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLOUT_STARTUP_DIR", str(tmp_path))
    with pytest.raises(OSError, match="start.bat"):
        autostart.set_enabled(True, tmp_path / "nowhere")


def test_blank_relay_means_the_built_in_one(monkeypatch):
    cfg = load_config(None)
    monkeypatch.setattr(config, "DEFAULT_RELAY", "https://callout-relay.example.workers.dev")
    assert cfg.phone.relay == "" and cfg.phone.relay_url == "https://callout-relay.example.workers.dev"
    cfg.phone.relay = "https://my-own-relay.example.workers.dev/"
    assert cfg.phone.relay_url == "https://my-own-relay.example.workers.dev"

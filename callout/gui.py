"""The desktop window: python -m callout app  (start.bat runs this)."""

from __future__ import annotations

import sys
from pathlib import Path

from .config import ConfigError, load_config
from .session import Session

WEB = Path(__file__).with_name("web")
FULL_SIZE = (1280, 860)
MINI_SIZE = (460, 190)


class Api:
    """What the page can call (window.pywebview.api.*). Every method is thread-safe."""

    def __init__(self, session: Session):
        self._session = session
        self._window = None
        self._full_size = FULL_SIZE

    def state(self, feed_version=-1):
        return self._session.snapshot(int(feed_version))

    def command(self, text):
        self._session.command(str(text))
        return True

    def talk(self, down):
        self._session.talk(bool(down))
        return True

    def settings(self):
        return self._session.settings()

    def apply(self, patch):
        return self._session.apply(dict(patch or {}))

    def mics(self):
        return self._session.mics()

    def test_connection(self, app, mode, port=None):
        return self._session.test_connection(app, mode, port)

    def start_test(self):
        self._session.start_test()
        return True

    def say_sample(self):
        self._session.say_sample()
        return True

    def unlock_live(self, text):
        return self._session.unlock_live(str(text or ""))

    def finish_setup(self):
        self._session.finish_setup()
        return True

    def open_logs(self):
        self._session.open_logs()
        return True

    def set_mini(self, on):
        w = self._window
        if w is None:
            return False
        if on:
            self._full_size = (w.width, w.height)
            w.resize(*MINI_SIZE)
            w.on_top = True
        else:
            w.on_top = False
            w.resize(*self._full_size)
        return True


def run_app(config_path: str = "config.toml", use_sim: bool = False) -> int:
    import webview

    path = Path(config_path)
    first_run = not path.exists()
    try:
        cfg = load_config(path if path.exists() else None)
    except ConfigError as e:
        print(f"Config error: {e}")
        return 2

    session = Session(cfg, path, use_sim=use_sim, first_run=first_run)
    session.start()
    session.wait_ready()

    api = Api(session)
    window = webview.create_window(
        "Callout", url=str(WEB / "index.html"), js_api=api,
        width=FULL_SIZE[0], height=FULL_SIZE[1], min_size=(MINI_SIZE[0], MINI_SIZE[1] - 30),
        background_color="#F4F4F1",
    )
    api._window = window
    window.events.closing += lambda: session.stop()
    webview.start(private_mode=True)
    return 0


if __name__ == "__main__":
    sys.exit(run_app())

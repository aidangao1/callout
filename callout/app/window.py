"""The desktop window: python -m callout app  (start.bat runs this)."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from ..config import ConfigError, load_config
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
        """Shrink to the always-on-top strip, or go back to the full window.

        Page calls arrive on a background thread. Changing a window's size or
        always-on-top state from a background thread can freeze a Windows app,
        so the change is handed to the window's own thread and this call
        returns right away.
        """
        w = self._window
        if w is None:
            return False
        on = bool(on)
        if on:
            try:
                size = (w.width, w.height)  # reading the size is safe from any thread
                if size[0] > MINI_SIZE[0] + 50:
                    self._full_size = size
            except Exception:
                pass
        width, height = MINI_SIZE if on else self._full_size
        if not _on_window_thread(w, lambda form: _apply_winforms(form, width, height, on)):
            # Not the Windows backend: use the library's own calls, off this thread.
            threading.Thread(target=_apply_generic, args=(w, width, height, on), daemon=True).start()
        return True


def _on_window_thread(window, fn) -> bool:
    """Run fn(form) on the Windows window's own thread, without waiting. False if not on WinForms."""
    try:
        from System import Action  # type: ignore[import-not-found]
        from webview.platforms.winforms import BrowserView  # type: ignore[import-not-found]
    except Exception:
        return False
    form = BrowserView.instances.get(window.uid)
    if form is None or not hasattr(form, "BeginInvoke"):
        return False
    form.BeginInvoke(Action(lambda: fn(form)))
    return True


def _apply_winforms(form, width: int, height: int, on_top: bool) -> None:
    try:
        if on_top:
            form.resize(width, height, _north_west())
            form.TopMost = True
        else:
            form.TopMost = False
            form.resize(width, height, _north_west())
        form.Activate()
    except Exception as e:  # never let a window tweak take the app down
        print(f"Mini mode: couldn't resize the window ({e}). Resize it by hand.")


def _apply_generic(window, width: int, height: int, on_top: bool) -> None:
    try:
        if on_top:
            window.resize(width, height)
            window.on_top = True
        else:
            window.on_top = False
            window.resize(width, height)
    except Exception as e:
        print(f"Mini mode: couldn't resize the window ({e}). Resize it by hand.")


def _north_west():
    from webview.window import FixPoint

    return FixPoint.NORTH | FixPoint.WEST


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
        "Callout",
        url=str(WEB / "index.html"),
        js_api=api,
        width=FULL_SIZE[0],
        height=FULL_SIZE[1],
        min_size=(MINI_SIZE[0], MINI_SIZE[1] - 30),
        background_color="#F4F4F1",
    )
    api._window = window
    window.events.closing += lambda: session.stop()
    webview.start(private_mode=True)
    return 0


if __name__ == "__main__":
    sys.exit(run_app())

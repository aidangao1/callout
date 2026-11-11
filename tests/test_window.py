"""Mini mode must only touch the window on the window's own thread (the Windows freeze fix)."""

import queue
import sys
import threading
import time
import types

import pytest

pytest.importorskip("webview")

from callout.app.window import MINI_SIZE, Api  # noqa: E402


class FakeForm:
    """Stands in for the WinForms window: records which thread changed it."""

    def __init__(self, ui_queue):
        self.ui_queue = ui_queue
        self.calls = []
        self._top = False

    def BeginInvoke(self, action):  # noqa: N802 - WinForms name
        self.ui_queue.put(action)

    @property
    def TopMost(self):  # noqa: N802
        return self._top

    @TopMost.setter
    def TopMost(self, value):  # noqa: N802
        self.calls.append((f"TopMost={value}", threading.current_thread().name))
        self._top = value

    def resize(self, w, h, fix_point):
        self.calls.append((f"resize {w}x{h}", threading.current_thread().name))

    def Activate(self):  # noqa: N802
        self.calls.append(("activate", threading.current_thread().name))


class FakeWindow:
    uid = "w1"
    width = 1500
    height = 900


@pytest.fixture
def winforms(monkeypatch):
    ui_queue: queue.Queue = queue.Queue()
    form = FakeForm(ui_queue)
    system = types.ModuleType("System")
    system.Action = lambda fn: fn
    backend = types.ModuleType("webview.platforms.winforms")
    backend.BrowserView = types.SimpleNamespace(instances={"w1": form})
    monkeypatch.setitem(sys.modules, "System", system)
    monkeypatch.setitem(sys.modules, "webview.platforms.winforms", backend)

    def ui_loop():
        while (action := ui_queue.get()) is not None:
            action()

    ui = threading.Thread(target=ui_loop, name="ui")
    ui.start()
    yield form
    ui_queue.put(None)
    ui.join()


def call_from_page(api, on):
    """Page calls arrive on a background thread, like pywebview's."""
    result = {}

    def go():
        t = time.monotonic()
        result["value"] = api.set_mini(on)
        result["seconds"] = time.monotonic() - t

    t = threading.Thread(target=go, name="page")
    t.start()
    t.join()
    return result


def test_mini_mode_changes_happen_on_the_window_thread(winforms):
    api = Api(session=None)
    api._window = FakeWindow()
    entered = call_from_page(api, True)
    time.sleep(0.1)
    left = call_from_page(api, False)
    time.sleep(0.1)

    assert entered["value"] and left["value"]
    assert entered["seconds"] < 0.05 and left["seconds"] < 0.05  # never waits on the window
    assert all(thread == "ui" for _, thread in winforms.calls)
    names = [what for what, _ in winforms.calls]
    assert names == [
        f"resize {MINI_SIZE[0]}x{MINI_SIZE[1]}",
        "TopMost=True",
        "activate",
        "TopMost=False",
        "resize 1500x900",
        "activate",
    ]


def test_other_platforms_use_the_library_off_the_calling_thread(monkeypatch):
    monkeypatch.setitem(sys.modules, "webview.platforms.winforms", None)  # not on Windows
    calls = []

    class Window(FakeWindow):
        def resize(self, w, h):
            calls.append(("resize", w, h))

        @property
        def on_top(self):
            return False

        @on_top.setter
        def on_top(self, value):
            calls.append(("on_top", value))

    api = Api(session=None)
    api._window = Window()
    assert api.set_mini(True)
    time.sleep(0.2)
    assert calls == [("resize", *MINI_SIZE), ("on_top", True)]

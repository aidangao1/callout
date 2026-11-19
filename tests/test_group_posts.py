"""Fills and warnings posted to Discord and Telegram: what gets posted, and that posting never blocks trading."""

import threading
import time

import pytest

from callout.app.session import Session
from callout.config import ConfigError, load_config, validate
from callout.remote import discord_post, telegram_post
from callout.remote.posting import QueuedPoster, Reply, send_once

HOOK = "https://discord.com/api/webhooks/1234567890/abcDEF_-123"
TOKEN = "1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
GROUP = "-1001234567890"


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


class FakeService:
    """Stands in for Discord's and Telegram's HTTP endpoints: records what was posted where."""

    def __init__(self, replies=None):
        self.sent: list[tuple[str, dict]] = []
        self.replies = list(replies or [])
        self.lock = threading.Lock()

    def __call__(self, url, payload):
        with self.lock:
            reply = self.replies.pop(0) if self.replies else (200, {"ok": True})
            if isinstance(reply, Exception):
                raise reply
            if reply[0] < 300:
                self.sent.append((url, payload))
        return reply

    def texts(self, service):
        key = "content" if service == "discord" else "text"
        return [p[key] for url, p in self.sent if service in url]


# ---- settings ----------------------------------------------------------------------------------


def test_links_and_tokens_are_checked():
    cfg = load_config(None)
    cfg.discord.webhook_url = HOOK
    cfg.telegram.bot_token, cfg.telegram.chat_id = TOKEN, GROUP
    validate(cfg)
    cfg.discord.webhook_url = "https://example.com/api/webhooks/1/abc"
    with pytest.raises(ConfigError, match="isn't a Discord webhook"):
        validate(cfg)
    cfg.discord.webhook_url = ""
    cfg.telegram.bot_token = "not-a-token"
    with pytest.raises(ConfigError, match="isn't a Telegram bot token"):
        validate(cfg)


# ---- delivery ----------------------------------------------------------------------------------


def test_queue_waits_out_rate_limits_and_reports_errors():
    replies = [Reply(False, "slow down", 0.05), Reply(True), Reply(False, "gone")]
    sent, errors = [], []

    def send(text):
        r = replies.pop(0)
        if r.ok:
            sent.append(text)
        return r

    p = QueuedPoster("Test", send, errors.append)
    p.post("one")
    p.post("two")
    assert wait_for(lambda: errors)
    p.close()
    assert sent == ["one"] and errors == ["gone"]


def test_queue_never_blocks_when_the_service_hangs():
    gate = threading.Event()

    def slow(text):
        gate.wait(5)
        return Reply(True)

    p = QueuedPoster("Slow", slow, max_queue=2)
    t = time.monotonic()
    for i in range(10):
        p.post(f"message {i}")
    assert time.monotonic() - t < 0.1
    gate.set()
    p.close()


def test_discord_messages_and_errors():
    fake = FakeService([(204, {}), (429, {"retry_after": 2}), (404, {})])
    send = discord_post.sender(HOOK, post=fake)
    assert send("hi") == Reply(True)
    assert fake.sent[0][1] == {"content": "hi", "allowed_mentions": {"parse": []}}  # never pings anyone
    assert send("hi").retry_after == 2
    assert "doesn't exist" in send("hi").error


def test_telegram_messages_and_errors():
    fake = FakeService([(200, {"ok": True}), (429, {"parameters": {"retry_after": 3}}), (401, {}), (403, {})])
    send = telegram_post.sender(TOKEN, GROUP, post=fake)
    assert send("hi") == Reply(True)
    url, payload = fake.sent[0]
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage" and payload["chat_id"] == GROUP
    assert send("hi").retry_after == 3
    assert "doesn't recognize this bot token" in send("hi").error
    assert "isn't in that group" in send("hi").error


def test_finding_the_telegram_group_the_bot_was_added_to():
    updates = {
        "ok": True,
        "result": [
            {"my_chat_member": {"chat": {"id": -1001111, "title": "Old group", "type": "supergroup"}}},
            {"message": {"chat": {"id": 42, "first_name": "Him", "type": "private"}}},  # a DM, not a group
            {"my_chat_member": {"chat": {"id": -1002222, "title": "Trading crew", "type": "supergroup"}}},
        ],
    }
    r = telegram_post.find_groups(TOKEN, post=lambda url, payload: (200, updates))
    assert r == {
        "ok": True,
        "groups": [{"id": "-1002222", "title": "Trading crew"}, {"id": "-1001111", "title": "Old group"}],
    }
    r = telegram_post.find_groups(TOKEN, post=lambda url, payload: (401, {"ok": False}))
    assert not r["ok"] and "bot token" in r["error"]


def test_test_buttons_report_the_outcome():
    assert send_once("Discord", lambda t: Reply(True), "hi") == {"ok": True}
    assert send_once("Discord", lambda t: Reply(False, "nope"), "hi") == {"ok": False, "error": "nope"}

    def offline(text):
        raise OSError("offline")

    assert send_once("Telegram", offline, "hi") == {"ok": False, "error": "Couldn't reach Telegram: offline"}


# ---- from the app ------------------------------------------------------------------------------


@pytest.fixture
def posted(tmp_path, monkeypatch):
    fake = FakeService()
    monkeypatch.setattr(discord_post, "post_json", fake)
    monkeypatch.setattr(telegram_post, "post_json", fake)
    cfg = load_config(None)
    cfg.log_dir = str(tmp_path / "logs")
    cfg.safety.check_market_hours = False
    cfg.safety.min_seconds_between_orders = 0
    cfg.discord.webhook_url = HOOK
    cfg.telegram.bot_token, cfg.telegram.chat_id = TOKEN, GROUP
    s = Session(cfg, tmp_path / "config.toml", use_sim=True, audio=False, tts=False)
    s.start()
    assert wait_for(lambda: s.snapshot().get("connected"))
    yield s, fake
    s.stop()


def test_fills_and_flatten_go_to_every_group(posted):
    s, fake = posted
    s.command("buy es")
    assert wait_for(lambda: s.snapshot().get("pending"))
    s.command("confirm")
    assert wait_for(lambda: fake.texts("discord") and fake.texts("telegram"))
    assert fake.texts("discord")[0].startswith("SIM · Filled. Bought 1 ES at ")
    assert fake.texts("telegram")[0].startswith("SIM · Filled. Bought 1 ES at ")
    assert "E S" not in fake.texts("telegram")[0]  # the spoken spelling is turned back into the symbol
    s.command("flatten")
    assert wait_for(lambda: len(fake.texts("telegram")) == 2)
    assert fake.texts("telegram")[1].startswith("SIM · Flat. Sold 1 ES")


def test_readbacks_rejections_and_empty_flattens_are_not_posted(posted):
    s, fake = posted
    s.command("buy es")
    assert wait_for(lambda: s.snapshot().get("pending"))
    s.command("cancel")
    s.command("blah")
    s.command("flatten")  # already flat: nothing to report
    time.sleep(0.6)
    assert fake.sent == []


def test_live_is_bold_on_discord(posted):
    s, _ = posted
    assert discord_post.format_post("LIVE", "Filled.") == "**LIVE** · Filled."
    assert telegram_post.format_post("LIVE", "Filled.") == "LIVE · Filled."


def test_changing_groups_in_settings(posted):
    s, fake = posted
    r = s.apply({"discord_webhook": "not a link"})
    assert not r["ok"] and "isn't a Discord webhook" in r["error"]
    assert s.cfg.discord.webhook_url == HOOK  # unchanged
    assert s.apply({"discord_webhook": ""})["ok"]
    assert [p.name for p, _ in s.posters] == ["Telegram"]
    view = s.settings()
    assert view["telegram_token"] == TOKEN and view["telegram_chat"] == GROUP
    assert s.apply({"telegram_token": ""})["ok"] and s.posters == [] and s.cfg.telegram.chat_id == ""
    assert "token" in s.test_telegram()["error"]

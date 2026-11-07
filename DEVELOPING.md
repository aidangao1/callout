# Callout: developer notes

The [README](README.md) covers installing and using Callout on Windows. This file covers how it works, terminal setup on any OS, and how to extend it.

Voice-command order entry for Interactive Brokers futures. Hold a key (or the on-screen Talk button), say **"buy E S"**, check the readback, say **"confirm"**, and a market order goes to TWS or IB Gateway. Say **"flatten"** to close everything.

```
hold F9 ─► mic ─► Vosk (offline, locked to known phrases) ─► strict parser ─► risk checks
        ─► readback (spoken + on screen) ─► "confirm" ─► IBKR market order ─► fill readback ─► JSONL log
```

> Not financial advice. This software places real orders when pointed at a live account. Test on paper first and use at your own risk.

## Voice commands

| Say | Does |
|---|---|
| `buy E S` / `buy E mini` | Buy 1 ES contract (quantity is a setting) |
| `sell E S` / `sell E mini` | Sell 1 ES contract |
| `buy micro E S` / `sell micro E S` | Same for MES, when it's turned on |
| `confirm` | Send the order that was just read back |
| `cancel` / `no` | Drop it |
| `flatten` / `flatten all` / `close all` | Cancel working orders and close every position in the configured instruments, in any expiry. No confirmation by default |
| `flatten E S` | Same, ES only |

In futures there is only buy and sell. If you're flat, "sell" opens a short. If you're long 1, "sell" closes it. The readback always tells you which, e.g. *"Sell 1 E S. Long 1 to flat. Say confirm."*

The app's CONFIRM, Cancel and FLATTEN ALL buttons (and Enter / Esc) send these same commands, so they go through the same checks.

## Setup

**You need:** Python 3.11+, an IBKR account with futures trading permissions, TWS or IB Gateway, and a microphone. On Windows, `install.bat` does steps 1 and 3 for you.

### 1. Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -e .
```

- **Windows:** nothing extra. The app window uses Edge WebView2, which is built into Windows 11 and most Windows 10 installs.
- **macOS:** give your terminal app Microphone, Accessibility and Input Monitoring permission (System Settings › Privacy & Security). The global hotkey needs the last two.
- **Linux:** `sudo apt install libportaudio2 espeak-ng`, plus a GTK or Qt backend for pywebview to use the app window. Global hotkeys need X11; on Wayland use the on-screen Talk button.

### 2. Turn on the API in TWS (or IB Gateway)

Log in to your **paper** account, then go to *Global Configuration › API › Settings*:

- check **Enable ActiveX and Socket Clients**
- uncheck **Read-Only API**
- socket port **7497** (TWS paper). IB Gateway paper uses **4002**.
- keep **Allow connections from localhost only** checked

Then follow **Protect your account in TWS** in the README (size limit, daily restart time).

### 3. Run

```bash
python -m callout app           # the desktop app (what start.bat runs); first run opens setup
```

Console tools, useful for troubleshooting:

```bash
python -m callout check         # connect, show the contract it will trade and your positions
python -m callout devices       # list microphones
python -m callout mic-scan      # record a moment from every mic and show which one hears you
python -m callout mic-test      # speak; shows what it heard and what it WOULD do. Never trades.
python -m callout tts-test      # play a spoken reply
python -m callout run           # trade in the console, without the app window
```

The speech model (~40 MB) downloads automatically the first time.

### Try it without TWS

```bash
python -m callout app --sim                                  # the app with simulated fills
python -m callout run --sim --text --ignore-market-hours     # console: type commands instead of speaking
```

The market-hours check still applies in the app with `--sim`; turn off "Block orders when the market is closed" in Settings › Trading to test on a weekend.

## Safety

- **Paper-account guard.** IBKR paper accounts start with `D`. In paper mode, Callout refuses to trade on any other account. The top bar's PAPER / LIVE tag comes from the account IBKR reports.
- **Live needs a deliberate step.** In the app: choose Live in Settings › Connection and type LIVE, and type LIVE again every time the app starts. In the console: `trading_mode = "live"`, a live port, **and** the `--live` flag.
- **Push-to-talk only.** Audio is kept only while the key or the Talk button is held.
- **Grammar-locked recognition.** The recognizer can only output known phrases, plus decoy words that are heard and rejected (so "flat" isn't rounded to "flatten"). Unknown words, extra words, or confidence below `min_confidence` are rejected with "Didn't catch that. Nothing sent."
- **Readback and confirm** (on by default). The readback includes the position change. If your position changes between the readback and "confirm", the order is not sent. Anything unclear after a readback (a mumble, a stray tap of the key) cancels the pending order.
- **Hold to flatten.** The FLATTEN ALL button only fires after a one-second hold. Saying "flatten" works instantly.
- **Limits.** `max_position`, a 1-second cooldown between orders, and `max_orders_per_minute`. Orders that reduce exposure are always allowed.
- **Market hours.** Orders are blocked outside CME Globex hours (Sun 6pm to Fri 5pm ET, plus the 5 to 6pm daily halt). Exchange holidays aren't modelled; IBKR rejects those orders itself.
- **Fill verification.** After every order, filled or not, Callout asks IBKR for the real position and warns you if it isn't what it expected (for example, a fill that arrived after a cancel).
- **Timeouts.** A market order not filled within `order_timeout_s` is cancelled. If the cancel isn't confirmed, you're told the order may still be working. Every request to TWS has a 10-second timeout, so a frozen TWS can't hang the app.
- **Disconnects.** If TWS drops, trading is blocked until it reconnects and positions resync. Callout reconnects automatically. An order whose state couldn't be confirmed is read back as "state unknown, check your platform".
- **Front month and roll.** Callout trades the front quarterly contract and rolls `roll_days_before_expiry` (default 8) days before expiry, but never while you hold the current contract. If you hold an older expiry, buy and sell are blocked until you flatten, so limits and readbacks always see your whole position.
- **Flatten and working orders.** Flatten cancels working orders first, so a resting stop can't fire after you're flat. The IBKR API can only cancel orders this app placed. If orders entered by hand in TWS remain, flatten tells you. Set `flatten_cancels_all_orders = true` to use IBKR's global cancel instead (it cancels every open order in the account, stocks included).

## Logs

Every utterance, decision, order and fill is written to `logs/callout-YYYY-MM-DD.jsonl` with millisecond timestamps and latency, including key-release-to-fill time. In the app, Settings › Logs (or "Log folder" under Activity) opens the folder.

```json
{"ts": "2026-11-09T10:02:13.481-05:00", "event": "order_result", "contract": "ESZ6", "action": "BUY",
 "status": "Filled", "filled": 1, "avg_price": 6001.25, "send_to_done_ms": 212.4, "release_to_done_ms": 1430.9}
```

Event types: `startup`, `heard` (with `rejected` reason if any), `awaiting_confirm`, `confirmed`, `cancelled`, `blocked`, `order_sent`, `order_result`, `position_mismatch`, `orders_cancelled`, `flatten_incomplete`, `contract_roll`, `contract_roll_deferred`, `broker_error`, `disconnected`, `connect_failed`, `reconnect_failed`, `error`, `shutdown`.

## Going live

1. Run on paper until the logs look boring.
2. Turn on MES (Settings › Trading). It's a tenth the size of ES. Consider turning ES off at first.
3. In the app: Settings › Connection › Live (real money), type LIVE, and click Use this connection. In the console: set `trading_mode = "live"` and the live port (TWS 7496 / Gateway 4001), then `python -m callout run --live`.

## Config

Settings live in `config.toml`. The app's Settings screen writes it; you can also edit it by hand while Callout is closed. `config.example.toml` has every option with comments. Ones you might change by hand:

- `push_to_talk`: the talk key. Pick one your trading platform doesn't use, since the key press still reaches the focused app. Empty means on-screen button only.
- `input_device`: which microphone. A number or part of a name from `python -m callout devices`; empty means the Windows default.
- `require_confirmation = false`: one-step orders. Faster, but a misheard word becomes a trade.
- `quantity`, `max_position`: per instrument.
- `spoken`: the phrases for each instrument. Phrases using words the speech model doesn't know are dropped at startup.
- `decoys`: extra words to hear and reject.
- `voice_rate`, `voice_volume`: spoken reply speed (-10 to 10) and volume (0 to 100).

## Mic troubleshooting

The app's Settings › Microphone and voice shows a live level meter and has a Test a command button. In the console, `mic-test` prints the length and peak level of each recording, and `mic-scan` tests every mic at once.

- **Level 0% / "mic is silent"**: the app is getting silence. Check Windows *Settings › Privacy & security › Microphone*: both "Microphone access" and "Let desktop apps access your microphone" must be on. If they are, it's probably the wrong mic.
- **"no audio is arriving"**: the mic stream isn't delivering anything. Pick a different entry for the same mic in `devices` (they're listed once per Windows audio system: MME, DirectSound, WASAPI).
- **Quiet (under ~30%)**: raise the input level in Windows sound settings or move closer. Recognition gets unreliable when the level is low.
- **Loud enough but still not recognised**: look at what it heard. The phrases, `decoys` or `min_confidence` may need tuning.

## The app window

`python -m callout app` (what `start.bat` runs; add `--sim` to use the simulator) opens a desktop window built with pywebview, which uses Edge WebView2 on Windows.

- `callout/session.py` runs the engine, broker and voice on a background asyncio loop and keeps a snapshot of everything the screen shows, refreshed several times a second. On-screen buttons send the same `confirm`, `cancel` and `flatten` commands as your voice, so they go through the same risk checks.
- `callout/gui.py` creates the window and exposes a small API to the page (`window.pywebview.api`).
- `callout/web/` is the page: `index.html`, `app.css`, `app.js`, and **`theme.css`, where every color and the font are defined.** Change the look there. Geist Mono is bundled (SIL Open Font License, `web/fonts/GeistMono-OFL.txt`). The page loads nothing from the internet.
- Settings changed in the app are written back to `config.toml` (`callout/settings_io.py`).
- Live trading has to be unlocked by typing LIVE each time the app starts, or when switching to live in Settings.

## Project layout

```
callout/
  cli.py            commands: app, init, check, devices, mic-scan, mic-test, tts-test, run
  gui.py            the desktop window
  session.py        runs everything behind the window
  settings_io.py    saves settings back to config.toml
  web/              the window's page (theme.css = colors and font)
  engine.py         intent -> risk -> confirm -> order -> readback
  intents.py        phrase grammar, decoys and strict parser
  risk.py           limits, cooldown, rate limit, market hours and clock
  contracts.py      expiries, front month, roll
  stt.py            Vosk speech-to-text, grammar-locked
  audio.py          mic capture, level meter, push-to-talk
  tts.py            spoken readback
  journal.py        JSONL log
  brokers/
    base.py         Broker interface
    ibkr.py         Interactive Brokers (ib_async)
    sim.py          simulated fills
tests/              python -m pytest
*.bat               Windows double-click launchers (install, start, start-console, mic-test, check-connection)
```

Run the tests with `pip install -e .[dev]` then `python -m pytest`.

## Extending

- **Another broker:** subclass `brokers.base.Broker` (connect, front_month, position, positions, market_order, cancel_open_orders, open_orders; optionally avg_price and working_count for the screen) and add it to `brokers/__init__.py`. The engine and the app don't change.
- **More commands** (e.g. "buy 2 E S", limit orders, stocks by dollar amount): add phrases in `intents.py`. For free-form speech, a larger speech model or an LLM can replace the parser, as long as it outputs the same `Intent` objects and goes through the same risk and confirm path.

## Known limitations

- Not yet tested with orders filling while the market is open.
- The speech model is small and fast; it sometimes needs a command said twice.
- Market orders only. No brackets or stops yet. ES and MES only.
- One account per session.
- Orders entered by hand in TWS can only be cancelled by flatten with the global-cancel setting (see Safety).
- No daily loss limit yet.

## License

Copyright 2026 Aidan Gao. [Apache 2.0](LICENSE); see [NOTICE](NOTICE). Anyone redistributing Callout must keep the NOTICE file.

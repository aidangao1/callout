# Callout: developer notes

The [README](README.md) covers installing and using Callout on Windows. This file covers how it works, terminal setup on any OS, and how to extend it.

Voice-command order entry for Interactive Brokers futures. Hold a key, say **"buy ES"**, hear the readback, say **"confirm"**, and a market order goes to TWS or IB Gateway. Say **"flatten"** to close everything.

```
hold F9 ─► mic ─► Vosk (offline, locked to known phrases) ─► strict parser ─► risk checks
        ─► spoken readback + "confirm" ─► IBKR market order ─► "Filled at 6001.25, you're long 1" ─► JSONL log
```

> Not financial advice. This software places real orders when pointed at a live account. Test on paper first and use at your own risk.

## Voice commands

| Say | Does |
|---|---|
| `buy E S` / `buy E mini` | Buy 1 ES contract (quantity is set in config) |
| `sell E S` / `sell E mini` | Sell 1 ES contract |
| `confirm` | Send the order that was just read back |
| `cancel` / `no` | Drop it |
| `flatten` / `flatten all` / `close all` | Cancel working orders and close every position in the configured instruments, in any expiry. No confirmation by default |
| `flatten E S` | Same, ES only |

In futures there is only buy and sell. If you're flat, "sell" opens a short. If you're long 1, "sell" closes it. The readback always tells you which, e.g. *"Sell 1 E S. Long 1 to flat. Say confirm."*

## Setup

**You need:** Python 3.11+, an IBKR account with futures trading permissions, TWS or IB Gateway, and a microphone.

### 1. Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -e .
```

- **macOS:** give your terminal app Microphone, Accessibility and Input Monitoring permission (System Settings › Privacy & Security). The global hotkey needs the last two.
- **Linux:** `sudo apt install libportaudio2 espeak-ng`. Global hotkeys need X11; on Wayland set `push_to_talk = "enter"`.
- **Windows:** nothing extra.

### 2. Turn on the API in TWS (or IB Gateway)

Log in to your **paper** account, then go to *Global Configuration › API › Settings*:

- check **Enable ActiveX and Socket Clients**
- uncheck **Read-Only API**
- socket port **7497** (TWS paper). IB Gateway paper uses **4002**.
- make sure `127.0.0.1` is allowed (Trusted IPs)

### 3. Configure and test

```bash
python -m callout init        # writes config.toml
python -m callout check       # connects, shows the contract it will trade and your positions
python -m callout mic-test    # speak; shows what it heard and what it WOULD do. Never trades.
python -m callout run         # trade
```

The speech model (~40 MB) downloads automatically the first time.

### Try it without TWS

```bash
python -m callout run --sim --text --ignore-market-hours
```

`--sim` fakes fills, `--text` lets you type commands instead of speaking, and `--ignore-market-hours` lets you test on a weekend. Drop `--text` to test with your voice.

## Safety

- **Paper-account guard.** IBKR paper accounts start with `D`. In paper mode, Callout refuses to trade on any other account. Live mode needs `trading_mode = "live"`, a live port, **and** the `--live` flag.
- **Push-to-talk only.** Audio is kept only while the key is held, so a TV or a friend can't place an order.
- **Grammar-locked recognition.** The recognizer can only output known phrases. Unknown words, extra words, or confidence below `min_confidence` are rejected with "Didn't catch that. Nothing sent."
- **Readback and confirm** (on by default). The readback includes the position change. If your position changes between the readback and "confirm" (say, a manual fill in TWS), the order is not sent. Anything unclear after a readback (a mumble, a stray tap of the key) cancels the pending order.
- **Limits.** `max_position`, a 1-second cooldown between orders, and `max_orders_per_minute`. Orders that reduce exposure are always allowed.
- **Market hours.** Orders are blocked outside CME Globex hours (Sun 6pm to Fri 5pm ET, plus the 5 to 6pm daily halt). Exchange holidays aren't modelled; IBKR rejects those orders itself.
- **Fill verification.** After every order, filled or not, Callout asks IBKR for the real position and warns you if it isn't what it expected (for example, a fill that arrived after a cancel).
- **Timeouts.** A market order not filled within `order_timeout_s` is cancelled. If the cancel isn't confirmed, you're told the order may still be working. Every request to TWS has a 10-second timeout, so a frozen TWS can't hang the app.
- **Disconnects.** If TWS drops, trading is blocked until it reconnects and positions resync. Callout reconnects automatically. An order whose state couldn't be confirmed is read back as "state unknown, check your platform".
- **Front month and roll.** Callout trades the front quarterly contract and rolls `roll_days_before_expiry` (default 8) days before expiry, but never while you hold the current contract. If you hold an older expiry, buy and sell are blocked until you flatten, so limits and readbacks always see your whole position.
- **Flatten and working orders.** Flatten cancels working orders first, so a resting stop can't fire after you're flat. The IBKR API can only cancel orders this app placed. If orders entered by hand in TWS remain, flatten tells you. Set `flatten_cancels_all_orders = true` to use IBKR's global cancel instead (it cancels every open order in the account, stocks included).

## Logs

Every utterance, decision, order and fill is written to `logs/callout-YYYY-MM-DD.jsonl` with millisecond timestamps and latency, including key-release-to-fill time:

```json
{"ts": "2026-11-09T10:02:13.481-05:00", "event": "order_result", "contract": "ESZ6", "action": "BUY",
 "status": "Filled", "filled": 1, "avg_price": 6001.25, "send_to_done_ms": 212.4, "release_to_done_ms": 1430.9}
```

Event types: `startup`, `heard` (with `rejected` reason if any), `awaiting_confirm`, `confirmed`, `cancelled`, `blocked`, `order_sent`, `order_result`, `position_mismatch`, `orders_cancelled`, `flatten_incomplete`, `contract_roll`, `contract_roll_deferred`, `broker_error`, `disconnected`, `reconnect_failed`, `error`, `shutdown`.

## Going live

1. Run on paper until the logs look boring.
2. Enable MES in `config.toml` (`[instruments.MES] enabled = true`, say "buy micro E S"). It's a tenth the size of ES. Consider disabling ES.
3. Set `trading_mode = "live"` and the live port (TWS 7496 / Gateway 4001).
4. `python -m callout run --live`

## Config

See `config.example.toml`. Everything is commented. Common changes:

- `push_to_talk`: pick a key your trading platform doesn't use, since the key press still reaches the focused app.
- `input_device`: which microphone to use. Run `python -m callout devices` to list them, then put the number or part of the name here.
- `require_confirmation = false`: one-step orders. Faster, but a misheard word becomes a trade.
- `quantity`, `max_position`: per instrument.
- `spoken`: the phrases for each instrument. Phrases using words the speech model doesn't know are dropped at startup with a note.

## Mic troubleshooting

`mic-test` prints the length and peak level of each recording under what it heard.

- **`level 0%` / "mic is silent"**: the app is getting silence. Check Windows *Settings › Privacy & security › Microphone*: both "Microphone access" and "Let desktop apps access your microphone" must be on. If they are, it's probably the wrong mic: run `python -m callout devices` and set `input_device`.
- **"no audio is arriving"**: the mic stream isn't delivering anything. Pick a different entry for the same mic in `devices` (they're listed once per Windows audio system: MME, DirectSound, WASAPI).
- **Quiet (under ~10%)**: raise the input level in Windows sound settings or move closer.
- **Loud enough but still not recognised**: look at what it heard. The phrases, `decoys` or `min_confidence` may need tuning.

## Project layout

```
callout/
  cli.py            commands: init, check, devices, mic-scan, mic-test, tts-test, run
  engine.py         intent -> risk -> confirm -> order -> readback
  intents.py        phrase grammar and strict parser
  risk.py           limits, cooldown, rate limit, market hours
  contracts.py      expiries, front month, roll
  stt.py            Vosk speech-to-text, grammar-locked
  audio.py          mic capture, push-to-talk
  tts.py            spoken readback
  journal.py        JSONL log
  brokers/
    base.py         Broker interface
    ibkr.py         Interactive Brokers (ib_async)
    sim.py          simulated fills
tests/              python -m pytest
*.bat               Windows double-click launchers (install, start, start-live, mic-test, check-connection)
```

Run the tests with `pip install -e .[dev]` then `python -m pytest`.

## Extending

- **Another broker:** subclass `brokers.base.Broker` (connect, front_month, position, positions, market_order, cancel_open_orders) and add it to `brokers/__init__.py`. The engine doesn't change.
- **More commands** (e.g. "buy 2 E S", limit orders, stocks by dollar amount): add phrases in `intents.py`. For free-form speech, a larger model or an LLM can replace the parser, as long as it outputs the same `Intent` objects and goes through the same risk and confirm path.

## Known limitations

- Market orders only. No brackets or stops yet.
- One account per session.
- Orders entered by hand in TWS can only be cancelled by flatten with the global-cancel setting (see Safety).
- No daily loss limit yet.

## License

[Apache 2.0](LICENSE).

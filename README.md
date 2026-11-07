# Callout

Trade ES futures with your voice. Hold a key, say **"buy E S"**, hear the order read back, say **"confirm"**, and it's sent to your Interactive Brokers account.

> **Warning:** Callout places real orders when connected to a real-money account. Always start with a **paper** (practice) account. Use at your own risk. This is not financial advice.

## What you need

- A **Windows** computer
- A **microphone**. A headset works best.
- An **Interactive Brokers** account with **futures trading** turned on. Every IBKR account comes with a free paper trading account for practice.
- About 15 minutes

---

## Setup (one time)

### Step 1: Install Python

1. Go to **python.org/downloads** and download the latest Python for Windows.
2. Run the installer. On the first screen, tick **"Add python.exe to PATH"**, then click **Install Now**.

### Step 2: Download Callout

1. Download Callout as a ZIP file. On GitHub, that's the green **Code** button, then **Download ZIP**.
2. Right-click the ZIP and choose **Extract All**. Put the folder somewhere easy to find, like `C:\callout`.

### Step 3: Install Callout

1. Open the `callout` folder and double-click **`install.bat`**.
2. A black window opens and installs everything. This takes a minute or two.
3. When it says **Done**, press any key to close it.

If Windows shows **"Windows protected your PC"**, click **More info**, then **Run anyway**. Windows shows this for any downloaded script.

### Step 4: Set up Trader Workstation (TWS)

TWS is Interactive Brokers' trading app. Callout sends orders through it, so it has to be open while you trade.

1. Download **Trader Workstation** from interactivebrokers.com and install it.
2. Open TWS. On the login screen, switch to **Paper**, then log in.
3. Click the **gear icon** at the top right of TWS. In some versions it's in the **File** or **Edit** menu, called **Global Configuration**.
4. In the list on the left, open **API**, then click **Settings**.
5. Tick **Enable ActiveX and Socket Clients**.
6. Untick **Read-Only API**.
7. Check that **Socket port** says **7497**.
8. Click **Apply**, then **OK**. Leave TWS open.

### Step 5: Check that everything works

Double-click these, in order:

1. **`check-connection.bat`**. It should say something like `Connected to ibkr. Account DU1234567 (paper).` If TWS pops up asking to accept a connection, click **Accept**.
2. **`mic-test.bat`**. Hold **F9**, say **"buy E S"**, and let go. It should print `would do: BUY ES`. This only tests your mic and never trades. The first time, it downloads a speech model, which takes a moment.

---

## Trading

1. Open TWS and log in. Use **Paper** until you're comfortable.
2. Double-click **`start.bat`**.
3. **Hold F9 while you speak**, and let go when you're done.

| Say | What happens |
|---|---|
| **buy E S** | Reads the order back to you. Say "confirm" to send it. |
| **sell E S** | Same, for selling. |
| **confirm** | Sends the order that was just read back. |
| **cancel** | Drops it. |
| **flatten** | Closes your ES position right away. It doesn't ask for confirmation. |

**Example:**

> **You:** "buy E S"
> **Callout:** "Buy 1 E S. Flat to long 1. Say confirm."
> **You:** "confirm"
> **Callout:** "Filled. Bought 1 E S at 6001.25. You're long 1."

**Good to know:**

- Futures only have buy and sell. If you're long and say "sell," you go flat. If you're flat and say "sell," you go short. The readback always tells you which.
- If Callout didn't understand you, it says **"Didn't catch that. Nothing sent."** Just say it again.
- If you don't say "confirm" within 10 seconds, the order is dropped.
- ES trades **Sunday 6pm to Friday 5pm Eastern**, with a break from 5 to 6pm every weekday. Outside those hours, Callout says the market is closed.
- To stop Callout, close its window.
- Every command and order is saved in the `logs` folder.

---

## Changing settings

Open **`config.toml`** in the callout folder with Notepad, change what you need, save, and restart `start.bat`.

| To... | Change this |
|---|---|
| Use a different talk key | `push_to_talk = "f9"` to another key, like `"f8"` |
| Use a different microphone | `input_device = ""` to the number `mic-test.bat` shows for your mic, like `"2"` |
| Skip saying "confirm" (riskier) | `require_confirmation = true` to `false` |
| Trade more than 1 contract at a time | `quantity = 1` under `[instruments.ES]` |
| Allow a bigger position | `max_position = 2` |
| Turn off the spoken replies | `tts = true` to `false` |
| Trade Micro E-mini (MES) | Under `[instruments.MES]`, set `enabled = true`, then say "buy micro E S" |

---

## Trading with real money

Only do this after you've used paper trading for a while.

1. In TWS, log in to your **live** account. Do the API settings from Step 4, but set the port to **7496**.
2. In `config.toml`, change `trading_mode = "paper"` to `"live"` and `port = 7497` to `7496`.
3. Double-click **`start-live.bat`** and type `LIVE` when it asks.

Consider starting with Micro E-mini (MES). It's a tenth the size of ES, so mistakes cost a tenth as much.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `install.bat` says Python isn't installed | Reinstall Python and tick **"Add python.exe to PATH"**. |
| "Couldn't reach TWS" | TWS isn't open and logged in, or Step 4 wasn't done. |
| "looks LIVE, refusing to trade" | You logged TWS into your real account. Log in with **Paper** selected. |
| "no ES futures" | Turn on futures trading in IBKR's Client Portal, under Settings › Trading Permissions. |
| Holding F9 does nothing | On a laptop, try **Fn + F9**, or pick another key in settings. If you started TWS with "Run as administrator", start it normally instead. |
| `mic-test` says "mic is silent" | In Windows Settings › Privacy & security › Microphone, turn on access for desktop apps. If that's already on, pick your mic in settings. |
| It often mishears you | Raise your mic volume in Windows Sound settings until `mic-test` shows a level around 30–50%. |
| No spoken replies | Make sure Windows is playing sound on the device you're listening to (Settings › System › Sound › Output). |
| "Order state unknown" or "Check your platform" | Look in TWS. Your positions and orders there are always the truth. |

---

## How Callout keeps you safe

- It won't trade a real-money account unless you deliberately set it up for live trading.
- It only listens while you hold the talk key.
- It only understands its exact commands. Everything else is ignored.
- It reads every order back and waits for "confirm."
- It limits how big your position can get, and how fast orders can be sent.
- After every order, it checks your real position with Interactive Brokers and warns you if anything doesn't match.

---

Mac or Linux, or want to know how it works inside? See [DEVELOPING.md](DEVELOPING.md).

**License:** [Apache 2.0](LICENSE). Provided as is, with no warranty: you are responsible for every order it places.

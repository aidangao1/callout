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
8. Leave **Allow connections from localhost only** ticked.
9. Click **Apply**, then **OK**. Leave TWS open.

Then set up the safety settings in the next section. They take two minutes.

### Protect your account in TWS

Turning on the API lets programs place orders through TWS, so lock it down:

1. **Only this computer.** In API › Settings, keep **Allow connections from localhost only** ticked and don't add other trusted IPs. With the API on, *any* program on this computer can place orders through TWS, not just Callout.
2. **A size limit in TWS itself.** In Global Configuration, open **Presets › Futures** and set the **Precautionary Settings** size limit, for example 2 contracts. TWS then stops oversized orders even if Callout ever had a bug.
3. **Daily restart outside trading hours.** TWS restarts or logs off once a day. In **Lock and Exit**, set that time outside your trading hours. Callout reconnects on its own afterwards, and TWS also needs a full login once a week.
4. **A manual way out.** If TWS or your computer stops working with a position open, Callout can't close it. Know how to flatten in TWS or the IBKR mobile app.

The same checklist is in the app under Settings › Connection.

### Step 5: Open Callout

Double-click **`start.bat`**. The Callout window opens, along with a small black window behind it. Keep that one open: closing it closes Callout.

The first time, Callout walks you through a short setup:
1. **Connect to TWS:** click **Test connection**. It should say `Connected · paper account DU…`. If TWS pops up asking to accept a connection, click **Accept**.
2. **Pick your microphone:** choose your mic and test a command. Nothing is traded.
3. **Check you can hear it:** play a sample of the spoken replies.
4. **Practice on paper:** place and close a practice order.

The first start also downloads a speech model (about 40 MB), which takes a moment.

---

## Trading

1. Open TWS and log in. Use **Paper** until you're comfortable.
2. Double-click **`start.bat`**.
3. **Hold F9 while you speak**, and let go when you're done. You can also press and hold the big **HOLD TO TALK** button.

**The screen:**
- **Top bar:** connection, and which account you're on. **PAPER** is an outlined tag. A real-money account shows a solid black **LIVE · REAL MONEY** tag.
- **Left, dark:** your position (FLAT, LONG 1, SHORT 2…), average price, and the **FLATTEN ALL** button. Press and *hold* it for a second; a single click does nothing, so you can't close a position by accident.
- **Middle:** what Callout heard, and the order waiting for you. **CONFIRM** (or the Enter key) sends it, **Cancel** (or Esc) drops it, the same as saying them. On a live account, a **LIVE ACCOUNT** label appears above every order.
- **Bottom:** everything that happened, newest first.
- **Mini mode** (top right) shrinks Callout to a small strip that stays on top of TWS.

The screen gets bigger when the window does, so it works well filling a second monitor.

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
- If you don't say "confirm" within 10 seconds, the order is dropped and Callout says "Order expired. Nothing sent."
- Flatten can only cancel orders Callout placed. If you placed an order by hand in TWS, flatten still closes your position, but a black banner stays at the top ("1 order still working in TWS") until you cancel that order in TWS. Otherwise it could open a new position.
- ES trades **Sunday 6pm to Friday 5pm Eastern**, with a break from 5 to 6pm every weekday. Outside those hours, Callout says the market is closed.
- To stop Callout, close its window.
- Every command and order is saved in the `logs` folder.

---

## Changing settings

Click **Settings** in the top right. Changes apply right away and are saved for next time.

- **Microphone and voice:** pick your mic (with a live level meter), test a command, change the talk key, turn spoken replies on or off, set their speed and volume, and add words Callout should ignore.
- **Trading:** turn ES and Micro E-mini (MES) on or off, contracts per order, the largest position allowed, the market-hours check, and the confirm settings.
- **Connection:** TWS or IB Gateway, paper or live. The port fills in by itself.
- **Logs:** opens the folder with the daily log files.
- **Run setup again:** repeats the first-run setup.

---

## Trading with real money

Only do this after you've used paper trading for a while.

1. In TWS, log in to your **live** account and turn on the same API settings as Step 4. The live port is **7496**.
2. In Callout, go to **Settings › Connection**, choose **Live (real money)**, type `LIVE` in the box that appears, and click **Use this connection**.
3. The top bar now shows a solid **LIVE · REAL MONEY** tag. Every time you open Callout after that, it asks you to type `LIVE` again before it connects.

To go back to practice, choose **Paper** in Settings › Connection.

Consider starting with Micro E-mini (MES). It's a tenth the size of ES, so mistakes cost a tenth as much.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `install.bat` says Python isn't installed | Reinstall Python and tick **"Add python.exe to PATH"**. |
| "Couldn't reach TWS" | TWS isn't open and logged in, or Step 4 wasn't done. |
| "looks LIVE, refusing to trade" | You logged TWS into your real account. Log in with **Paper** selected. |
| "no ES futures" | Turn on futures trading in IBKR's Client Portal, under Settings › Trading Permissions. |
| Holding F9 does nothing | On a laptop, try **Fn + F9**, or change the talk key in Settings. If you started TWS with "Run as administrator", start it normally instead. The on-screen **HOLD TO TALK** button always works. |
| The mic level bar doesn't move | In Windows Settings › Privacy & security › Microphone, turn on access for desktop apps. If that's already on, pick your mic in Settings › Microphone and voice. |
| It often mishears you | Raise your mic volume in Windows Sound settings until the level bar reaches the shaded band when you talk. |
| No spoken replies | Make sure Windows is playing sound on the device you're listening to (Settings › System › Sound › Output). |
| The Callout window doesn't open | Look at the black window for an error. If it mentions WebView2, install **Microsoft Edge WebView2 Runtime** from microsoft.com (it's built into Windows 11). `start-console.bat` runs Callout without the window, and `mic-test.bat` and `check-connection.bat` test the mic and the TWS connection on their own. |
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

**License:** Copyright 2026 Aidan Gao. Licensed under [Apache 2.0](LICENSE); see [NOTICE](NOTICE). Provided as is, with no warranty: you are responsible for every order it places.

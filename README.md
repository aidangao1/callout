# Callout

Trade ES futures with your voice. Hold a key, say **"buy E S"**, hear the order read back, say **"confirm"**, and it's sent to your Interactive Brokers account.

**New here? Start with the one-page [quick start](QUICKSTART.md).**

> **Warning:** Callout places real orders when connected to a real-money account. Always start with a **paper** (practice) account. Use at your own risk. This is not financial advice.

## What you need

- A **Windows** computer
- A **microphone**. A headset works best.
- An **Interactive Brokers** account with **futures trading** turned on, and its free **paper trading** (practice) account. Newer accounts get one automatically. If yours doesn't have one, request it in IBKR's Client Portal under Settings › **Paper Trading Account**; it's usually ready the next business day.
- No paper account yet? You can still try everything with fake trades: see [Try it with the simulator](#try-it-with-the-simulator).
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
2. Open TWS. On the login screen, switch to **Paper**, then log in with your **paper** username and password (they're different from your live ones).
3. Click the **gear icon** at the top right of TWS. In some versions it's in the **File** or **Edit** menu, called **Global Configuration**.
4. In the list on the left, open **API**, then click **Settings**.
5. Tick **Enable ActiveX and Socket Clients**.
6. Untick **Read-Only API**.
7. Check that **Socket port** says **7497**. That's the paper port. Your live login shows **7496**, which is normal: leave it as it is. Callout uses the right port when you choose Paper or Live.
8. Leave **Allow connections from localhost only** ticked.
9. Click **Apply**, then **OK**. Leave TWS open.

Paper and live are separate logins with separate settings. Even if you've turned on the API in your live login before, do these steps while logged in to **Paper**.

Then set up the safety settings in the next section. They take two minutes.

### Protect your account in TWS

Turning on the API lets programs place orders through TWS, so lock it down:

1. **Only this computer.** In API › Settings, keep **Allow connections from localhost only** ticked and don't add other trusted IPs. With the API on, *any* program on this computer can place orders through TWS, not just Callout.
2. **A size limit in TWS itself.** In Global Configuration, open **Presets › Futures** and set the **Precautionary Settings**: size limit 2 contracts, and a total value limit of about $1,000,000 so normal ES orders pass without a popup. Then in **API › Precautions**, keep **Bypass Order Precautions for API Orders** *unticked*. When it's ticked, TWS lets API orders past these limits without a warning, so the limit wouldn't protect you. With it unticked, an oversized order gets stuck on a TWS popup and Callout cancels it after 10 seconds.
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

### Try it with the simulator

No paper account yet? The simulator lets you try everything without TWS or an IBKR account. Your mic, the talk key, spoken replies, confirm and flatten all work for real; only the fills are fake.

1. Open the Callout folder in File Explorer.
2. Click the address bar at the top, type `cmd`, and press **Enter**. A black window opens in that folder.
3. Type `start.bat --sim` and press **Enter**. The top bar shows **SIMULATOR**.
4. If the market is closed, go to **Settings › Trading** and turn off **Block orders when the market is closed**. Turn it back on before you trade on paper or live: settings are shared.

When your paper account is ready, do Step 4 and double-click `start.bat` as usual. To see the first-run setup again, use **Settings › Run setup again**.

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
- **The first order each time TWS starts, TWS shows a popup asking you to allow orders from the API.** Accept it within 10 seconds, or Callout cancels that order. The popup can open behind the Callout window, so check TWS if your first order seems to hang. A good habit: place and close one practice order at the start of each session.
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
- **Connection:** TWS or IB Gateway, paper or live. The port fills in by itself (TWS: paper 7497, live 7496). Only type a different one if you changed it in TWS.
- **Phone:** trade hands-free from your phone, from anywhere (see below).
- **Group posts:** post your fills and warnings to a Telegram group or a Discord channel (see below).
- **Updates:** which version you have, and updating to a new one (see below).
- **Logs:** opens the folder with the daily log files.
- **Run setup again:** repeats the first-run setup.

---

## Trading from your phone

Your phone listens, and Callout on your computer does the trading, so you can trade from anywhere with earbuds in. Your computer has to stay on at home with TWS logged in.

**Setting it up (once):**
1. Set up the relay (one-time, about 10 minutes): follow `relay/README.md`, then paste its address into **Settings › Phone** and click **Save**.
2. Click **Pair a phone**, and scan the code with your phone's camera.

**Using it:** open the page the code opened (or the Callout app), tap **Start listening**, and talk:

> **You:** "Call out, buy E S"
> **Callout (in your earbuds):** "Buy 1 E S. Flat to long 1. Say confirm."
> **You:** "Confirm"

- Callout only acts on speech that starts with **"Call out"**, so the conversation around you is ignored. While an order waits, a plain "confirm" or "cancel" is enough.
- **Every order from the phone needs "confirm", flatten too,** because the phone's mic is always on.
- The page in the phone's browser needs the screen on. The Callout iPhone app keeps listening with the phone locked in your pocket.
- On the phone page, **Confirm** and **Flatten** need a one-second press, so a stray tap can't trade. Saying "confirm" works as usual.

**Keeping the phone page listening in your pocket (until the Callout app):** iPhones stop a web page's microphone when the screen locks. Apple's Guided Access keeps the page on screen and ignores touches, so nothing gets tapped in your pocket.

- **Once:** on the iPhone, go to **Settings › Accessibility › Guided Access**, turn it on, set a passcode, and set **Display Auto-Lock** to **Never**.
- **Each time:**
  1. Open the Callout page, tap **Start listening**, and allow the mic.
  2. Triple-click the side button, tap **Options**, turn off **Touch**, tap **Done**, then **Start**.
  3. Pocket the phone and talk.
- **To stop:** triple-click the side button, enter the passcode (or double-click and use Face ID), and tap **End**.

The screen stays on, so the battery drains faster. The Callout iPhone app will listen with the phone locked, without any of this.
- Commands and replies are encrypted between your phone and your computer. Pairing again (or clicking Unpair) cuts off the old phone.

---

## Fills in a group chat (Telegram or Discord)

Callout can post every fill, flatten result, order problem and lost connection to a Telegram group, a Discord channel, or both, so they reach your phone or watch while you're away. Each post says whether it was **PAPER** or **LIVE**. Readbacks and misheard words aren't posted.

**Telegram**
1. In Telegram, message **@BotFather**, send `/newbot`, and follow the steps. It gives you a token like `123456789:AAH…`.
2. Add your new bot to the group (Group info › Add members). Then, in the group, send **`/start@YourBotName`** with your bot's username. Bots only see messages addressed to them, so a plain message doesn't count.
3. In Callout, go to **Settings › Group posts**, paste the token, click **Save**, then **Find my group**, then **Send a test message**.

**Discord**
1. Open the channel's settings in Discord, then **Integrations › Webhooks › New Webhook**, and click **Copy Webhook URL**.
2. In Callout, go to **Settings › Group posts**, paste the link under Discord, click **Save**, then **Send a test message**.

Keep the token and the link to yourself: anyone who has them can post into your group. To stop posts, clear the box and click Save.

WeChat isn't supported: WeChat doesn't let programs post into ordinary groups, and the unofficial tools that do can get your WeChat account banned.

---

## Updating Callout

When a new version is out, a small square appears next to **Settings** in the top bar, and the Activity list says so. Click Settings, then **Update**: Callout closes, updates and reopens by itself in about a minute. Your settings and logs are kept. It only updates when you have no open position and no order waiting for confirm.

This works from version 0.10.0 on. To get 0.10.0 from an older version, do it by hand once: download the new ZIP, extract it to a new folder, copy `config.toml` from your old Callout folder into the new one, and double-click `install.bat` there.

---

## Trading with real money

Only do this after you've used paper trading for a while.

1. In TWS, log in to your **live** account and turn on the same API settings as Step 4. The live port is **7496**.
2. In Callout, go to **Settings › Connection**, choose **Live (real money)**, type `LIVE` in the box that appears, and click **Use this connection**.
3. The top bar now shows a solid **LIVE · REAL MONEY** tag. Every time you open Callout after that, it asks you to type `LIVE` again before it connects.

To go back to practice, choose **Paper** in Settings › Connection.

**Using the IBKR Mobile app while Callout trades live:** IBKR lets each username be logged in to only one trading app at a time. Logging in on your phone with the same username as TWS logs TWS out, which disconnects Callout. Add a second username for your account in IBKR's Client Portal and use that one on your phone. (Your paper account has its own username, so paper is not affected, but paper loses live prices while your real username is logged in somewhere else.)

Consider starting with Micro E-mini (MES). It's a tenth the size of ES, so mistakes cost a tenth as much.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `install.bat` says Python isn't installed | Reinstall Python and tick **"Add python.exe to PATH"**. |
| "Couldn't reach TWS" | TWS isn't open and logged in, or Step 4 wasn't done in the login you're using. If TWS is logged in to your live account, it listens on 7496, not the paper port 7497: log in with **Paper**. |
| "looks LIVE, refusing to trade" | You logged TWS into your real account. Log in with **Paper** selected. |
| "no ES futures" | Turn on futures trading in IBKR's Client Portal, under Settings › Trading Permissions. |
| Holding F9 does nothing | On a laptop, try **Fn + F9**, or change the talk key in Settings. If you started TWS with "Run as administrator", start it normally instead. The on-screen **HOLD TO TALK** button always works. |
| The mic level bar doesn't move | In Windows Settings › Privacy & security › Microphone, turn on access for desktop apps. If that's already on, pick your mic in Settings › Microphone and voice. |
| It often mishears you | Raise your mic volume in Windows Sound settings until the level bar reaches the shaded band when you talk. |
| No spoken replies | Make sure Windows is playing sound on the device you're listening to (Settings › System › Sound › Output). |
| The Callout window doesn't open | Look at the black window for an error. If it mentions WebView2, install **Microsoft Edge WebView2 Runtime** from microsoft.com (it's built into Windows 11). In the `troubleshooting` folder, `start-console.bat` runs Callout without the window, and `mic-test.bat` and `check-connection.bat` test the mic and the TWS connection on their own. |
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

## Suggestions

Have an idea, a command you wish Callout understood, or something that didn't work? Tell us in this short form: **[Send a suggestion](https://forms.gle/QCx536MZtLBhVo1m7)**

---

Mac or Linux, or want to know how it works inside? See [DEVELOPING.md](DEVELOPING.md).

**License:** Copyright 2026 Aidan Gao. Licensed under [Apache 2.0](LICENSE); see [NOTICE](NOTICE). Provided as is, with no warranty: you are responsible for every order it places.

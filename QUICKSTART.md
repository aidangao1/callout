# Callout quick start

Trade ES by voice from anywhere: say **"Call out, buy E S"**, hear it read back, say **"confirm"**.

## Once

1. **Install.** Download Callout, unzip it, and double-click **`install.bat`**.
2. **Set up.** Double-click **`start.bat`**. A short setup walks you through five steps: connecting to TWS, your microphone, the sound, a practice order, and your phone.
3. **Your phone.** On the last step, scan the code with your iPhone's camera, or with the Callout app if you have it. Tick **Open Callout when Windows starts**.

## Every day

**On the computer:**
- **TWS** is open and logged in.
- **Callout** is open. It opens itself when Windows starts if you ticked the box.

**On your phone:** open the Callout app (or the page the code opened) and tap **Start listening**. Then talk:

> "Call out, buy E S" → *"Buy 1 E S. Flat to long 1. Say confirm."* → "Confirm" → *"Filled. You're long 1."*

At the computer, hold **F9** and say "buy E S" instead. No "call out" is needed there.

### Until the Callout app arrives

The phone page only listens while it's on screen. To keep it going in your pocket, use Apple's Guided Access:

- **Once:** iPhone **Settings › Accessibility › Guided Access**: turn it on, set a passcode, set **Display Auto-Lock** to **Never**.
- **Each time:** on the Callout page tap **Start listening**. Triple-click the side button, tap **Options**, turn off **Touch**, tap **Done**, then **Start**. Pocket the phone.
- **To stop:** triple-click the side button, enter the passcode, and tap **End**.

## Optional: your fills in a group chat

Callout can post every fill to a Telegram group or a Discord channel. In Callout, go to **Settings › Group posts**:

- **Telegram:** message **@BotFather** in Telegram and send `/newbot` to get a token. Add the new bot to your group and send a message there. In Callout, paste the token, click **Save**, then **Find my group**.
- **Discord:** in the channel's settings, go to **Integrations › Webhooks › New Webhook › Copy Webhook URL**. Paste it in Callout and click **Save**.

Then click **Send a test message** to check it arrives.

## Good to know

- From the phone, **every order needs "confirm", flatten too.** Callout ignores anything that doesn't start with "Call out".
- On the phone page, **Confirm** and **Flatten** need a one-second press, so a stray tap can't trade.
- **"Flatten"** closes everything. At the computer it works instantly; from the phone it asks first.
- Your computer has to stay **on**, with TWS logged in, for the phone to work.

## If something's off

| What you see | What to do |
|---|---|
| Phone says "Callout isn't running on your PC" | Open Callout on the computer. |
| Callout says "Not connected" | Open TWS and log in. |
| Phone shows "Not paired" | In Callout: Settings › Phone › Pair a phone, and scan again. |
| It doesn't catch what you say | Say "Call out" clearly first, then the command. |
| Anything else | Check TWS: your positions and orders there are always the truth. |

The full guide is in [README.md](README.md).

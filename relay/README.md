# Callout relay

The relay is where your phone and the computer running Callout meet, so the phone can reach Callout from anywhere: the court, the car, another city. It runs on Cloudflare's free plan.

It can't read or change anything. Every message between the phone and Callout is encrypted with a key that only those two devices have. The key is in the pairing QR code, after the `#`, a part of a link that browsers and apps never send to any server. The relay passes sealed messages from one side to the other and keeps nothing.

One relay serves any number of phones and computers: each pairing gets its own random room.

## Set it up (once, about 10 minutes)

1. Make a free account at **dash.cloudflare.com/sign-up** (signing up with GitHub works).
2. If you don't have **Node.js**, `deploy.bat` installs it for you (or get the LTS version from nodejs.org).
3. Double-click **`deploy.bat`** in this `relay` folder. It installs what the relay needs, opens your browser to sign in to Cloudflare (click **Allow**), and publishes the relay. If Node.js is missing, it installs that first and asks you to run it again. The first publish may ask you to pick a `workers.dev` subdomain; any name works.

   The same three commands by hand: `npm install`, `npx wrangler login`, `npx wrangler deploy`.
4. The deploy prints your relay's address, like `https://callout-relay.yourname.workers.dev`. Open it in a browser: you should see **"Pair this phone first"**.
5. In Callout, go to **Settings › Phone**, paste that address under **Relay address**, and click **Save**.

If the relay's address ever changes, save the new one in Settings and pair the phone again.

## Updating it

When a new version of Callout changes the relay, double-click `deploy.bat` again. Phones and computers reconnect by themselves.

## Trying it locally

`npx wrangler dev` runs the relay on your computer at `http://127.0.0.1:8787`. The tests can use it too:

```
set CALLOUT_TEST_RELAY=http://127.0.0.1:8787
python -m pytest tests/test_phone_link.py
```

## Cost

Cloudflare's free plan includes Durable Objects (what the relay uses for rooms) with 100,000 requests a day. A phone and a computer trading for a few hours use a tiny fraction of that. Idle connections cost nothing.

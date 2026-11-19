/* Callout relay.

   The phone and the PC both connect here and meet in a "room" named by a random id
   from the pairing QR code. The relay passes binary frames from one to the other and
   tells each side when the other comes and goes. That's all it does.

   It can't read or change anything: frames are sealed end to end with a key that only
   the phone and the PC have (it's after the "#" in the pairing link, which is never
   sent to a server). It keeps nothing: no storage, no logs of content. */

import PAGE from "./page.html";

const ROLES = ["pc", "phone"];
const MAX_FRAME = 1 << 20; // 1 MiB: a few seconds of audio fits easily
const ROOM_ID = /^[A-Za-z0-9_-]{16,64}$/;

export class Room {
  constructor(ctx) {
    this.ctx = ctx;
  }

  socket(role) {
    return this.ctx.getWebSockets(role)[0];
  }

  async fetch(request) {
    const role = new URL(request.url).searchParams.get("role");
    if (!ROLES.includes(role)) return new Response("role must be pc or phone", { status: 400 });
    if (request.headers.get("Upgrade") !== "websocket") return new Response("Expected a websocket", { status: 426 });

    // One PC and one phone per room: a new connection replaces an old one of the same kind.
    for (const old of this.ctx.getWebSockets(role)) {
      try { old.close(1000, "replaced"); } catch {}
    }
    const [client, server] = Object.values(new WebSocketPair());
    this.ctx.acceptWebSocket(server, [role]); // hibernation: costs nothing while idle
    const other = this.socket(otherRole(role));
    note(server, Boolean(other));
    if (other) note(other, true);
    return new Response(null, { status: 101, webSocket: client });
  }

  webSocketMessage(ws, message) {
    if (typeof message === "string") return; // only sealed binary frames are passed on
    if (message.byteLength > MAX_FRAME) return;
    const role = this.ctx.getTags(ws)[0];
    const peer = this.socket(otherRole(role));
    if (peer) {
      try { peer.send(message); } catch {}
    }
  }

  webSocketClose(ws, code, reason) {
    try { ws.close(code === 1005 ? 1000 : code, reason); } catch {} // finish the goodbye so the other end isn't left waiting
    this.left(ws);
  }

  webSocketError(ws) {
    this.left(ws);
  }

  left(ws) {
    const role = this.ctx.getTags(ws)[0];
    const still = this.ctx.getWebSockets(role).filter((s) => s !== ws);
    if (still.length) return; // it was replaced, not gone
    const peer = this.socket(otherRole(role));
    if (peer) note(peer, false);
  }
}

function otherRole(role) {
  return role === "pc" ? "phone" : "pc";
}

function note(ws, present) {
  try { ws.send(JSON.stringify({ relay: "peer", present })); } catch {}
}

const pageHeaders = (host) => ({
  "content-type": "text/html; charset=utf-8",
  "cache-control": "no-store",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
  "content-security-policy":
    "default-src 'none'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'unsafe-inline' https://fonts.googleapis.com; " +
    "font-src https://fonts.gstatic.com; connect-src 'self' wss://" + host + "; img-src data:",
});

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const room = url.pathname.match(/^\/room\/([^/]+)$/);
    if (room) {
      if (!ROOM_ID.test(room[1])) return new Response("Bad room", { status: 400 });
      return env.ROOMS.get(env.ROOMS.idFromName(room[1])).fetch(request);
    }
    if (url.pathname === "/" || url.pathname === "/pair") {
      return new Response(PAGE, { headers: pageHeaders(url.host) });
    }
    return new Response("Not found", { status: 404 });
  },
};

const ALLOWED_ORIGIN = "https://yokkaichi-express.github.io";
const ACTION = "teikyo";
const HOSTS = new Set(["yokkaichi-express.github.io"]);
const MAX = { body: 4000, place: 200, name: 80, contact: 200 };
const RATE_MAX = 5;
const RATE_WINDOW_MS = 60 * 60 * 1000;
const STYLES = new Set(["real", "nickname", "anonymous"]);
const CONTACTS = new Set(["", "email", "phone"]);

function cors(origin) {
  const allow = origin === ALLOWED_ORIGIN ? origin : ALLOWED_ORIGIN;
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function json(data, status, origin) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors(origin) },
  });
}

function clip(s, n) {
  return String(s ?? "").trim().slice(0, n);
}

function validDate(s) {
  return /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(s + "T00:00:00Z"));
}

async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function readBody(request) {
  const type = request.headers.get("Content-Type") || "";
  if (type.includes("application/json")) {
    const data = await request.json();
    return data && typeof data === "object" ? data : {};
  }
  const form = await request.formData();
  const data = {};
  for (const [k, v] of form.entries()) {
    if (typeof v === "string") data[k] = v;
  }
  return data;
}

async function verifyTurnstile(token, ip, env) {
  if (typeof token !== "string" || token.length === 0 || token.length > 2048) return false;
  let result;
  try {
    const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      signal: AbortSignal.timeout(10_000),
      body: new URLSearchParams({
        secret: env.TURNSTILE_SECRET,
        response: token,
        remoteip: ip || "",
      }),
    });
    if (!r.ok) return false;
    result = await r.json();
  } catch {
    return false;
  }
  return !!(result && result.success && result.action === ACTION && HOSTS.has(result.hostname));
}

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get("Origin") || "";
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors(origin) });
    }
    const url = new URL(request.url);
    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
      return json({ ok: true, service: "yonek-teikyo" }, 200, origin);
    }
    if (request.method !== "POST" || url.pathname !== "/teikyo") {
      return json({ ok: false, error: "not_found" }, 404, origin);
    }
    if (origin && origin !== ALLOWED_ORIGIN) {
      return json({ ok: false, error: "forbidden" }, 403, origin);
    }

    let data;
    try {
      data = await readBody(request);
    } catch {
      return json({ ok: false, error: "validation" }, 400, origin);
    }

    // Honeypot: pretend success, do not store.
    if (clip(data.website || data.company || "", 200)) {
      return json({ ok: true }, 200, origin);
    }

    const ip = request.headers.get("CF-Connecting-IP") || "";
    const token = data["cf-turnstile-response"] || data.turnstile || "";
    if (!(await verifyTurnstile(token, ip, env))) {
      return json({ ok: false, error: "forbidden" }, 403, origin);
    }

    const body = clip(data.body, MAX.body);
    const place = clip(data.place, MAX.place);
    const dateUnknown = data.date_unknown === true || data.date_unknown === "1" || data.date_unknown === "on";
    const happenedOn = clip(data.happened_on || data.date || "", 10);
    const nameStyle = clip(data.name_style, 20);
    const nameText = clip(data.name_text, MAX.name);
    const contactType = clip(data.contact_type, 20);
    const contact = clip(data.contact, MAX.contact);
    const notify = data.notify_on_publish === true || data.notify_on_publish === "1" || data.notify_on_publish === "on";
    const consent = data.consent === true || data.consent === "1" || data.consent === "on";

    if (!body || body.length < 8 || !place) {
      return json({ ok: false, error: "validation" }, 400, origin);
    }
    if (!STYLES.has(nameStyle)) {
      return json({ ok: false, error: "validation" }, 400, origin);
    }
    if ((nameStyle === "real" || nameStyle === "nickname") && !nameText) {
      return json({ ok: false, error: "validation" }, 400, origin);
    }
    if (!CONTACTS.has(contactType)) {
      return json({ ok: false, error: "validation" }, 400, origin);
    }
    if (contactType && !contact) {
      return json({ ok: false, error: "validation" }, 400, origin);
    }
    if (contactType === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contact)) {
      return json({ ok: false, error: "validation" }, 400, origin);
    }
    if (contactType === "phone" && !/^[0-9+\-() ]{8,20}$/.test(contact)) {
      return json({ ok: false, error: "validation" }, 400, origin);
    }
    if (!consent) {
      return json({ ok: false, error: "validation" }, 400, origin);
    }
    if (dateUnknown) {
      // ok, date may be empty
    } else if (!validDate(happenedOn)) {
      return json({ ok: false, error: "validation" }, 400, origin);
    }

    const ipHash = await sha256((env.TURNSTILE_SECRET || "") + "|" + ip);
    const now = new Date();
    const nowIso = now.toISOString();
    const windowStart = new Date(now.getTime() - RATE_WINDOW_MS).toISOString();

    try {
      const counted = await env.DB.prepare(
        "SELECT COUNT(*) AS n FROM rate_limits WHERE ip_hash = ? AND created_at >= ?"
      ).bind(ipHash, windowStart).first();
      if ((counted && counted.n) >= RATE_MAX) {
        return json({ ok: false, error: "rate_limit" }, 429, origin);
      }

      await env.DB.prepare("INSERT INTO rate_limits (ip_hash, created_at) VALUES (?, ?)").bind(ipHash, nowIso).run();
      await env.DB.prepare("DELETE FROM rate_limits WHERE created_at < ?").bind(windowStart).run();

      const id = crypto.randomUUID();
      const storedName = nameStyle === "anonymous" ? "" : nameText;
      const storedNotify = notify && contact ? 1 : 0;
      await env.DB.prepare(
        `INSERT INTO tips (
          id, created_at, body, place, happened_on, date_unknown,
          name_style, name_text, contact_type, contact, notify_on_publish, consent, ip_hash, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'new')`
      ).bind(
        id,
        nowIso,
        body,
        place,
        dateUnknown ? null : happenedOn,
        dateUnknown ? 1 : 0,
        nameStyle,
        storedName,
        contactType || null,
        contact || null,
        storedNotify,
        ipHash
      ).run();

      if (env.NOTIFY_WEBHOOK_URL) {
        const payload = {
          source: "よんエク 情報提供",
          id,
          created_at: nowIso,
          body,
          place,
          happened_on: dateUnknown ? "日はわからない" : happenedOn,
          name_style: nameStyle,
          name_text: storedName,
          contact_type: contactType || "",
          contact: contact || "",
          notify_on_publish: !!storedNotify,
        };
        ctx.waitUntil(
          fetch(env.NOTIFY_WEBHOOK_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }).catch(() => {})
        );
      }

      return json({ ok: true }, 200, origin);
    } catch (err) {
      console.log(JSON.stringify({ event: "teikyo_error" }));
      return json({ ok: false, error: "server" }, 500, origin);
    }
  },
};

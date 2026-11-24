const ALLOWED_ORIGIN = "https://yokkaichi-express.github.io";
const ACTION = "teikyo";
const HOSTS = new Set(["yokkaichi-express.github.io"]);
const MAX = { body: 4000, place: 200, name: 80, contact: 200 };
const RATE_MAX = 5;
const RATE_WINDOW_MS = 60 * 60 * 1000;
const SESSION_MS = 30 * 60 * 1000;
const STYLES = new Set(["real", "nickname", "anonymous"]);
const CONTACTS = new Set(["", "email", "phone"]);
const PHOTO_MAX = 3;
const PHOTO_BYTES = 5 * 1024 * 1024;
const VIDEO_MAX = 1;
const VIDEO_BYTES = 200 * 1024 * 1024;
const PART_BYTES = 8 * 1024 * 1024;
const PHOTO_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"]);
const VIDEO_TYPES = new Set(["video/mp4", "video/quicktime", "video/webm"]);

function cors(origin) {
  const allow = origin === ALLOWED_ORIGIN ? origin : ALLOWED_ORIGIN;
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Yonek-Test",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
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

function timingEqual(a, b) {
  const aa = String(a || "");
  const bb = String(b || "");
  if (aa.length !== bb.length) return false;
  let d = 0;
  for (let i = 0; i < aa.length; i++) d |= aa.charCodeAt(i) ^ bb.charCodeAt(i);
  return d === 0;
}

function extFor(type, name) {
  const n = String(name || "").toLowerCase();
  if (n.endsWith(".jpg") || n.endsWith(".jpeg")) return "jpg";
  if (n.endsWith(".png")) return "png";
  if (n.endsWith(".webp")) return "webp";
  if (n.endsWith(".heic")) return "heic";
  if (n.endsWith(".heif")) return "heif";
  if (n.endsWith(".mp4")) return "mp4";
  if (n.endsWith(".mov")) return "mov";
  if (n.endsWith(".webm")) return "webm";
  const map = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
  };
  return map[type] || "bin";
}

function sniffKind(bytes, declared, filename) {
  if (!bytes || bytes.length < 12) return null;
  const hex = [...bytes.slice(0, 12)].map((b) => b.toString(16).padStart(2, "0")).join("");
  const ascii = String.fromCharCode(...bytes.slice(0, 16));
  const type = String(declared || "").toLowerCase();
  const name = String(filename || "").toLowerCase();
  if (hex.startsWith("ffd8ff")) return { kind: "photo", type: "image/jpeg" };
  if (hex.startsWith("89504e47")) return { kind: "photo", type: "image/png" };
  if (ascii.startsWith("RIFF") && ascii.slice(8, 12) === "WEBP") return { kind: "photo", type: "image/webp" };
  if (bytes[0] === 0x1a && bytes[1] === 0x45 && bytes[2] === 0xdf && bytes[3] === 0xa3) {
    return { kind: "video", type: "video/webm" };
  }
  if (ascii.slice(4, 8) === "ftyp") {
    const brand = ascii.slice(8, 12).replace(/\0/g, "").toLowerCase();
    const heic = ["heic", "heif", "mif1", "heix", "hevc", "heim", "heis", "msf1"];
    if (heic.includes(brand) || type.startsWith("image/hei") || name.endsWith(".heic") || name.endsWith(".heif")) {
      return { kind: "photo", type: type === "image/heif" ? "image/heif" : "image/heic" };
    }
    if (brand === "qt  " || type === "video/quicktime" || name.endsWith(".mov")) {
      return { kind: "video", type: "video/quicktime" };
    }
    return { kind: "video", type: "video/mp4" };
  }
  return null;
}

function validateFileMeta(list) {
  if (!Array.isArray(list)) return "validation";
  if (list.length > PHOTO_MAX + VIDEO_MAX) return "validation";
  let photos = 0;
  let videos = 0;
  for (const f of list) {
    const kind = f.kind === "video" || VIDEO_TYPES.has(f.type) ? "video" : "photo";
    const type = String(f.type || "");
    const size = Number(f.size);
    const name = clip(f.name || f.filename || "file", 180);
    if (!name || !Number.isFinite(size) || size <= 0) return "validation";
    if (kind === "photo") {
      photos++;
      if (photos > PHOTO_MAX) return "validation";
      if (size > PHOTO_BYTES) return "too_large";
      if (type && !PHOTO_TYPES.has(type) && !/\.(jpe?g|png|webp|heic|heif)$/i.test(name)) return "validation";
    } else {
      videos++;
      if (videos > VIDEO_MAX) return "validation";
      if (size > VIDEO_BYTES) return "too_large";
      if (type && !VIDEO_TYPES.has(type) && !/\.(mp4|mov|webm)$/i.test(name)) return "validation";
    }
  }
  return null;
}

async function readJson(request) {
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

function isTestAuth(request, env) {
  return !!(env.TEST_KEY && timingEqual(request.headers.get("X-Yonek-Test") || "", env.TEST_KEY));
}

function parseFields(data) {
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
  if (!body || body.length < 8 || !place) return { error: "validation" };
  if (!STYLES.has(nameStyle)) return { error: "validation" };
  if ((nameStyle === "real" || nameStyle === "nickname") && !nameText) return { error: "validation" };
  if (!CONTACTS.has(contactType)) return { error: "validation" };
  if (contactType && !contact) return { error: "validation" };
  if (contactType === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contact)) return { error: "validation" };
  if (contactType === "phone" && !/^[0-9+\-() ]{8,20}$/.test(contact)) return { error: "validation" };
  if (!consent) return { error: "validation" };
  if (!dateUnknown && !validDate(happenedOn)) return { error: "validation" };
  return {
    body,
    place,
    dateUnknown,
    happenedOn: dateUnknown ? null : happenedOn,
    nameStyle,
    nameText: nameStyle === "anonymous" ? "" : nameText,
    contactType: contactType || null,
    contact: contact || null,
    notify: notify && contact ? 1 : 0,
  };
}

async function rateLimit(env, ipHash, nowIso) {
  const windowStart = new Date(Date.parse(nowIso) - RATE_WINDOW_MS).toISOString();
  const counted = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM rate_limits WHERE ip_hash = ? AND created_at >= ?"
  ).bind(ipHash, windowStart).first();
  if ((counted && counted.n) >= RATE_MAX) return false;
  await env.DB.prepare("INSERT INTO rate_limits (ip_hash, created_at) VALUES (?, ?)").bind(ipHash, nowIso).run();
  await env.DB.prepare("DELETE FROM rate_limits WHERE created_at < ?").bind(windowStart).run();
  return true;
}

async function insertTip(env, fields, nowIso, ipHash, isTest, status) {
  const id = crypto.randomUUID();
  await env.DB.prepare(
    `INSERT INTO tips (
      id, created_at, body, place, happened_on, date_unknown,
      name_style, name_text, contact_type, contact, notify_on_publish, consent, ip_hash, status, is_test
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)`
  ).bind(
    id,
    nowIso,
    fields.body,
    fields.place,
    fields.happenedOn,
    fields.dateUnknown ? 1 : 0,
    fields.nameStyle,
    fields.nameText,
    fields.contactType,
    fields.contact,
    fields.notify,
    ipHash,
    status,
    isTest ? 1 : 0
  ).run();
  return id;
}

async function notify(env, ctx, id, nowIso, fields) {
  if (!env.NOTIFY_WEBHOOK_URL) return;
  const payload = {
    source: "よんエク 情報提供",
    id,
    created_at: nowIso,
    body: fields.body,
    place: fields.place,
    happened_on: fields.dateUnknown ? "日はわからない" : fields.happenedOn,
    name_style: fields.nameStyle,
    name_text: fields.nameText,
    contact_type: fields.contactType || "",
    contact: fields.contact || "",
    notify_on_publish: !!fields.notify,
  };
  ctx.waitUntil(
    fetch(env.NOTIFY_WEBHOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch(() => {})
  );
}

async function loadSession(env, sessionId) {
  if (!sessionId) return null;
  const row = await env.DB.prepare("SELECT * FROM upload_sessions WHERE id = ?").bind(sessionId).first();
  if (!row) return null;
  if (row.expires_at < new Date().toISOString()) return null;
  row.files = JSON.parse(row.files || "[]");
  return row;
}

async function saveSession(env, session) {
  await env.DB.prepare("UPDATE upload_sessions SET files = ? WHERE id = ?")
    .bind(JSON.stringify(session.files), session.id).run();
}

async function handleStart(request, env, ctx, origin) {
  const test = isTestAuth(request, env);
  const data = await readJson(request);
  const ip = request.headers.get("CF-Connecting-IP") || "";
  const token = data["cf-turnstile-response"] || data.turnstile || "";
  if (!test && !(await verifyTurnstile(token, ip, env))) {
    return json({ ok: false, error: "forbidden" }, 403, origin);
  }
  if (clip(data.website, 200)) {
    return json({ ok: true, done: true }, 200, origin);
  }
  const fields = parseFields(data);
  if (fields.error) return json({ ok: false, error: fields.error }, 400, origin);
  const filesIn = Array.isArray(data.files) ? data.files : [];
  const ferr = validateFileMeta(filesIn);
  if (ferr) return json({ ok: false, error: ferr }, 400, origin);

  const ipHash = await sha256((env.TURNSTILE_SECRET || "") + "|" + ip);
  const nowIso = new Date().toISOString();
  if (!(await rateLimit(env, ipHash, nowIso))) {
    return json({ ok: false, error: "rate_limit" }, 429, origin);
  }

  const isTest = test;
  if (filesIn.length === 0) {
    const id = await insertTip(env, fields, nowIso, ipHash, isTest, "new");
    await notify(env, ctx, id, nowIso, fields);
    return json({ ok: true, id, done: true }, 200, origin);
  }

  const tipId = await insertTip(env, fields, nowIso, ipHash, isTest, "pending");
  const sessionId = crypto.randomUUID();
  const files = filesIn.map((f, i) => {
    const kind = f.kind === "video" || VIDEO_TYPES.has(f.type) ? "video" : "photo";
    const type = String(f.type || (kind === "video" ? "video/mp4" : "image/jpeg"));
    const name = clip(f.name || f.filename || (kind + "-" + (i + 1)), 180);
    const ext = extFor(type, name);
    const id = crypto.randomUUID();
    return {
      id,
      kind,
      content_type: type,
      size: Number(f.size),
      filename: name,
      key: `tips/${tipId}/${kind}-${id}.${ext}`,
      uploaded: false,
    };
  });
  const expires = new Date(Date.now() + SESSION_MS).toISOString();
  await env.DB.prepare(
    "INSERT INTO upload_sessions (id, tip_id, expires_at, files, created_at) VALUES (?, ?, ?, ?, ?)"
  ).bind(sessionId, tipId, expires, JSON.stringify(files), nowIso).run();
  return json({
    ok: true,
    id: tipId,
    session: sessionId,
    done: false,
    files: files.map((f) => ({ id: f.id, kind: f.kind, size: f.size })),
  }, 200, origin);
}

async function handleUpload(request, env, origin, url) {
  const sessionId = url.searchParams.get("session") || "";
  const fileId = url.searchParams.get("file") || "";
  const session = await loadSession(env, sessionId);
  if (!session) return json({ ok: false, error: "forbidden" }, 403, origin);
  const file = session.files.find((f) => f.id === fileId);
  if (!file || file.uploaded) return json({ ok: false, error: "validation" }, 400, origin);

  if (file.kind === "video" && file.size > PART_BYTES) {
    return json({ ok: false, error: "validation" }, 400, origin);
  }
  const declared = Number(request.headers.get("Content-Length") || "0");
  if (!declared || declared !== file.size) return json({ ok: false, error: "validation" }, 400, origin);
  if (file.kind === "photo" && declared > PHOTO_BYTES) return json({ ok: false, error: "too_large" }, 400, origin);
  if (file.kind === "video" && declared > PART_BYTES) return json({ ok: false, error: "too_large" }, 400, origin);

  const buf = await request.arrayBuffer();
  if (buf.byteLength !== file.size) return json({ ok: false, error: "validation" }, 400, origin);
  if (file.kind === "photo" && buf.byteLength > PHOTO_BYTES) return json({ ok: false, error: "too_large" }, 400, origin);

  const sniffed = sniffKind(new Uint8Array(buf.slice(0, 24)), file.content_type, file.filename);
  if (!sniffed || sniffed.kind !== file.kind) return json({ ok: false, error: "validation" }, 400, origin);

  const put = await env.MEDIA.put(file.key, buf, {
    httpMetadata: { contentType: sniffed.type },
    customMetadata: { tip_id: session.tip_id, kind: file.kind },
  });
  if (!put) return json({ ok: false, error: "server" }, 500, origin);
  file.uploaded = true;
  file.content_type = sniffed.type;
  file.size = buf.byteLength;
  await saveSession(env, session);
  return json({ ok: true }, 200, origin);
}

async function handleUploadInit(request, env, origin) {
  const data = await readJson(request);
  const session = await loadSession(env, data.session || "");
  if (!session) return json({ ok: false, error: "forbidden" }, 403, origin);
  const file = session.files.find((f) => f.id === data.file);
  if (!file || file.kind !== "video" || file.uploaded) return json({ ok: false, error: "validation" }, 400, origin);
  if (file.size <= PART_BYTES) return json({ ok: false, error: "validation" }, 400, origin);
  const mp = await env.MEDIA.createMultipartUpload(file.key, {
    httpMetadata: { contentType: file.content_type || "video/mp4" },
    customMetadata: { tip_id: session.tip_id, kind: "video" },
  });
  file.uploadId = mp.uploadId;
  file.parts = [];
  await saveSession(env, session);
  return json({ ok: true, upload_id: mp.uploadId, part_size: PART_BYTES }, 200, origin);
}

async function handleUploadPart(request, env, origin, url) {
  const session = await loadSession(env, url.searchParams.get("session") || "");
  if (!session) return json({ ok: false, error: "forbidden" }, 403, origin);
  const file = session.files.find((f) => f.id === url.searchParams.get("file"));
  const partNum = Number(url.searchParams.get("part") || "0");
  if (!file || !file.uploadId || !Number.isInteger(partNum) || partNum < 1) {
    return json({ ok: false, error: "validation" }, 400, origin);
  }
  const buf = await request.arrayBuffer();
  if (buf.byteLength > PART_BYTES) return json({ ok: false, error: "too_large" }, 400, origin);
  if (partNum === 1 && buf.byteLength >= 12) {
    const sniffed = sniffKind(new Uint8Array(buf.slice(0, 24)), file.content_type, file.filename);
    if (!sniffed || sniffed.kind !== "video") return json({ ok: false, error: "validation" }, 400, origin);
    file.content_type = sniffed.type;
  }
  // parts except last must be >= 5MiB; we require PART_BYTES except when remaining is last
  const uploaded = (file.parts || []).reduce((s, p) => s + (p.size || 0), 0);
  const remainingAfter = file.size - uploaded - buf.byteLength;
  if (remainingAfter > 0 && buf.byteLength < 5 * 1024 * 1024) {
    return json({ ok: false, error: "validation" }, 400, origin);
  }
  const mp = env.MEDIA.resumeMultipartUpload(file.key, file.uploadId);
  const part = await mp.uploadPart(partNum, buf);
  file.parts = file.parts || [];
  file.parts.push({ partNumber: partNum, etag: part.etag, size: buf.byteLength });
  await saveSession(env, session);
  return json({ ok: true, part: partNum, etag: part.etag }, 200, origin);
}

async function handleUploadFinish(request, env, origin) {
  const data = await readJson(request);
  const session = await loadSession(env, data.session || "");
  if (!session) return json({ ok: false, error: "forbidden" }, 403, origin);
  const file = session.files.find((f) => f.id === data.file);
  if (!file || !file.uploadId) return json({ ok: false, error: "validation" }, 400, origin);
  const parts = (file.parts || [])
    .sort((a, b) => a.partNumber - b.partNumber)
    .map((p) => ({ partNumber: p.partNumber, etag: p.etag }));
  if (!parts.length) return json({ ok: false, error: "validation" }, 400, origin);
  const total = (file.parts || []).reduce((s, p) => s + (p.size || 0), 0);
  if (total !== file.size) return json({ ok: false, error: "validation" }, 400, origin);
  const mp = env.MEDIA.resumeMultipartUpload(file.key, file.uploadId);
  await mp.complete(parts);
  file.uploaded = true;
  await saveSession(env, session);
  return json({ ok: true }, 200, origin);
}

async function handleComplete(request, env, ctx, origin) {
  const data = await readJson(request);
  const session = await loadSession(env, data.session || "");
  if (!session) return json({ ok: false, error: "forbidden" }, 403, origin);
  for (const f of session.files) {
    if (!f.uploaded) return json({ ok: false, error: "validation" }, 400, origin);
    const obj = await env.MEDIA.head(f.key);
    if (!obj || (typeof obj.size === "number" && obj.size !== f.size)) {
      return json({ ok: false, error: "validation" }, 400, origin);
    }
    const nowIso = new Date().toISOString();
    await env.DB.prepare(
      "INSERT INTO attachments (id, tip_id, kind, object_key, content_type, size, filename, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    ).bind(f.id, session.tip_id, f.kind, f.key, f.content_type, obj.size || f.size, f.filename, nowIso).run();
  }
  await env.DB.prepare("UPDATE tips SET status = 'new' WHERE id = ? AND status = 'pending'").bind(session.tip_id).run();
  const tip = await env.DB.prepare(
    "SELECT id, created_at, body, place, happened_on, date_unknown, name_style, name_text, contact_type, contact, notify_on_publish FROM tips WHERE id = ?"
  ).bind(session.tip_id).first();
  if (tip) {
    await notify(env, ctx, tip.id, tip.created_at, {
      body: tip.body,
      place: tip.place,
      dateUnknown: !!tip.date_unknown,
      happenedOn: tip.happened_on,
      nameStyle: tip.name_style,
      nameText: tip.name_text,
      contactType: tip.contact_type,
      contact: tip.contact,
      notify: tip.notify_on_publish,
    });
  }
  await env.DB.prepare("DELETE FROM upload_sessions WHERE id = ?").bind(session.id).run();
  return json({ ok: true, id: session.tip_id }, 200, origin);
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
    if (origin && origin !== ALLOWED_ORIGIN && !isTestAuth(request, env)) {
      return json({ ok: false, error: "forbidden" }, 403, origin);
    }
    try {
      if (request.method === "POST" && url.pathname === "/teikyo") {
        // Text-only shortcut (no files). Same checks as /start with empty files.
        const data = await readJson(request);
        data.files = data.files || [];
        if (data.files.length) {
          return json({ ok: false, error: "validation" }, 400, origin);
        }
        // Re-wrap as start
        request = new Request(request.url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Yonek-Test": request.headers.get("X-Yonek-Test") || "", "CF-Connecting-IP": request.headers.get("CF-Connecting-IP") || "" },
          body: JSON.stringify(data),
        });
        return await handleStart(request, env, ctx, origin);
      }
      if (request.method === "POST" && url.pathname === "/teikyo/start") {
        return await handleStart(request, env, ctx, origin);
      }
      if (request.method === "PUT" && url.pathname === "/teikyo/upload") {
        return await handleUpload(request, env, origin, url);
      }
      if (request.method === "POST" && url.pathname === "/teikyo/upload/init") {
        return await handleUploadInit(request, env, origin);
      }
      if (request.method === "PUT" && url.pathname === "/teikyo/upload/part") {
        return await handleUploadPart(request, env, origin, url);
      }
      if (request.method === "POST" && url.pathname === "/teikyo/upload/finish") {
        return await handleUploadFinish(request, env, origin);
      }
      if (request.method === "POST" && url.pathname === "/teikyo/complete") {
        return await handleComplete(request, env, ctx, origin);
      }
      return json({ ok: false, error: "not_found" }, 404, origin);
    } catch (err) {
      console.log(JSON.stringify({ event: "teikyo_error" }));
      return json({ ok: false, error: "server" }, 500, origin);
    }
  },
};

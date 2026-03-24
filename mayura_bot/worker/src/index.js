const HEALTH_PATH = "/health";
const SUBSCRIBERS_PATH = "/subscribers";
const IMPORT_SUBSCRIBERS_PATH = "/admin/import-subs";
const RUN_MONTHLY_PATH = "/admin/run-monthly";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === HEALTH_PATH) {
      return handleHealth(env);
    }

    if (request.method === "GET" && url.pathname === SUBSCRIBERS_PATH) {
      return handleSubscribersExport(request, env);
    }

    if (request.method === "POST" && url.pathname === IMPORT_SUBSCRIBERS_PATH) {
      return handleImportSubscribers(request, env);
    }

    if (request.method === "POST" && url.pathname === RUN_MONTHLY_PATH) {
      return handleManualRun(request, env, ctx);
    }

    if (request.method === "POST" && url.pathname === `/${env.SECRET_PATH}`) {
      return handleWebhook(request, env, ctx);
    }

    return new Response("Not found", { status: 404 });
  },
};

async function handleWebhook(request, env, ctx) {
  const update = await request.json().catch(() => null);
  if (!update) {
    return new Response("bad request", { status: 400 });
  }

  const msg = update.message || update.channel_post;
  if (!msg || !msg.chat || !msg.chat.id) {
    return new Response("ok");
  }

  const chatId = String(msg.chat.id);
  const firstName = msg.from?.first_name || "there";
  const text = String(msg.text || "").trim();

  if (text.startsWith("/start")) {
    await addSubscriber(env, chatId, firstName);
    await tgSendMessage(
      env,
      chatId,
      [
        `Namaskara ${firstName}.`,
        "You are now subscribed to Mayura e-zine updates.",
        "",
        "Commands:",
        "  /latest - send cached edition",
        "  /stop - unsubscribe",
      ].join("\n"),
    );
  } else if (text.startsWith("/stop")) {
    await removeSubscriber(env, chatId);
    await tgSendMessage(env, chatId, "You have been unsubscribed. Send /start to resubscribe.");
  } else if (text.startsWith("/latest")) {
    ctx.waitUntil(sendLatestToChat(env, chatId));
    await tgSendMessage(env, chatId, "Fetching cached/latest edition. You will receive it shortly.");
  } else {
    await tgSendMessage(env, chatId, "Commands:\n  /start\n  /latest\n  /stop");
  }

  return new Response("ok");
}

async function handleHealth(env) {
  const ids = await listSubscriberIds(env);
  const monthKey = getMonthKey();
  const meta = await getMonthMetaWithFallback(env, monthKey);

  return json({
    status: "ok",
    subscribers: ids.length,
    month_key: monthKey,
    pdf_cached: Boolean(meta?.r2_key),
  });
}

async function handleSubscribersExport(request, env) {
  if (!isAdminAuthorized(request, env)) {
    return new Response("forbidden", { status: 403 });
  }

  const ids = await listSubscriberIds(env);
  return json({ subscribers: ids, csv: ids.join(",") });
}

async function handleImportSubscribers(request, env) {
  if (!isAdminAuthorized(request, env)) {
    return new Response("forbidden", { status: 403 });
  }

  const ct = request.headers.get("content-type") || "";
  const raw = await request.text();
  let ids = [];

  if (ct.includes("application/json")) {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      ids = parsed.map(String);
    } else if (Array.isArray(parsed?.subscribers)) {
      ids = parsed.subscribers.map(String);
    }
  } else {
    ids = raw.split(",").map((s) => s.trim()).filter(Boolean);
  }

  ids = Array.from(new Set(ids));
  for (const chatId of ids) {
    await addSubscriber(env, chatId, "imported");
  }

  return json({ imported: ids.length });
}

async function handleManualRun(request, env, ctx) {
  if (!isAdminAuthorized(request, env)) {
    return new Response("forbidden", { status: 403 });
  }

  ctx.waitUntil(runMonthlyBroadcast(env));
  return json({ status: "scheduled" });
}

function isAdminAuthorized(request, env) {
  const url = new URL(request.url);
  const token = url.searchParams.get("token") || request.headers.get("x-admin-token");
  return Boolean(env.ADMIN_TOKEN) && token === env.ADMIN_TOKEN;
}

async function sendLatestToChat(env, chatId) {
  try {
    const monthKey = getMonthKey();
    const { fileId } = await ensureMonthlyPdfAndFileId(env, monthKey, chatId);
    await tgSendDocumentByFileId(env, chatId, fileId, captionForMonth(monthKey));
  } catch (err) {
    await tgSendMessage(env, chatId, `Failed to send latest edition: ${String(err)}`);
  }
}

async function runMonthlyBroadcast(env) {
  const monthKey = getMonthKey();
  const subscribers = await listSubscriberIds(env);

  if (!subscribers.length) {
    return;
  }

  const seedChatId = subscribers[0];
  const { fileId } = await ensureMonthlyPdfAndFileId(env, monthKey, seedChatId);
  const caption = captionForMonth(monthKey);

  for (const chatId of subscribers) {
    try {
      await tgSendDocumentByFileId(env, chatId, fileId, caption);
    } catch (err) {
      console.error(`send failed for ${chatId}`, err);
    }
  }
}

async function ensureMonthlyPdfAndFileId(env, monthKey, seedChatId) {
  let meta = await getMonthMetaWithFallback(env, monthKey);
  if (!meta?.r2_key) {
    throw new Error(
      `No cached PDF found for ${monthKey}. Upload to R2 key: ${expectedR2Key(monthKey)}`,
    );
  }

  if (!meta.telegram_file_id) {
    const obj = await env.PDF_CACHE.get(meta.r2_key);
    if (!obj) {
      throw new Error(`Missing R2 object: ${meta.r2_key}`);
    }

    const bytes = await obj.arrayBuffer();
    const uploaded = await tgUploadDocument(env, seedChatId, bytes, `mayura_${monthKey}.pdf`, captionForMonth(monthKey));
    const fileId = uploaded?.result?.document?.file_id;
    if (!fileId) {
      throw new Error(`Telegram upload did not return file_id: ${JSON.stringify(uploaded)}`);
    }

    meta.telegram_file_id = fileId;
    await saveMonthMeta(env, monthKey, meta);
  }

  return { meta, fileId: meta.telegram_file_id };
}

function getMonthKey() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
  }).formatToParts(new Date());

  const year = parts.find((p) => p.type === "year")?.value;
  const month = parts.find((p) => p.type === "month")?.value;
  return `${year}-${month}`;
}

function captionForMonth(monthKey) {
  return `ಮಯೂರ | Mayura — ${monthKey} Edition`;
}

async function tgSendMessage(env, chatId, text) {
  const endpoint = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  const resp = await fetch(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });

  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`Telegram sendMessage failed (${resp.status}): ${body}`);
  }
}

async function tgSendDocumentByFileId(env, chatId, fileId, caption) {
  const endpoint = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendDocument`;
  const resp = await fetch(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      document: fileId,
      caption,
    }),
  });

  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`Telegram sendDocument(file_id) failed (${resp.status}): ${body}`);
  }

  const result = await resp.json();
  if (!result.ok) {
    throw new Error(`Telegram sendDocument(file_id) API error: ${JSON.stringify(result)}`);
  }

  return result;
}

async function tgUploadDocument(env, chatId, bytes, filename, caption) {
  const endpoint = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendDocument`;
  const form = new FormData();
  form.set("chat_id", chatId);
  form.set("caption", caption);
  form.set("document", new Blob([bytes], { type: "application/pdf" }), filename);

  const resp = await fetch(endpoint, {
    method: "POST",
    body: form,
  });

  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`Telegram upload failed (${resp.status}): ${body}`);
  }

  const result = await resp.json();
  if (!result.ok) {
    throw new Error(`Telegram upload API error: ${JSON.stringify(result)}`);
  }

  return result;
}

async function addSubscriber(env, chatId, firstName) {
  const value = JSON.stringify({
    first_name: firstName,
    subscribed_at: new Date().toISOString(),
  });
  await env.SUBSCRIBERS.put(subscriberKey(chatId), value);
}

async function removeSubscriber(env, chatId) {
  await env.SUBSCRIBERS.delete(subscriberKey(chatId));
}

async function listSubscriberIds(env) {
  const out = [];
  let cursor;

  do {
    const page = await env.SUBSCRIBERS.list({ cursor, limit: 1000 });
    for (const key of page.keys) {
      if (key.name.startsWith("sub:")) {
        out.push(key.name.slice(4));
      } else if (/^-?\d+$/.test(key.name)) {
        // Backward-compatible: include legacy chat-id keys without prefix.
        out.push(key.name);
      }
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);

  return out;
}

function subscriberKey(chatId) {
  return `sub:${chatId}`;
}

function monthMetaKey(monthKey) {
  return `meta:${monthKey}`;
}

function expectedR2Key(monthKey) {
  return `pdfs/${monthKey}/mayura_${monthKey}.pdf`;
}

async function getMonthMeta(env, monthKey) {
  const raw = await env.SUBSCRIBERS.get(monthMetaKey(monthKey));
  return raw ? JSON.parse(raw) : null;
}

async function getMonthMetaWithFallback(env, monthKey) {
  const existing = await getMonthMeta(env, monthKey);
  if (existing?.r2_key) {
    return existing;
  }

  const r2Key = expectedR2Key(monthKey);
  const head = await env.PDF_CACHE.head(r2Key);
  if (!head) {
    return existing || null;
  }

  const next = {
    ...(existing || {}),
    month_key: monthKey,
    r2_key: r2Key,
    discovered_at: new Date().toISOString(),
  };
  await saveMonthMeta(env, monthKey, next);
  return next;
}

async function saveMonthMeta(env, monthKey, meta) {
  await env.SUBSCRIBERS.put(monthMetaKey(monthKey), JSON.stringify(meta));
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

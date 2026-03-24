const HEALTH_PATH = "/health";
const SUBSCRIBERS_PATH = "/subscribers";
const IMPORT_SUBSCRIBERS_PATH = "/admin/import-subs";
const RUN_MONTHLY_PATH = "/admin/run-monthly";
const RUN_WEEKLY_SUDHA_PATH = "/admin/run-weekly-sudha";

const SERIES = {
  mayura: {
    label: "ಮಯೂರ | Mayura",
    cadence: "monthly",
    expectedR2Key: (periodKey) => `pdfs/${periodKey}/mayura_${periodKey}.pdf`,
    filename: (periodKey) => `mayura_${periodKey}.pdf`,
  },
  sudha: {
    label: "ಸುಧಾ | Sudha",
    cadence: "weekly",
    expectedR2Key: (periodKey) => `pdfs/sudha/${periodKey}/sudha_${periodKey}.pdf`,
    filename: (periodKey) => `sudha_${periodKey}.pdf`,
  },
};

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
      return handleManualRunMayura(request, env, ctx);
    }

    if (request.method === "POST" && url.pathname === RUN_WEEKLY_SUDHA_PATH) {
      return handleManualRunSudha(request, env, ctx);
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
  const text = String(msg.text || "").trim().toLowerCase();

  if (text.startsWith("/start")) {
    await addSubscriber(env, chatId, firstName);
    await tgSendMessage(
      env,
      chatId,
      [
        `Namaskara ${firstName}.`,
        "You are now subscribed to e-zine updates.",
        "",
        "Commands:",
        "  /latest_mayura - send Mayura monthly cached edition",
        "  /latest_sudha - send Sudha weekly cached edition",
        "  /stop - unsubscribe",
      ].join("\n"),
    );
  } else if (text.startsWith("/stop")) {
    await removeSubscriber(env, chatId);
    await tgSendMessage(env, chatId, "You have been unsubscribed. Send /start to resubscribe.");
  } else if (text.startsWith("/latest_mayura")) {
    ctx.waitUntil(sendLatestToChat(env, chatId, "mayura"));
    await tgSendMessage(env, chatId, "Fetching Mayura cached/latest edition. You will receive it shortly.");
  } else if (text.startsWith("/latest_sudha")) {
    ctx.waitUntil(sendLatestToChat(env, chatId, "sudha"));
    await tgSendMessage(env, chatId, "Fetching Sudha cached/latest edition. You will receive it shortly.");
  } else {
    await tgSendMessage(env, chatId, "Commands:\n  /start\n  /latest_mayura\n  /latest_sudha\n  /stop");
  }

  return new Response("ok");
}

async function handleHealth(env) {
  const ids = await listSubscriberIds(env);
  const mayuraPeriod = getPeriodKey("mayura");
  const sudhaPeriod = getPeriodKey("sudha");
  const mayuraMeta = await getMetaWithFallback(env, "mayura", mayuraPeriod);
  const sudhaMeta = await getMetaWithFallback(env, "sudha", sudhaPeriod);

  return json({
    status: "ok",
    subscribers: ids.length,
    mayura_period: mayuraPeriod,
    mayura_pdf_cached: Boolean(mayuraMeta?.r2_key),
    sudha_period: sudhaPeriod,
    sudha_pdf_cached: Boolean(sudhaMeta?.r2_key),
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

async function handleManualRunMayura(request, env, ctx) {
  if (!isAdminAuthorized(request, env)) {
    return new Response("forbidden", { status: 403 });
  }

  ctx.waitUntil(runBroadcast(env, "mayura"));
  return json({ status: "scheduled", series: "mayura" });
}

async function handleManualRunSudha(request, env, ctx) {
  if (!isAdminAuthorized(request, env)) {
    return new Response("forbidden", { status: 403 });
  }

  ctx.waitUntil(runBroadcast(env, "sudha"));
  return json({ status: "scheduled", series: "sudha" });
}

function isAdminAuthorized(request, env) {
  const url = new URL(request.url);
  const token = url.searchParams.get("token") || request.headers.get("x-admin-token");
  return Boolean(env.ADMIN_TOKEN) && token === env.ADMIN_TOKEN;
}

async function sendLatestToChat(env, chatId, series) {
  try {
    const periodKey = getPeriodKey(series);
    const { fileId } = await ensurePdfAndFileId(env, series, periodKey, chatId);
    await tgSendDocumentByFileId(env, chatId, fileId, caption(series, periodKey));
  } catch (err) {
    await tgSendMessage(env, chatId, `Failed to send ${series} edition: ${String(err)}`);
  }
}

async function runBroadcast(env, series) {
  const periodKey = getPeriodKey(series);
  const subscribers = await listSubscriberIds(env);

  if (!subscribers.length) {
    return;
  }

  const seedChatId = subscribers[0];
  const { fileId } = await ensurePdfAndFileId(env, series, periodKey, seedChatId);
  const fileCaption = caption(series, periodKey);

  for (const chatId of subscribers) {
    try {
      await tgSendDocumentByFileId(env, chatId, fileId, fileCaption);
    } catch (err) {
      console.error(`send failed for ${chatId}`, err);
    }
  }
}

async function ensurePdfAndFileId(env, series, periodKey, seedChatId) {
  let meta = await getMetaWithFallback(env, series, periodKey);
  if (!meta?.r2_key) {
    throw new Error(
      `No cached PDF found for ${series} ${periodKey}. Upload to R2 key: ${expectedR2Key(series, periodKey)}`,
    );
  }

  if (!meta.telegram_file_id) {
    const obj = await env.PDF_CACHE.get(meta.r2_key);
    if (!obj) {
      throw new Error(`Missing R2 object: ${meta.r2_key}`);
    }

    const bytes = await obj.arrayBuffer();
    const uploaded = await tgUploadDocument(
      env,
      seedChatId,
      bytes,
      SERIES[series].filename(periodKey),
      caption(series, periodKey),
    );
    const fileId = uploaded?.result?.document?.file_id;
    if (!fileId) {
      throw new Error(`Telegram upload did not return file_id: ${JSON.stringify(uploaded)}`);
    }

    meta.telegram_file_id = fileId;
    await saveMeta(env, series, periodKey, meta);
  }

  return { meta, fileId: meta.telegram_file_id };
}

function getPeriodKey(series) {
  if (SERIES[series].cadence === "monthly") {
    return getMonthKey();
  }

  return getIsoWeekKeyInKolkata();
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

function getIsoWeekKeyInKolkata() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());

  const year = Number(parts.find((p) => p.type === "year")?.value);
  const month = Number(parts.find((p) => p.type === "month")?.value);
  const day = Number(parts.find((p) => p.type === "day")?.value);

  // Convert Kolkata local date into UTC-based date arithmetic for ISO week calc.
  const date = new Date(Date.UTC(year, month - 1, day));
  const weekday = (date.getUTCDay() + 6) % 7; // Monday=0
  date.setUTCDate(date.getUTCDate() - weekday + 3); // Thursday of current week

  const isoYear = date.getUTCFullYear();
  const firstThursday = new Date(Date.UTC(isoYear, 0, 4));
  const firstWeekday = (firstThursday.getUTCDay() + 6) % 7;
  firstThursday.setUTCDate(firstThursday.getUTCDate() - firstWeekday + 3);

  const weekNumber = 1 + Math.round((date - firstThursday) / (7 * 24 * 60 * 60 * 1000));
  return `${isoYear}-W${String(weekNumber).padStart(2, "0")}`;
}

function caption(series, periodKey) {
  return `${SERIES[series].label} — ${periodKey} Edition`;
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

async function tgSendDocumentByFileId(env, chatId, fileId, fileCaption) {
  const endpoint = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendDocument`;
  const resp = await fetch(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      document: fileId,
      caption: fileCaption,
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

async function tgUploadDocument(env, chatId, bytes, filename, fileCaption) {
  const endpoint = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendDocument`;
  const form = new FormData();
  form.set("chat_id", chatId);
  form.set("caption", fileCaption);
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

function metaKey(series, periodKey) {
  return `meta:${series}:${periodKey}`;
}

function expectedR2Key(series, periodKey) {
  return SERIES[series].expectedR2Key(periodKey);
}

async function getMeta(env, series, periodKey) {
  const raw = await env.SUBSCRIBERS.get(metaKey(series, periodKey));
  return raw ? JSON.parse(raw) : null;
}

async function getMetaWithFallback(env, series, periodKey) {
  const existing = await getMeta(env, series, periodKey);
  if (existing?.r2_key) {
    return existing;
  }

  const r2Key = expectedR2Key(series, periodKey);
  const head = await env.PDF_CACHE.head(r2Key);
  if (!head) {
    return existing || null;
  }

  const next = {
    ...(existing || {}),
    series,
    period_key: periodKey,
    r2_key: r2Key,
    discovered_at: new Date().toISOString(),
  };
  await saveMeta(env, series, periodKey, next);
  return next;
}

async function saveMeta(env, series, periodKey, meta) {
  await env.SUBSCRIBERS.put(metaKey(series, periodKey), JSON.stringify(meta));
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

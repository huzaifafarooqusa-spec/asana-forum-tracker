// Telegram control + chat bot for the Asana forum tracker and MEXC scalper.
// Telegram calls POST /telegram (webhook); GET /register points the bot's webhook here.

const OWNER = "huzaifafarooqusa-spec";
const BOTS = {
  tracker: { repo: `${OWNER}/asana-forum-tracker`, workflow: "tracker.yml", label: "Asana tracker" },
  scalper: { repo: `${OWNER}/mexc-safe-scalper`, workflow: "scalper.yml", label: "MEXC scalper" },
};
const HISTORY_LIMIT = 12;
// Some Cloudflare-fronted gateways reject non-browser clients (error 1010)
const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36";
const SYSTEM_PROMPT =
  "You are a concise, helpful assistant in Telegram for Huzaifa, an Asana and operations consultant " +
  "(KlarityOps). Answer clearly and briefly. Plain text only, no markdown tables. If asked about the bots, " +
  "mention the commands: /status, /pause, /resume, /testdraft, /probe, /price, /models, /model, /reset.";
const HELP = `Commands:
/status – scalper balance & trades, tracker alerts, bots on/off
/pause [tracker|scalper|all] – stop a bot
/resume [tracker|scalper|all] – start it again
/testdraft [n] – test AI drafts for the last n forum questions
/probe – check which AI models the tracker can use
/price [coin] – live MEXC price, e.g. /price MOVR
/models – list chat models · /model <name> – switch
/reset – clear chat memory
Anything else is a chat message.`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/register") return register(env, url.origin);
    if (url.pathname !== "/telegram" || request.method !== "POST") return new Response("ok");
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== (await webhookSecret(env))) {
      return new Response("forbidden", { status: 403 });
    }
    const update = await request.json();
    const msg = update.message;
    if (!msg?.text || String(msg.chat.id) !== String(env.CHAT_ID)) return new Response("ok");
    // Telegram retries slow webhooks; handle each update once
    if ((await env.KV.get(`update:${update.update_id}`)) !== null) return new Response("ok");
    await env.KV.put(`update:${update.update_id}`, "1", { expirationTtl: 3600 });
    try {
      await handle(env, msg.chat.id, msg.text.trim());
    } catch (e) {
      await send(env, msg.chat.id, `❌ Error: ${e.message}`);
    }
    return new Response("ok");
  },
};

async function handle(env, chatId, text) {
  const [cmd, ...args] = text.split(/\s+/);
  const arg = args.join(" ");
  switch (cmd.toLowerCase().replace(/@.*$/, "")) {
    case "/start":
    case "/help":
      return send(env, chatId, HELP);
    case "/status":
      return send(env, chatId, await status(env));
    case "/pause":
    case "/resume":
      return send(env, chatId, await toggle(env, cmd === "/resume", arg || "all"));
    case "/testdraft":
      return send(env, chatId, await dispatch(env, "tracker", {
        test_draft: "true", test_count: String(Math.min(Math.max(parseInt(arg) || 1, 1), 10)),
      }, "🧪 Test drafts started; they arrive here in a few minutes."));
    case "/probe":
      return send(env, chatId, await dispatch(env, "tracker", { probe_models: "true" },
        "🔎 Model probe started. Results are in the GitHub Actions log of the run."));
    case "/price":
      return send(env, chatId, await price(arg || "MOVR"));
    case "/models":
      return send(env, chatId, await listModels(env));
    case "/model":
      if (!arg) return send(env, chatId, `Current model: ${(await currentModel(env)) || "(none set)"}`);
      await env.KV.put("model", arg);
      return send(env, chatId, `✅ Chat model set to ${arg}`);
    case "/reset":
      await env.KV.delete("history");
      return send(env, chatId, "🧹 Chat memory cleared.");
    default:
      return chat(env, chatId, text);
  }
}

// --- Chat --------------------------------------------------------------------

async function currentModel(env) {
  return (await env.KV.get("model")) || env.DEFAULT_MODEL;
}

async function chat(env, chatId, text) {
  const model = await currentModel(env);
  if (!model) return send(env, chatId, "No chat model set yet. Use /models, then /model <name>.");
  await tg(env, "sendChatAction", { chat_id: chatId, action: "typing" });
  const history = JSON.parse((await env.KV.get("history")) || "[]");
  history.push({ role: "user", content: text });
  const res = await fetch(`${env.LLM_BASE_URL}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${env.LLM_API_KEY}`, "User-Agent": UA },
    body: JSON.stringify({ model, messages: [{ role: "system", content: SYSTEM_PROMPT }, ...history] }),
  });
  if (!res.ok) return send(env, chatId, `❌ Chat API error ${res.status}: ${(await res.text()).slice(0, 300)}`);
  const data = await res.json();
  const reply = data.choices?.[0]?.message?.content?.trim() || "(empty reply)";
  history.push({ role: "assistant", content: reply });
  await env.KV.put("history", JSON.stringify(history.slice(-HISTORY_LIMIT)));
  return send(env, chatId, reply);
}

async function listModels(env) {
  const res = await fetch(`${env.LLM_BASE_URL}/models`, { headers: { Authorization: `Bearer ${env.LLM_API_KEY}`, "User-Agent": UA } });
  if (!res.ok) return `❌ Models API error ${res.status}`;
  const ids = ((await res.json()).data || []).map((m) => m.id);
  return `${ids.length} models (current: ${(await currentModel(env)) || "none"}):\n` + ids.slice(0, 80).join("\n");
}

// --- Bot control ---------------------------------------------------------------

async function github(env, path, init = {}) {
  return fetch(`https://api.github.com${path}`, {
    ...init,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "User-Agent": "klarity-telegram-bot",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(init.headers || {}),
    },
  });
}

async function dispatch(env, bot, inputs, okText) {
  const b = BOTS[bot];
  const res = await github(env, `/repos/${b.repo}/actions/workflows/${b.workflow}/dispatches`, {
    method: "POST",
    body: JSON.stringify({ ref: "main", inputs }),
  });
  return res.status === 204 ? okText : `❌ GitHub error ${res.status}: ${(await res.text()).slice(0, 200)}`;
}

async function toggle(env, enable, which) {
  const names = which === "all" ? Object.keys(BOTS) : [which];
  const lines = [];
  for (const name of names) {
    const b = BOTS[name];
    if (!b) { lines.push(`Unknown bot "${name}". Use tracker, scalper or all.`); continue; }
    const res = await github(env, `/repos/${b.repo}/actions/workflows/${b.workflow}/${enable ? "enable" : "disable"}`,
      { method: "PUT" });
    lines.push(res.status === 204 ? `${enable ? "▶️ Resumed" : "⏸ Paused"}: ${b.label}`
      : `❌ ${b.label}: GitHub error ${res.status}`);
  }
  return lines.join("\n");
}

async function status(env) {
  const out = [];
  for (const [name, b] of Object.entries(BOTS)) {
    const wf = await (await github(env, `/repos/${b.repo}/actions/workflows/${b.workflow}`)).json();
    const runs = await (await github(env, `/repos/${b.repo}/actions/workflows/${b.workflow}/runs?per_page=1`)).json();
    const last = runs.workflow_runs?.[0];
    out.push(`${wf.state === "active" ? "🟢" : "⏸"} ${b.label}: ${wf.state}` +
      (last ? `, last run ${ago(last.created_at)} (${last.conclusion || last.status})` : ""));
    const state = await (await fetch(`https://raw.githubusercontent.com/${b.repo}/state/state.json?t=${Date.now()}`)).json()
      .catch(() => null);
    if (!state) continue;
    if (name === "scalper") {
      const s = state.stats;
      const open = Object.values(state.open_trades || {});
      out.push(`   💰 Cash $${state.virtual_balance.toFixed(2)} · trades ${s.total_trades} ` +
        `(${s.wins}W/${s.losses}L) · P&L ${s.total_profit_usdt >= 0 ? "+" : ""}${s.total_profit_usdt.toFixed(2)}`);
      for (const t of open) out.push(`   📂 ${t.symbol} @ ${t.entry_price.toPrecision(5)} since ${t.entry_time}`);
    } else {
      const d = state.daily;
      out.push(`   🔔 Today: ${d.alerts} alerts, ${d.priority} priority, ${d.drafts || 0} drafts`);
    }
  }
  return out.join("\n");
}

async function price(coin) {
  const symbol = coin.toUpperCase().replace(/USDT$/, "") + "USDT";
  const res = await fetch(`https://api.mexc.com/api/v3/ticker/24hr?symbol=${symbol}`);
  if (!res.ok) return `❌ No MEXC price for ${symbol}`;
  const t = await res.json();
  const chg = parseFloat(t.priceChangePercent) * (Math.abs(parseFloat(t.priceChangePercent)) < 1 ? 100 : 1);
  return `${symbol}: ${parseFloat(t.lastPrice)}\n24h: ${chg >= 0 ? "+" : ""}${chg.toFixed(2)}% · ` +
    `high ${parseFloat(t.highPrice)} · low ${parseFloat(t.lowPrice)}`;
}

function ago(iso) {
  const m = Math.round((Date.now() - Date.parse(iso)) / 60000);
  return m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`;
}

// --- Telegram ------------------------------------------------------------------

async function tg(env, method, body) {
  return fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function send(env, chatId, text) {
  for (let i = 0; i < text.length; i += 4000) {
    await tg(env, "sendMessage", { chat_id: chatId, text: text.slice(i, i + 4000), disable_web_page_preview: true });
  }
}

async function webhookSecret(env) {
  // Derived from the bot token, so there is no extra secret to manage
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`webhook:${env.BOT_TOKEN}`));
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 48);
}

async function register(env, origin) {
  const set = await (await tg(env, "setWebhook", {
    url: `${origin}/telegram`,
    secret_token: await webhookSecret(env),
    allowed_updates: ["message"],
    drop_pending_updates: true,
  })).json();
  await tg(env, "setMyCommands", {
    commands: [
      ["status", "Bots status, balance, alerts"], ["pause", "Pause tracker|scalper|all"],
      ["resume", "Resume tracker|scalper|all"], ["testdraft", "Test AI drafts (n questions)"],
      ["probe", "Check tracker AI models"], ["price", "Live MEXC price, e.g. /price MOVR"],
      ["models", "List chat models"], ["model", "Switch chat model"], ["reset", "Clear chat memory"],
      ["help", "Show commands"],
    ].map(([command, description]) => ({ command, description })),
  });
  return Response.json({ webhook: set.ok, description: set.description });
}

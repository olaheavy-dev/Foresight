// A scripted stand-in for the Foresight API, for Workspace journeys and screenshots
// (playwright.workspace.config.ts). It serves the same contracts as the real backend from the
// typed fixtures in src/test/workspaceFixtures.ts: session, features, threads, messages, the run
// event stream (SSE with ids and Last-Event-ID replay), stored responses and calculations.
//
//   node e2e/mock-api.mjs            # port 8787 (MOCK_API_PORT), every Workspace flag on
//   MOCK_FLAGS=off node e2e/mock-api.mjs   # as deployed today: every flag off
//
// Which script a question gets: "invest"/"shares" → refusal; "which"/"trip?" → clarifying
// question; "next month" → engine timeout; "spend"/"eat" → spending answer; anything else →
// affordability answer. "degraded" → the spending answer marked degraded.
import { createServer } from "node:http";

const fx = await import(new URL("../src/test/workspaceFixtures.ts", import.meta.url).href);
const PORT = Number(process.env.MOCK_API_PORT ?? 8787);
const FLAGS_ON = process.env.MOCK_FLAGS !== "off";
const SPEED = Number(process.env.MOCK_SPEED ?? 1);

const profile = {
  workspace_id: fx.WORKSPACE_ID,
  name: "Sam Okafor",
  kind: "demo",
  persona: "P1",
  country: "GB",
  home_currency: "GBP",
  locale: "en-GB",
  timezone: "Europe/London",
  data_version: 2,
  read_only: true,
  account: { kind: "guest", name: null, email: null },
};
const FEATURES = ["forecast", "agents", "checked_advice", "audit_trail", "ask", "anomaly_detection"].map((key, i) => ({
  key,
  stage: i < 1 ? 1 : 2,
  title: key,
  enabled: FLAGS_ON,
}));

const responses = new Map();
for (const r of [fx.affordabilityResponse(), fx.spendingResponse(), fx.refusalResponse(), fx.degradedResponse()])
  responses.set(r.response_id, r);

const runs = new Map(); // run_id → script
const threads = new Map(); // thread_id → { title, created_at, messages[] }
// AI status: GET /api/ai-status; tests switch it with POST /__mock/ai-status {status}.
let aiStatus = process.env.MOCK_AI_STATUS ?? "ok";
let seq = 100;
const nextId = (prefix) => fx.uid(prefix, seq++);

function scriptFor(text) {
  const t = text.toLowerCase();
  if (/invest|shares|crypto/.test(t))
    return fx
      .answerScript(fx.refusalResponse(), text)
      .filter((e) => e.event !== "step" || e.data.agent === "coordinator");
  if (aiStatus === "unavailable")
    return [{ event: "error", data: { code: "ai_unavailable", retryable: true }, delayMs: 300 }];
  if (/^which/.test(t) || /trip\?$/.test(t)) return fx.clarifyScript();
  if (/next month/.test(t)) return fx.errorScript();
  if (/degraded/.test(t)) return fx.answerScript(fx.degradedResponse(), text);
  if (/spend|eat|delivery/.test(t))
    return fx.answerScript(fx.spendingResponse(), "Why is my eating-out spending higher than usual?");
  return fx.answerScript(fx.affordabilityResponse(), "Can I afford a one-off trip in December?");
}

const json = (res, status, body, headers = {}) => {
  res.writeHead(status, { "content-type": "application/json", ...headers });
  res.end(JSON.stringify(body));
};

async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  try {
    return JSON.parse(Buffer.concat(chunks).toString() || "{}");
  } catch {
    return {};
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms / SPEED));

createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const path = url.pathname;
  const cookie = "foresight_session=mock; Path=/; HttpOnly; SameSite=Lax";

  if (path === "/healthz") return json(res, 200, { status: "ok", sha: "mock", database: true });
  if (path === "/api/features") return json(res, 200, { features: FEATURES });
  if (path === "/api/session" && req.method === "GET") return json(res, 200, profile);
  if (path === "/api/session/demo" && req.method === "POST") return json(res, 200, profile, { "set-cookie": cookie });
  if (path === "/api/auth/providers") return json(res, 200, { google: process.env.MOCK_GOOGLE === "1", guest: true });
  if (path === "/api/session/logout" || path === "/api/session/delete") {
    res.writeHead(204, { "set-cookie": "foresight_session=; Path=/; Max-Age=0" });
    return res.end();
  }
  if (path === "/api/forecast" || path === "/api/public/demo-forecast") {
    const chart = fx.forecastChart();
    return json(res, 200, {
      forecast_id: `fc_${"0a1b2c3d4e5f60718293a4b5"}`,
      workspace_id: fx.WORKSPACE_ID,
      currency: "GBP",
      locale: "en-GB",
      engine_version: "fc-test",
      data_version: 2,
      chart,
    });
  }
  if (path === "/api/ai-status") {
    const message = aiStatus === "ok" ? null : aiStatus === "degraded" ? "Slower than usual" : "Paused";
    return json(res, 200, { status: aiStatus, message });
  }
  if (path === "/__mock/ai-status" && req.method === "POST") {
    aiStatus = String((await readBody(req)).status ?? "ok");
    return json(res, 200, { status: aiStatus });
  }
  if (path === "/api/threads" && req.method === "POST") {
    const id = nextId("thr");
    threads.set(id, { title: "", created_at: new Date().toISOString(), messages: [] });
    return json(res, 201, { thread_id: id });
  }
  if (path === "/api/threads" && req.method === "GET") {
    const list = [...threads.entries()]
      .filter(([, t]) => t.messages.length)
      .map(([thread_id, t]) => ({ thread_id, title: t.title, created_at: t.created_at }))
      .reverse();
    return json(res, 200, { threads: list });
  }
  const one = /^\/api\/threads\/(thr_[0-9A-Z]{26})$/.exec(path);
  if (one && req.method === "GET") {
    const t = threads.get(one[1]);
    return t
      ? json(res, 200, { thread_id: one[1], title: t.title, messages: t.messages })
      : json(res, 404, { detail: "Not found" });
  }

  const msg = /^\/api\/threads\/(thr_[0-9A-Z]{26})\/messages$/.exec(path);
  if (msg && req.method === "POST") {
    const body = await readBody(req);
    const runId = nextId("run");
    const text = String(body.text ?? "");
    // A guest whose network has used today's allowance (backend/app/network_cap.py REFUSED).
    if (/allowance/i.test(text))
      return json(res, 429, {
        detail:
          "Today’s guest allowance for your network is used. Sign in with Google to keep going, or come back tomorrow.",
      });
    const script = scriptFor(text);
    runs.set(runId, script);
    const thread = threads.get(msg[1]) ?? { title: "", created_at: new Date().toISOString(), messages: [] };
    if (!thread.title) thread.title = text.slice(0, 60);
    const now = new Date().toISOString();
    thread.messages.push({
      message_id: nextId("msg"),
      role: "user",
      text,
      standalone_question: null,
      run_id: runId,
      response_id: null,
      created_at: now,
    });
    const answer = script.find((e) => e.event === "answer");
    if (answer)
      thread.messages.push({
        message_id: nextId("msg"),
        role: "assistant",
        text: "",
        standalone_question: null,
        run_id: runId,
        response_id: answer.data.rsp_id,
        created_at: now,
      });
    threads.set(msg[1], thread);
    return json(res, 202, { run_id: runId, thread_id: msg[1] });
  }

  const events = /^\/api\/runs\/(run_[0-9A-Z]{26})\/events$/.exec(path);
  if (events) {
    const script = runs.get(events[1]);
    if (!script) return json(res, 404, { detail: "Not found" });
    const after = Number(req.headers["last-event-id"] ?? url.searchParams.get("last_event_id") ?? 0);
    // Sent like the real backend (no-store, no no-transform): the Next route handler for this
    // path must keep the stream unbuffered on its own.
    res.writeHead(200, {
      "content-type": "text/event-stream",
      "cache-control": "no-store",
      "x-accel-buffering": "no",
      connection: "keep-alive",
    });
    res.write(": stream open\n\n");
    for (let i = after; i < script.length; i += 1) {
      const e = script[i];
      await sleep(e.delayMs);
      if (res.destroyed) return;
      res.write(`id: ${i + 1}\nevent: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`);
    }
    return res.end();
  }

  const rsp = /^\/api\/responses\/(rsp_[0-9A-Z]{26})$/.exec(path);
  if (rsp)
    return responses.has(rsp[1]) ? json(res, 200, responses.get(rsp[1])) : json(res, 404, { detail: "Not found" });

  const calc = /^\/api\/calculations\/(calc_[0-9a-zA-Z]+)$/.exec(path);
  if (calc)
    return calc[1] === fx.calculation().calc_id
      ? json(res, 200, fx.calculation())
      : json(res, 404, { detail: "Not found" });

  return json(res, 404, { detail: "Not found" });
}).listen(PORT, () => console.log(`mock api on :${PORT} (flags ${FLAGS_ON ? "on" : "off"})`));

/**
 * The Ask pipeline client (docs/05 §4.2): create a thread, post a question, then follow the run's
 * typed event stream until it answers, asks a clarifying question or fails.
 *
 * Endpoints (W2-3):
 *   POST /api/threads                       → { thread_id }
 *   POST /api/threads/{id}/messages         { text, client_msg_id, action? } → { run_id }
 *   GET  /api/runs/{run_id}/events          SSE: run.started · step · clarify · answer · error · heartbeat
 *   GET  /api/responses/{rsp_id}            stored snapshot (fetchResponse in api.ts)
 *
 * Events carry an increasing `id`. The browser's EventSource resends it as `Last-Event-ID` when
 * it reconnects; a manual reconnect passes `?last_event_id=` instead. The reducer ignores any
 * event it has already applied, so a replay after a reconnect never doubles a step.
 *
 * Step labels and reasons are server templates filled with hydrated values (never model text),
 * so the UI shows them as they arrive.
 *
 * The browser reads the stream through app/api/runs/[runId]/events/route.ts, which marks it
 * `no-transform`: through the plain /api rewrite, Next gzips the response and the browser gets
 * every event at once when the run ends, so the live checklist never shows.
 */
import { parseAgentResponse, type ApiOptions, type ParsedResponse } from "@/lib/api";

const ULID = "[0-9A-HJKMNP-TV-Z]{26}";
const THREAD_ID = new RegExp(`^thr_${ULID}$`);
const RUN_ID = new RegExp(`^run_${ULID}$`);
const RESPONSE_ID = new RegExp(`^rsp_${ULID}$`);
const TIMEOUT_MS = 10_000;

export const isThreadId = (v: unknown): v is string => typeof v === "string" && THREAD_ID.test(v);
export const isRunId = (v: unknown): v is string => typeof v === "string" && RUN_ID.test(v);
export const isResponseId = (v: unknown): v is string => typeof v === "string" && RESPONSE_ID.test(v);

async function post(path: string, body: unknown, { fetchImpl = fetch, baseUrl = "" }: ApiOptions) {
  try {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      method: "POST",
      cache: "no-store",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!response.ok) return null;
    return (await response.json()) as unknown;
  } catch {
    return null;
  }
}

/** Start a conversation thread for the session's profile. */
export async function createThread(options: ApiOptions = {}): Promise<string | null> {
  const body = await post("/api/threads", {}, options);
  const id = (body as { thread_id?: unknown } | null)?.thread_id;
  return isThreadId(id) ? id : null;
}

export type StructuredAction = { kind: string; payload: unknown; action_id?: string };

/** Post a question (or a structured follow-up). Idempotent on `clientMsgId`. */
export async function postMessage(
  threadId: string,
  text: string,
  clientMsgId: string,
  { action, ...options }: ApiOptions & { action?: StructuredAction } = {},
): Promise<string | null> {
  if (!isThreadId(threadId)) return null;
  const body = await post(
    `/api/threads/${encodeURIComponent(threadId)}/messages`,
    { text, client_msg_id: clientMsgId, ...(action ? { action } : {}) },
    options,
  );
  const id = (body as { run_id?: unknown } | null)?.run_id;
  return isRunId(id) ? id : null;
}

export function runEventsUrl(runId: string, lastEventId?: string | null, baseUrl = ""): string {
  const suffix = lastEventId ? `?last_event_id=${encodeURIComponent(lastEventId)}` : "";
  return `${baseUrl}/api/runs/${encodeURIComponent(runId)}/events${suffix}`;
}

// ---------------------------------------------------------------------------------------------
// Events

export const RUN_EVENT_TYPES = ["run.started", "step", "clarify", "answer", "error", "heartbeat"] as const;
export type RunEventType = (typeof RUN_EVENT_TYPES)[number];

export type StepStatus = "started" | "done" | "rejected" | "revised" | "skipped" | "cached";
const STEP_STATUSES: readonly StepStatus[] = ["started", "done", "rejected", "revised", "skipped", "cached"];

export type RunStep = {
  step_id: string;
  agent: string;
  label: string;
  status: StepStatus;
  reason: string | null;
  /** When the server logged the step (ISO), if it says. */
  at: string | null;
};

export type ClarifyOption = { label: string; question: string };

export type RunEvent =
  | { type: "run.started"; id: string | null; standaloneQuestion: string | null; at: string | null }
  | { type: "step"; id: string | null; step: RunStep }
  | { type: "clarify"; id: string | null; question: string; options: ClarifyOption[] }
  | { type: "answer"; id: string | null; responseId: string; snapshot: unknown }
  | {
      type: "error";
      id: string | null;
      code: string;
      retryable: boolean;
      partialResponseId: string | null;
    }
  | { type: "heartbeat"; id: string | null };

const str = (v: unknown): string | null => (typeof v === "string" && v.length > 0 ? v : null);

function parseOptions(raw: unknown): ClarifyOption[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((o): ClarifyOption[] => {
    if (typeof o === "string") return o ? [{ label: o, question: o }] : [];
    if (typeof o !== "object" || o === null) return [];
    const r = o as Record<string, unknown>;
    // An AskAction from the ClarifyingQuestion block, or a plain {label, question}.
    const payload = (r.payload ?? {}) as Record<string, unknown>;
    const label = str(r.label);
    const question = str(r.question) ?? str(payload.question) ?? label;
    return label && question ? [{ label, question }] : [];
  });
}

/** Turns one SSE message into a typed event. Anything malformed is dropped (null). */
export function parseRunEvent(type: string, data: string, id?: string | null): RunEvent | null {
  const eventId = id ? String(id) : null;
  if (type === "heartbeat") return { type, id: eventId };
  let body: Record<string, unknown>;
  try {
    const parsed: unknown = data ? JSON.parse(data) : {};
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
    body = parsed as Record<string, unknown>;
  } catch {
    return null;
  }
  switch (type) {
    case "run.started":
      return { type, id: eventId, standaloneQuestion: str(body.standalone_question), at: str(body.at) };
    case "step": {
      const status = body.status as StepStatus;
      const stepId = str(body.step_id);
      const label = str(body.label);
      if (!stepId || !label || !STEP_STATUSES.includes(status)) return null;
      return {
        type,
        id: eventId,
        step: {
          step_id: stepId,
          agent: str(body.agent) ?? "coordinator",
          label,
          status,
          reason: str(body.reason),
          at: str(body.at) ?? str(body.finished_at) ?? str(body.started_at),
        },
      };
    }
    case "clarify": {
      const question = str(body.question);
      const options = parseOptions(body.options);
      if (!question || options.length === 0) return null;
      return { type, id: eventId, question, options: options.slice(0, 4) };
    }
    case "answer": {
      const responseId = str(body.rsp_id) ?? str(body.response_id);
      if (!isResponseId(responseId)) return null;
      return { type, id: eventId, responseId, snapshot: body.snapshot ?? null };
    }
    case "error":
      return {
        type,
        id: eventId,
        code: str(body.code) ?? "unknown",
        retryable: body.retryable === true,
        partialResponseId: isResponseId(body.partial_rsp_id) ? body.partial_rsp_id : null,
      };
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------------------------
// Run state

export type RunPhase = "posting" | "running" | "answered" | "clarify" | "error";

export type RunState = {
  runId: string | null;
  phase: RunPhase;
  /** The question as the Understand step rewrote it ("Checking: …"). */
  standaloneQuestion: string | null;
  steps: RunStep[];
  startedAt: string | null;
  lastEventId: string | null;
  answer: { responseId: string; response: ParsedResponse | null } | null;
  clarify: { question: string; options: ClarifyOption[] } | null;
  error: { code: string; retryable: boolean; partialResponseId: string | null } | null;
};

export const initialRun = (runId: string | null = null): RunState => ({
  runId,
  phase: runId ? "running" : "posting",
  standaloneQuestion: null,
  steps: [],
  startedAt: null,
  lastEventId: null,
  answer: null,
  clarify: null,
  error: null,
});

const TERMINAL: RunPhase[] = ["answered", "clarify", "error"];
export const isTerminal = (run: RunState) => TERMINAL.includes(run.phase);

/** True when `id` is not newer than the last applied event (a replay after reconnecting). */
function alreadyApplied(last: string | null, id: string | null): boolean {
  if (!last || !id) return false;
  const a = Number(last);
  const b = Number(id);
  if (Number.isFinite(a) && Number.isFinite(b)) return b <= a;
  return false;
}

/** Applies one event. Pure; replays and duplicate step ids are idempotent. */
export function runReducer(state: RunState, event: RunEvent): RunState {
  if (alreadyApplied(state.lastEventId, event.id)) return state;
  const next: RunState = { ...state, lastEventId: event.id ?? state.lastEventId };
  switch (event.type) {
    case "heartbeat":
      return next;
    case "run.started":
      return {
        ...next,
        phase: isTerminal(state) ? state.phase : "running",
        standaloneQuestion: event.standaloneQuestion ?? state.standaloneQuestion,
        startedAt: state.startedAt ?? event.at,
      };
    case "step": {
      const i = state.steps.findIndex((s) => s.step_id === event.step.step_id);
      const steps =
        i === -1
          ? [...state.steps, event.step]
          : state.steps.map((s, j) => (j === i ? { ...s, ...event.step, at: event.step.at ?? s.at } : s));
      return {
        ...next,
        phase: isTerminal(state) ? state.phase : "running",
        steps,
        startedAt: state.startedAt ?? event.step.at,
      };
    }
    case "clarify":
      return { ...next, phase: "clarify", clarify: { question: event.question, options: event.options } };
    case "answer":
      return {
        ...next,
        phase: "answered",
        answer: { responseId: event.responseId, response: parseAgentResponse(event.snapshot) },
      };
    case "error":
      return {
        ...next,
        phase: "error",
        error: { code: event.code, retryable: event.retryable, partialResponseId: event.partialResponseId },
      };
  }
}

// ---------------------------------------------------------------------------------------------
// Following a run

/** The subset of EventSource the follower needs (a fake in tests). */
export type EventSourceLike = {
  readonly readyState: number;
  addEventListener(type: string, listener: (event: Event) => void): void;
  close(): void;
};
export type EventSourceFactory = (url: string) => EventSourceLike;

const CLOSED = 2;

/**
 * Follows a run's events until a terminal event, calling `onEvent` for each. The browser
 * reconnects by itself (with Last-Event-ID); if it gives up, this reopens the stream once from
 * the last applied event id. Returns a stop function.
 */
export function followRun(
  runId: string,
  onEvent: (event: RunEvent) => void,
  {
    open = (url) => new EventSource(url, { withCredentials: true }),
    onLost,
    baseUrl = "",
    maxReopens = 2,
  }: { open?: EventSourceFactory; onLost?: () => void; baseUrl?: string; maxReopens?: number } = {},
): () => void {
  let source: EventSourceLike | null = null;
  let stopped = false;
  let lastId: string | null = null;
  let reopens = 0;

  const stop = () => {
    stopped = true;
    source?.close();
  };

  const connect = () => {
    const es = open(runEventsUrl(runId, lastId, baseUrl));
    source = es;
    for (const type of RUN_EVENT_TYPES) {
      es.addEventListener(type, (raw) => {
        // An SSE "error" event and a connection error share the listener; only the former has data.
        if (!(typeof MessageEvent !== "undefined" && raw instanceof MessageEvent) || typeof raw.data !== "string") {
          if (type === "error" && !stopped && es.readyState === CLOSED) {
            if (reopens < maxReopens) {
              reopens += 1;
              connect();
            } else {
              onLost?.();
            }
          }
          return;
        }
        const event = parseRunEvent(type, raw.data, raw.lastEventId || null);
        if (!event) return;
        if (event.id) lastId = event.id;
        onEvent(event);
        if (event.type === "answer" || event.type === "clarify" || event.type === "error") stop();
      });
    }
  };

  connect();
  return stop;
}

/** A fresh idempotency key for one question. */
export function newClientMsgId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
}

// ---------------------------------------------------------------------------------------------
// Stored threads (GET /api/threads, GET /api/threads/{id})

export type ThreadSummary = { thread_id: string; title: string; created_at: string };
export type ThreadMessage = {
  message_id: string;
  role: "user" | "assistant";
  text: string;
  standalone_question: string | null;
  run_id: string | null;
  response_id: string | null;
  created_at: string;
};
export type ThreadDetail = { thread_id: string; title: string; messages: ThreadMessage[] };

async function get(path: string, { fetchImpl = fetch, baseUrl = "" }: ApiOptions = {}): Promise<unknown> {
  try {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      cache: "no-store",
      credentials: "include",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    return response.ok ? ((await response.json()) as unknown) : null;
  } catch {
    return null;
  }
}

function isSummary(v: unknown): v is ThreadSummary {
  const t = v as Record<string, unknown> | null;
  return !!t && isThreadId(t.thread_id) && typeof t.title === "string" && typeof t.created_at === "string";
}

/** The profile's conversations, newest first; null if the list can't be read. */
export async function fetchThreads(options: ApiOptions = {}): Promise<ThreadSummary[] | null> {
  const body = (await get("/api/threads", options)) as { threads?: unknown } | null;
  return Array.isArray(body?.threads) ? body.threads.filter(isSummary) : null;
}

/** One conversation with its messages (answers are read separately as snapshots). */
export async function fetchThread(threadId: string, options: ApiOptions = {}): Promise<ThreadDetail | null> {
  if (!isThreadId(threadId)) return null;
  const body = (await get(`/api/threads/${encodeURIComponent(threadId)}`, options)) as Record<string, unknown> | null;
  if (!body || !isThreadId(body.thread_id) || !Array.isArray(body.messages)) return null;
  const messages = body.messages.flatMap((raw): ThreadMessage[] => {
    const m = raw as Record<string, unknown>;
    if (typeof m?.message_id !== "string" || (m.role !== "user" && m.role !== "assistant") || typeof m.text !== "string") return [];
    return [
      {
        message_id: m.message_id,
        role: m.role,
        text: m.text,
        standalone_question: str(m.standalone_question),
        run_id: isRunId(m.run_id) ? m.run_id : null,
        response_id: isResponseId(m.response_id) ? m.response_id : null,
        created_at: str(m.created_at) ?? new Date(0).toISOString(),
      },
    ];
  });
  return { thread_id: body.thread_id, title: typeof body.title === "string" ? body.title : "", messages };
}

// ---------------------------------------------------------------------------------------------
// AI status (GET /api/ai-status): whether model-written answers are available right now.

export type AiStatus = { status: "ok" | "degraded" | "unavailable"; message: string | null };
export const AI_STATUS_POLL_MS = 120_000;

export async function fetchAiStatus(options: ApiOptions = {}): Promise<AiStatus | null> {
  const body = (await get("/api/ai-status", options)) as Record<string, unknown> | null;
  const s = body?.status;
  if (s !== "ok" && s !== "degraded" && s !== "unavailable") return null;
  return { status: s, message: str(body?.message) };
}

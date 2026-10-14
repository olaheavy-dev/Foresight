import { affordabilityResponse, answerScript, clarifyScript, errorScript, uid } from "@/test/workspaceFixtures";
import {
  createThread,
  type EventSourceLike,
  followRun,
  initialRun,
  isTerminal,
  parseRunEvent,
  postMessage,
  type RunEvent,
  runEventsUrl,
  runReducer,
} from "./ask";

const RUN = uid("run", 9);
const THREAD = uid("thr", 9);

function apply(events: RunEvent[]) {
  return events.reduce(runReducer, initialRun(RUN));
}

function scriptEvents(script: { event: string; data: unknown }[]): RunEvent[] {
  return script.map((e, i) => parseRunEvent(e.event, JSON.stringify(e.data), String(i + 1))!);
}

describe("parseRunEvent", () => {
  it("reads every event type the stream sends", () => {
    const events = scriptEvents(answerScript(affordabilityResponse(), "Can I afford a trip in December?"));
    expect(events.every(Boolean)).toBe(true);
    expect(events.map((e) => e.type)).toContain("answer");
    expect(parseRunEvent("heartbeat", "", "3")).toEqual({ type: "heartbeat", id: "3" });
  });

  it("drops malformed or unknown events instead of guessing", () => {
    expect(parseRunEvent("step", "{not json", "1")).toBeNull();
    expect(parseRunEvent("step", JSON.stringify({ step_id: "s", label: "x", status: "exploded" }))).toBeNull();
    expect(parseRunEvent("answer", JSON.stringify({ rsp_id: "rsp_bad" }))).toBeNull();
    expect(parseRunEvent("mystery", "{}")).toBeNull();
    expect(parseRunEvent("clarify", JSON.stringify({ question: "Which?", options: [] }))).toBeNull();
  });

  it("accepts clarify options as AskActions or plain labels", () => {
    const fromBlock = parseRunEvent("clarify", JSON.stringify(clarifyScript()[2].data));
    expect(fromBlock).toMatchObject({
      type: "clarify",
      options: [{ label: "A one-off trip" }, { label: "A monthly getaway" }],
    });
    const plain = parseRunEvent(
      "clarify",
      JSON.stringify({ question: "Which?", options: ["This month", "Next month"] }),
    );
    expect(plain).toMatchObject({
      options: [{ label: "This month", question: "This month" }, { label: "Next month" }],
    });
  });

  it("keeps a partial answer id on errors", () => {
    const e = parseRunEvent(
      "error",
      JSON.stringify({ code: "engine_timeout", retryable: true, partial_rsp_id: uid("rsp", 4) }),
    );
    expect(e).toMatchObject({ type: "error", retryable: true, partialResponseId: uid("rsp", 4) });
  });
});

describe("runReducer", () => {
  it("builds the step checklist and ends with a validated answer", () => {
    const state = apply(scriptEvents(answerScript(affordabilityResponse(), "Can I afford a trip in December?")));
    expect(state.phase).toBe("answered");
    expect(isTerminal(state)).toBe(true);
    expect(state.standaloneQuestion).toBe("Can I afford a trip in December?");
    // "started" then "done" for the same step id updates one row, never adds a second.
    expect(state.steps.map((s) => [s.label, s.status])).toEqual([
      ["Understood your question", "done"],
      ["Read your transactions", "done"],
      ["Built your forecast", "done"],
      ["Verifier rejected a draft", "rejected"],
      ["Revised: pay after 27 Nov", "revised"],
      ["Checked", "done"],
    ]);
    expect(state.steps[3].reason).toMatch(/below your buffer/);
    expect(state.answer?.response?.blocks.every((b) => b.ok)).toBe(true);
  });

  it("ignores events replayed after a reconnect", () => {
    const events = scriptEvents(answerScript(affordabilityResponse(), "q"));
    const once = apply(events.slice(0, 5));
    // Reconnecting with Last-Event-ID 3 makes the server resend 4 and 5 before the rest.
    const replayed = [...events.slice(3, 5), ...events.slice(5)].reduce(runReducer, once);
    expect(replayed).toEqual(apply(events));
  });

  it("an invalid answer snapshot is kept as null so the canvas can fetch it again", () => {
    const answer = parseRunEvent("answer", JSON.stringify({ rsp_id: uid("rsp", 1), snapshot: { nope: true } }), "1")!;
    const state = runReducer(initialRun(RUN), answer);
    expect(state.phase).toBe("answered");
    expect(state.answer).toEqual({ responseId: uid("rsp", 1), response: null });
  });

  it("clarify and error are terminal phases", () => {
    expect(apply(scriptEvents(clarifyScript())).phase).toBe("clarify");
    const failed = apply(scriptEvents(errorScript()));
    expect(failed.phase).toBe("error");
    expect(failed.error).toEqual({ code: "engine_timeout", retryable: true, partialResponseId: null });
    // The step that never finished stays "started" (shown as unfinished, not as done).
    expect(failed.steps.at(-1)?.status).toBe("started");
  });
});

class FakeSource implements EventSourceLike {
  readyState = 1;
  listeners = new Map<string, ((e: Event) => void)[]>();
  closed = false;
  constructor(public url: string) {}
  addEventListener(type: string, fn: (e: Event) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  emit(type: string, data: unknown, id: string) {
    const e = new MessageEvent(type, { data: JSON.stringify(data), lastEventId: id });
    for (const fn of this.listeners.get(type) ?? []) fn(e);
  }
  drop() {
    this.readyState = 2;
    for (const fn of this.listeners.get("error") ?? []) fn(new Event("error"));
  }
}

describe("followRun", () => {
  it("reopens the stream from the last event id when the connection is lost, and stops on the answer", () => {
    const sources: FakeSource[] = [];
    const seen: RunEvent[] = [];
    followRun(RUN, (e) => seen.push(e), {
      open: (url) => {
        const s = new FakeSource(url);
        sources.push(s);
        return s;
      },
    });
    const script = answerScript(affordabilityResponse(), "q");
    sources[0].emit(script[0].event, script[0].data, "1");
    sources[0].emit(script[1].event, script[1].data, "2");
    sources[0].drop();
    expect(sources).toHaveLength(2);
    expect(sources[1].url).toBe(`/api/runs/${RUN}/events?last_event_id=2`);
    const last = script.at(-1)!;
    sources[1].emit(last.event, last.data, "9");
    expect(sources[1].closed).toBe(true);
    expect(seen.map((e) => e.type)).toEqual(["run.started", "step", "answer"]);
  });

  it("gives up after a bounded number of reopens and reports the run as lost", () => {
    const sources: FakeSource[] = [];
    const lost = vi.fn();
    followRun(RUN, () => {}, {
      open: (url) => {
        const s = new FakeSource(url);
        sources.push(s);
        return s;
      },
      onLost: lost,
      maxReopens: 1,
    });
    sources[0].drop();
    sources[1].drop();
    expect(sources).toHaveLength(2);
    expect(lost).toHaveBeenCalledOnce();
  });

  it("treats an SSE `error` event (with data) as a run event, not a lost connection", () => {
    const sources: FakeSource[] = [];
    const seen: RunEvent[] = [];
    followRun(RUN, (e) => seen.push(e), {
      open: (url) => {
        const s = new FakeSource(url);
        sources.push(s);
        return s;
      },
    });
    sources[0].emit("error", { code: "engine_timeout", retryable: true }, "4");
    expect(seen).toEqual([expect.objectContaining({ type: "error", code: "engine_timeout" })]);
    expect(sources).toHaveLength(1);
    expect(sources[0].closed).toBe(true);
  });
});

describe("thread and message requests", () => {
  const ok = (body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }));

  it("creates a thread and posts an idempotent message", async () => {
    const f = ok({ thread_id: THREAD });
    expect(await createThread({ fetchImpl: f })).toBe(THREAD);
    const g = ok({ run_id: RUN });
    expect(await postMessage(THREAD, "Hello", "abc", { fetchImpl: g })).toBe(RUN);
    const [url, init] = g.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`/api/threads/${THREAD}/messages`);
    expect(JSON.parse(init.body as string)).toEqual({ text: "Hello", client_msg_id: "abc" });
  });

  it("returns null for failures and malformed ids", async () => {
    expect(await createThread({ fetchImpl: ok({ thread_id: "nope" }) })).toBeNull();
    expect(await postMessage("thr_bad", "x", "y", { fetchImpl: ok({ run_id: RUN }) })).toBeNull();
    const fail = vi.fn(async () => new Response("{}", { status: 503 }));
    expect(await postMessage(THREAD, "x", "y", { fetchImpl: fail })).toBeNull();
  });

  it("builds the events URL", () => {
    expect(runEventsUrl(RUN)).toBe(`/api/runs/${RUN}/events`);
  });
});

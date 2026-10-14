"use client";

/**
 * AI Workspace (IA: Workspace; TASKS: AI Workspace shell). Three regions that scroll on their own
 * inside the viewport: the conversation (threads and messages), the analysis canvas, and the
 * pinned question box, which is visible at every breakpoint.
 *
 * A question creates (or continues) a thread, posts the message with an idempotency key, then
 * follows the run's event stream: the step checklist fills in live, and the answer snapshot
 * replaces it when the Verifier has checked it. Threads are remembered for the browser session
 * (sessionStorage); reopening one reads the stored snapshots, it never re-runs the agents.
 */
import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Icon, type IconName } from "@/components/icons/Icon";
import { NotShipped } from "@/components/ui/NotShipped";
import { fetchResponse, parseAgentResponse, type ParsedResponse } from "@/lib/api";
import {
  AI_STATUS_POLL_MS,
  type AiStatus,
  createThread,
  fetchAiStatus,
  fetchThread,
  fetchThreads,
  followRun,
  initialRun,
  isTerminal,
  newClientMsgId,
  postMessage,
  type RunEvent,
  runReducer,
  type RunState,
  type StructuredAction,
  type ThreadDetail,
} from "@/lib/ask";
import { formatClock } from "@/lib/format";
import type { FollowUpAction } from "@/ui-contracts/types";
import { AnswerCanvas, isRefusal, layoutAnswer, verdictText } from "./AnswerCanvas";
import { BlockEnvProvider, ClarifyCard } from "./blocks";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { StepChecklist } from "./steps";

// ---------------------------------------------------------------------------------------------
// State

export type Turn = {
  id: string; // also the client_msg_id
  question: string;
  askedAt: string;
  run: RunState;
  partial: ParsedResponse | null;
};
export type Thread = { key: string; threadId: string | null; title: string; createdAt: string; turns: Turn[] };
type State = { threads: Thread[]; selected: string | null };

type Action =
  | { type: "hydrate"; threads: Thread[] }
  | { type: "remote"; threads: { threadId: string; title: string; createdAt: string }[] }
  | { type: "turns"; key: string; turns: Turn[] }
  | { type: "select"; key: string | null }
  | { type: "start"; key: string; title: string; turn: Turn; now: string }
  | { type: "thread_id"; key: string; threadId: string }
  | { type: "run_id"; key: string; turnId: string; runId: string }
  | { type: "event"; key: string; turnId: string; event: RunEvent }
  | { type: "response"; key: string; turnId: string; response: ParsedResponse }
  | { type: "partial"; key: string; turnId: string; response: ParsedResponse }
  | { type: "fail"; key: string; turnId: string; code: string; retryable: boolean };

function updateTurn(state: State, key: string, turnId: string, fn: (t: Turn) => Turn): State {
  return {
    ...state,
    threads: state.threads.map((th) =>
      th.key !== key ? th : { ...th, turns: th.turns.map((t) => (t.id === turnId ? fn(t) : t)) },
    ),
  };
}

export function workspaceReducer(state: State, action: Action): State {
  switch (action.type) {
    case "hydrate":
      return { ...state, threads: action.threads };
    case "remote": {
      // Conversations stored on the server that this browser session hasn't opened yet.
      const known = new Set(state.threads.map((t) => t.threadId));
      const added = action.threads
        .filter((t) => !known.has(t.threadId))
        .map((t): Thread => ({
          key: t.threadId,
          threadId: t.threadId,
          title: t.title || "Conversation",
          createdAt: t.createdAt,
          turns: [],
        }));
      const threads = [...state.threads, ...added].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
      return { ...state, threads };
    }
    case "turns":
      return {
        ...state,
        threads: state.threads.map((t) =>
          t.key === action.key && t.turns.length === 0 ? { ...t, turns: action.turns } : t,
        ),
      };
    case "select":
      return { ...state, selected: action.key };
    case "start": {
      const exists = state.threads.some((t) => t.key === action.key);
      const threads = exists
        ? state.threads.map((t) => (t.key === action.key ? { ...t, turns: [...t.turns, action.turn] } : t))
        : [
            { key: action.key, threadId: null, title: action.title, createdAt: action.now, turns: [action.turn] },
            ...state.threads,
          ];
      return { threads, selected: action.key };
    }
    case "thread_id":
      return {
        ...state,
        threads: state.threads.map((t) => (t.key === action.key ? { ...t, threadId: action.threadId } : t)),
      };
    case "run_id":
      return updateTurn(state, action.key, action.turnId, (t) => ({
        ...t,
        run: { ...t.run, runId: action.runId, phase: "running" },
      }));
    case "event":
      return updateTurn(state, action.key, action.turnId, (t) => ({ ...t, run: runReducer(t.run, action.event) }));
    case "response":
      return updateTurn(state, action.key, action.turnId, (t) =>
        t.run.answer ? { ...t, run: { ...t.run, answer: { ...t.run.answer, response: action.response } } } : t,
      );
    case "partial":
      return updateTurn(state, action.key, action.turnId, (t) => ({ ...t, partial: action.response }));
    case "fail":
      return updateTurn(state, action.key, action.turnId, (t) => ({
        ...t,
        run: {
          ...t.run,
          phase: "error",
          error: { code: action.code, retryable: action.retryable, partialResponseId: null },
        },
      }));
  }
}

/** Rebuilds turns from a stored conversation: each user message, then the answer that followed. */
export function turnsFromThread(detail: ThreadDetail): Turn[] {
  const turns: Turn[] = [];
  for (const m of detail.messages) {
    if (m.role === "user") {
      turns.push({
        id: m.message_id,
        question: m.text,
        askedAt: m.created_at,
        partial: null,
        run: { ...initialRun(m.run_id), standaloneQuestion: m.standalone_question },
      });
    } else {
      const t = turns.at(-1);
      if (!t) continue;
      t.run = { ...t.run, runId: t.run.runId ?? m.run_id };
      if (m.response_id) t.run = { ...t.run, phase: "answered", answer: { responseId: m.response_id, response: null } };
    }
  }
  return turns;
}

// What survives a reload: everything except the parsed snapshots, which are re-read by id.
type StoredTurn = Omit<Turn, "run" | "partial"> & { run: Omit<RunState, "answer"> & { responseId: string | null } };
type StoredThread = Omit<Thread, "turns"> & { turns: StoredTurn[] };

const storageKey = (workspaceId: string) => `foresight.workspace.threads.${workspaceId}`;

function toStored(threads: Thread[]): StoredThread[] {
  return threads.slice(0, 20).map((th) => ({
    ...th,
    turns: th.turns.map(({ partial: _partial, run: { answer, ...run }, ...t }) => ({
      ...t,
      run: { ...run, responseId: answer?.responseId ?? null },
    })),
  }));
}

function fromStored(stored: StoredThread[]): Thread[] {
  return stored.map((th) => ({
    ...th,
    turns: th.turns.map(({ run: { responseId, ...run }, ...t }) => ({
      ...t,
      partial: null,
      run: { ...initialRun(run.runId), ...run, answer: responseId ? { responseId, response: null } : null },
    })),
  }));
}

// ---------------------------------------------------------------------------------------------
// Copy

const STARTERS: { icon: IconName; q: string; note: string }[] = [
  { icon: "plane", q: "Can I afford a holiday next month?", note: "Checks timing against your paydays" },
  { icon: "utensils", q: "Why is my spending up?", note: "Compares the last 30 days with a usual month" },
  { icon: "briefcase", q: "What if my salary is late?", note: "Simulates a later payday against your bills" },
  { icon: "calendar", q: "How does next month look?", note: "A quick read of your forecast" },
];

/** While AI answers are paused, the starters point at what still works without them. */
const STILL_WORKS: { icon: IconName; q: string; note: string; href: string | null }[] = [
  { icon: "pulse", q: "See your forecast", note: "Your balance to the next paydays, from the engine", href: "/home" },
  { icon: "sliders", q: "Try a what-if", note: "Decision Lab runs the engine directly", href: "/lab" },
  { icon: "swap", q: "Look through transactions", note: "Search and filter your ledger", href: "/transactions" },
  { icon: "clock", q: "Reopen an earlier answer", note: "Answers you’ve had are stored", href: null },
];

const PAUSED = "AI answers are paused right now. Your forecast and numbers still work.";

const ERRORS: Record<string, string> = {
  ai_unavailable: "AI answers are paused right now.",
  engine_timeout: "The forecast engine didn’t respond.",
  deadline: "This answer took too long to finish.",
  connection_lost: "We lost the connection to this answer.",
  unavailable: "Foresight couldn’t take the question right now.",
  model_unavailable: "AI explanations are unavailable right now.",
  spend_limit: "AI explanations are unavailable right now.",
  budget_exceeded: "This question needed more work than one answer allows.",
};

const errorText = (code: string) => ERRORS[code] ?? "Something went wrong with this answer.";

// ---------------------------------------------------------------------------------------------

export type WorkspaceProps = {
  workspaceId: string;
  firstName: string;
  locale: string;
  timeZone: string;
  currency: string;
  initialQuestion: string | null;
  flags: { auditTrail: boolean; checkedAdvice: boolean; anomalyDetection: boolean };
};

export function Workspace({
  workspaceId,
  firstName,
  locale,
  timeZone,
  currency,
  initialQuestion,
  flags,
}: WorkspaceProps) {
  const [state, dispatch] = useReducer(workspaceReducer, { threads: [], selected: null });
  const [hydrated, setHydrated] = useState(false);
  const [draft, setDraft] = useState("");
  const [convoOpen, setConvoOpen] = useState(false);
  const [evidence, setEvidence] = useState<string | null>(null);
  const [ai, setAi] = useState<AiStatus | null>(null);
  const stops = useRef(new Map<string, () => void>());
  const asked = useRef(false);
  const stateRef = useRef(state);
  stateRef.current = state;

  const thread = state.threads.find((t) => t.key === state.selected) ?? null;
  const turn = thread?.turns.at(-1) ?? null;
  const busy = Boolean(turn && !isTerminal(turn.run));

  // -- following runs -----------------------------------------------------------------------
  const follow = useCallback((key: string, turnId: string, runId: string) => {
    stops.current.get(turnId)?.();
    const stop = followRun(
      runId,
      (event) => {
        dispatch({ type: "event", key, turnId, event });
        if (event.type === "answer" && !parseAgentResponse(event.snapshot)) {
          fetchResponse(event.responseId).then((r) =>
            r
              ? dispatch({ type: "response", key, turnId, response: r })
              : dispatch({ type: "fail", key, turnId, code: "unavailable", retryable: true }),
          );
        }
        if (event.type === "error" && event.code === "ai_unavailable") {
          setAi({ status: "unavailable", message: null });
        }
        if (event.type === "error" && event.partialResponseId) {
          fetchResponse(event.partialResponseId).then((r) =>
            r ? dispatch({ type: "partial", key, turnId, response: r }) : null,
          );
        }
      },
      { onLost: () => dispatch({ type: "fail", key, turnId, code: "connection_lost", retryable: true }) },
    );
    stops.current.set(turnId, stop);
  }, []);

  useEffect(() => {
    const map = stops.current;
    return () => map.forEach((stop) => stop());
  }, []);

  // -- AI status: on load and every two minutes while the Workspace is open --------------------
  useEffect(() => {
    let live = true;
    const check = () =>
      fetchAiStatus().then((s) => {
        if (live) setAi(s);
      });
    void check();
    const timer = window.setInterval(check, AI_STATUS_POLL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);
  const paused = ai?.status === "unavailable";

  // -- session persistence ------------------------------------------------------------------
  useEffect(() => {
    let stored: StoredThread[] = [];
    try {
      stored = JSON.parse(sessionStorage.getItem(storageKey(workspaceId)) ?? "[]") as StoredThread[];
    } catch {
      stored = [];
    }
    const threads = Array.isArray(stored) ? fromStored(stored) : [];
    dispatch({ type: "hydrate", threads });
    const params = new URLSearchParams(window.location.search);
    const wanted = params.get("thread");
    if (wanted && threads.some((t) => t.key === wanted)) dispatch({ type: "select", key: wanted });
    setEvidence(params.get("evidence"));
    // Reopened answers come from their stored snapshots; unfinished runs are followed again.
    for (const th of threads) {
      for (const t of th.turns) {
        if (t.run.answer && !t.run.answer.response) {
          const id = t.run.answer.responseId;
          fetchResponse(id).then((r) =>
            r ? dispatch({ type: "response", key: th.key, turnId: t.id, response: r }) : null,
          );
        } else if (t.run.runId && !isTerminal(t.run)) {
          follow(th.key, t.id, t.run.runId);
        }
      }
    }
    setHydrated(true);
    // Conversations from earlier sessions come from the server; their answers load when opened.
    fetchThreads().then((list) => {
      if (list)
        dispatch({
          type: "remote",
          threads: list.map((t) => ({ threadId: t.thread_id, title: t.title, createdAt: t.created_at })),
        });
    });
  }, [workspaceId, follow]);

  // Opening a conversation this session hasn't seen: read its messages, then its stored answers.
  const selectedEmpty = thread && thread.turns.length === 0 && thread.threadId ? thread : null;
  useEffect(() => {
    if (!selectedEmpty?.threadId) return;
    const { key, threadId } = selectedEmpty;
    let live = true;
    fetchThread(threadId).then((detail) => {
      if (!live || !detail) return;
      const turns = turnsFromThread(detail);
      dispatch({ type: "turns", key, turns });
      for (const t of turns) {
        if (t.run.answer) {
          fetchResponse(t.run.answer.responseId).then((r) =>
            r ? dispatch({ type: "response", key, turnId: t.id, response: r }) : null,
          );
        } else if (t.run.runId) {
          follow(key, t.id, t.run.runId);
        }
      }
    });
    return () => {
      live = false;
    };
  }, [selectedEmpty?.key, selectedEmpty?.threadId, follow]);

  useEffect(() => {
    if (!hydrated) return;
    try {
      sessionStorage.setItem(storageKey(workspaceId), JSON.stringify(toStored(state.threads)));
    } catch {
      // Storage full or disabled: the conversation still works, it just won't survive a reload.
    }
  }, [state.threads, hydrated, workspaceId]);

  // Keep ?thread= and ?evidence= in the address bar so a view is linkable (no server round trip).
  useEffect(() => {
    if (!hydrated) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("q");
    if (state.selected) url.searchParams.set("thread", state.selected);
    else url.searchParams.delete("thread");
    if (evidence) url.searchParams.set("evidence", evidence);
    else url.searchParams.delete("evidence");
    window.history.replaceState(window.history.state, "", url);
  }, [state.selected, evidence, hydrated]);

  // -- asking -------------------------------------------------------------------------------
  const ask = useCallback(
    async (text: string, { newThread = false, action }: { newThread?: boolean; action?: StructuredAction } = {}) => {
      const question = text.trim().slice(0, 2000);
      if (!question) return;
      const current = stateRef.current.threads.find((t) => t.key === stateRef.current.selected);
      const last = current?.turns.at(-1);
      if (last && !isTerminal(last.run)) return;
      const th = !newThread && current ? current : null;
      const key = th?.key ?? `t_${newClientMsgId()}`;
      const now = new Date().toISOString();
      const turnId = newClientMsgId();
      dispatch({
        type: "start",
        key,
        title: question.length > 60 ? `${question.slice(0, 57)}…` : question,
        now,
        turn: { id: turnId, question, askedAt: now, run: initialRun(), partial: null },
      });
      setDraft("");
      let threadId = th?.threadId ?? null;
      if (!threadId) {
        threadId = await createThread();
        if (!threadId) return dispatch({ type: "fail", key, turnId, code: "unavailable", retryable: true });
        dispatch({ type: "thread_id", key, threadId });
      }
      const runId = await postMessage(threadId, question, turnId, { action });
      if (!runId) return dispatch({ type: "fail", key, turnId, code: "unavailable", retryable: true });
      dispatch({ type: "run_id", key, turnId, runId });
      follow(key, turnId, runId);
    },
    [follow],
  );

  useEffect(() => {
    if (!hydrated || asked.current || !initialQuestion) return;
    asked.current = true;
    void ask(initialQuestion, { newThread: true });
  }, [hydrated, initialQuestion, ask]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void ask(draft);
  };

  const followUp = (f: FollowUpAction) => {
    if (f.kind === "ask") void ask(f.payload.question);
    else if (f.kind === "open_evidence") setEvidence(f.payload.ref);
  };

  // -- derived ------------------------------------------------------------------------------
  const answer = turn?.run.answer?.response ?? null;
  const laid = useMemo(() => (answer ? layoutAnswer(answer) : null), [answer]);
  const chips = (answer?.follow_ups ?? []).filter(
    (f) => f.kind === "ask" || (f.kind === "open_evidence" && flags.auditTrail),
  );
  const jump: { id: string; label: string; icon: IconName }[] = laid
    ? [
        ...(laid.tabs.recommendation.length
          ? [{ id: "recommendation", label: "Compare", icon: "scale" as IconName }]
          : []),
        ...(laid.tabs.details.length ? [{ id: "details", label: "Details", icon: "pulse" as IconName }] : []),
        { id: "checked", label: "Checks", icon: "checkcircle" as IconName },
        ...(laid.tabs.transactions.length
          ? [{ id: "transactions", label: "Transactions", icon: "list" as IconName }]
          : []),
      ]
    : [];

  const env = {
    currency: answer?.currency ?? currency,
    locale,
    timeZone,
    ask: (q: string) => void ask(q),
    checkedAdvice: flags.checkedAdvice,
  };

  return (
    <BlockEnvProvider value={env}>
      <div className="ws-body" data-thread={thread ? "open" : "new"}>
        {/* ======== Conversation ======== */}
        <section className="convo" data-collapsed={!convoOpen} aria-label="Conversation">
          <button
            type="button"
            className="convo-toggle"
            aria-expanded={convoOpen}
            aria-controls="convo-body"
            onClick={() => setConvoOpen((o) => !o)}
          >
            <span className="icon-chip sm">
              <Icon name="sparkles" />
            </span>
            <span className="q">{thread ? thread.title : "New question"}</span>
            <span className="xs faint">Conversation</span>
            <Icon name="chevdown" className="chev" />
          </button>
          <div className="convo-body" id="convo-body">
            <div className="assistant-head">
              <BotAvatar />
              <div>
                <h2>Foresight Assistant</h2>
                <p>Your financial intelligence partner</p>
              </div>
            </div>

            <div className="recent">
              <div className="recent-head">
                <h3 id="recent-h">Recent</h3>
                <button
                  type="button"
                  className="new-q"
                  aria-current={!thread ? "true" : undefined}
                  onClick={() => dispatch({ type: "select", key: null })}
                >
                  <Icon name="plus" />
                  New question
                </button>
              </div>
              {state.threads.length ? (
                <ul className="threads" aria-labelledby="recent-h">
                  {state.threads.map((t) => (
                    <li key={t.key}>
                      <button
                        type="button"
                        aria-current={t.key === state.selected ? "true" : undefined}
                        onClick={() => dispatch({ type: "select", key: t.key })}
                      >
                        <Icon name="sparkles" />
                        <span className="t">{t.title}</span>
                        <span className="time">{formatClock(t.createdAt, locale, timeZone).slice(0, 5)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="xs faint">Your questions this session appear here.</p>
              )}
            </div>

            {thread ? (
              <div className="thread">
                {thread.turns.map((t) => (
                  <TurnBubbles key={t.id} turn={t} locale={locale} timeZone={timeZone} />
                ))}
                {jump.length && turn?.run.phase === "answered" && !isRefusal(answer!) ? (
                  <nav className="jump" aria-label="Go deeper">
                    {jump.map((j) => (
                      <a key={j.id} href={`#${j.id}`}>
                        <Icon name={j.icon} />
                        {j.label}
                      </a>
                    ))}
                  </nav>
                ) : null}
              </div>
            ) : (
              <div className="thread">
                <div className="msg-bot">
                  <BotAvatar mini />
                  <div className="bubble">
                    <p>
                      Hi {firstName}. Ask about a decision, a change in your spending or the months ahead. I’ll show you
                      what was checked before you see the answer.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* ======== Pinned question box ======== */}
        <div className="dock">
          {paused ? (
            <div className="ai-notice" role="status">
              <Icon name="info" />
              <div>
                <p>{PAUSED}</p>
                <p className="sub">You can still ask; a free-text question may not get an AI explanation.</p>
                <p className="links">
                  <Link href="/home">Your forecast</Link>
                  <Link href="/lab">Decision Lab</Link>
                  <Link href="/transactions">Transactions</Link>
                </p>
              </div>
            </div>
          ) : ai?.status === "degraded" ? (
            <p className="ai-notice soft" role="status">
              <Icon name="info" />
              <span>AI answers may be slower than usual. Numbers are unaffected.</span>
            </p>
          ) : null}
          {chips.length && !paused ? (
            <div className="try" role="group" aria-label="Try asking">
              <div className="chips">
                {chips.map((f) => (
                  <button key={f.action_id} type="button" className="chip" disabled={busy} onClick={() => followUp(f)}>
                    {f.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <form className="composer" onSubmit={submit}>
            <Icon name="sparkles" />
            <label className="sr-only" htmlFor="ws-ask">
              Ask a question
            </label>
            <input
              id="ws-ask"
              type="text"
              autoComplete="off"
              maxLength={2000}
              placeholder={thread ? "Ask a follow-up question…" : "Ask about your money…"}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <button
              className="send"
              type="submit"
              aria-label={busy ? "Working on your last question" : "Send"}
              disabled={busy || !draft.trim()}
            >
              <Icon name="send" />
            </button>
          </form>
        </div>

        {/* ======== Analysis canvas ======== */}
        <section className="canvas" aria-label="Analysis" aria-busy={busy} tabIndex={0}>
          {!thread || !turn ? (
            <Welcome
              paused={paused}
              onAsk={(q) => void ask(q, { newThread: true })}
              onEarlier={() => {
                setConvoOpen(true);
                document.querySelector<HTMLButtonElement>(".ws-body .threads button")?.focus();
              }}
            />
          ) : turn.run.phase === "answered" ? (
            answer && answer.intent === "spending_question" && !flags.anomalyDetection ? (
              <div className="analysis">
                <CanvasTop question={turn.question} />
                <NotShipped
                  title="Spending analysis"
                  detail="Spending answers appear here once behaviour and anomaly detection passes its evaluation."
                />
              </div>
            ) : answer ? (
              <AnswerCanvas
                response={answer}
                liveSteps={turn.run.steps}
                locale={locale}
                timeZone={timeZone}
                auditTrail={flags.auditTrail}
                openEvidence={setEvidence}
              />
            ) : (
              <Working turn={turn} locale={locale} timeZone={timeZone} fetching />
            )
          ) : turn.run.phase === "clarify" && turn.run.clarify ? (
            <div className="analysis">
              <CanvasTop question={turn.question} />
              <ClarifyCard
                question={turn.run.clarify.question}
                options={turn.run.clarify.options}
                onPick={(q) => void ask(q)}
              />
            </div>
          ) : turn.run.phase === "error" && turn.run.error ? (
            <div className="analysis">
              <CanvasTop question={turn.question} />
              <section className="card ws-card error-card" role="alert">
                <div className="card-head">
                  <span className="icon-chip sm amber">
                    <Icon name="alert" />
                  </span>
                  <div>
                    <h2 className="card-title">{errorText(turn.run.error.code)}</h2>
                    <p className="card-sub">
                      {turn.run.error.code === "ai_unavailable"
                        ? "Your forecast and numbers still work. Try the Decision Lab for a what-if, or ask again later."
                        : turn.partial
                          ? "Part of the answer was checked before it stopped; it’s shown below."
                          : "No figures were shown, because none were checked. Your question is kept."}
                    </p>
                  </div>
                </div>
                <StepChecklist
                  steps={turn.run.steps}
                  locale={locale}
                  timeZone={timeZone}
                  label="Steps before it stopped"
                />
                {turn.run.error.retryable ? (
                  <div className="btns">
                    <button type="button" className="btn primary" onClick={() => void ask(turn.question)}>
                      Try again
                    </button>
                  </div>
                ) : null}
              </section>
              {turn.partial ? (
                <AnswerCanvas
                  response={turn.partial}
                  liveSteps={[]}
                  locale={locale}
                  timeZone={timeZone}
                  auditTrail={flags.auditTrail}
                  openEvidence={setEvidence}
                  partial
                />
              ) : null}
            </div>
          ) : (
            <Working turn={turn} locale={locale} timeZone={timeZone} />
          )}
        </section>
      </div>

      {evidence && flags.auditTrail ? (
        <EvidenceDrawer
          refId={evidence}
          response={answer ?? turn?.partial ?? null}
          locale={locale}
          timeZone={timeZone}
          onClose={() => setEvidence(null)}
        />
      ) : null}
    </BlockEnvProvider>
  );
}

// ---------------------------------------------------------------------------------------------

function BotAvatar({ mini = false }: { mini?: boolean }) {
  return (
    <span className={mini ? "bot-avatar mini" : "bot-avatar"} aria-hidden="true">
      <svg viewBox="0 0 32 32">
        <path d="M7 11.5 27 5.5l-2.4 6.2L4.6 17.7Z" />
        <path d="M5.6 19.4 21.8 14.6l-2.2 5.6L3.4 25Z" />
        <path d="M4.4 26.6 13.8 23.8l-1.6 4L2.8 30.6Z" />
      </svg>
    </span>
  );
}

function CanvasTop({ question, working = false }: { question: string; working?: boolean }) {
  return (
    <div className="canvas-top">
      <span className="ai">
        <Icon name="sparkles" />
        AI Analysis
      </span>
      <span className="done">{working ? `Working on “${question}”` : `“${question}”`}</span>
    </div>
  );
}

function TurnBubbles({ turn, locale, timeZone }: { turn: Turn; locale: string; timeZone: string }) {
  const r = turn.run;
  const time = formatClock(turn.askedAt, locale, timeZone).slice(0, 5);
  let bot: string;
  let stamp = "";
  if (r.phase === "answered") {
    bot = (r.answer?.response && verdictText(r.answer.response)) ?? "Here’s what I found.";
    stamp =
      r.answer?.response && !isRefusal(r.answer.response)
        ? "numbers from the forecast engine, checked before you saw them"
        : "";
  } else if (r.phase === "clarify") bot = r.clarify?.question ?? "Which did you mean?";
  else if (r.phase === "error") bot = errorText(r.error?.code ?? "");
  else bot = r.standaloneQuestion ? `Checking: ${r.standaloneQuestion}` : "Working on it…";
  return (
    <>
      <div className="msg-user">
        <div className="bubble">{turn.question}</div>
        <div className="stamp">{time}</div>
      </div>
      <div className="msg-bot">
        <BotAvatar mini />
        <div>
          <div className="bubble" aria-live={isTerminal(r) ? undefined : "polite"}>
            <p>{bot}</p>
          </div>
          {stamp ? <div className="stamp">{stamp}</div> : null}
        </div>
      </div>
    </>
  );
}

function Working({
  turn,
  locale,
  timeZone,
  fetching = false,
}: {
  turn: Turn;
  locale: string;
  timeZone: string;
  fetching?: boolean;
}) {
  const r = turn.run;
  return (
    <div className="analysis loading-view">
      <CanvasTop question={turn.question} working />
      <section className="run" aria-labelledby="run-h" aria-live="polite">
        <h2 className="run-h" id="run-h">
          {fetching ? "Opening the checked answer" : "Checking before you see it"}
        </h2>
        <p className="run-sub">
          {r.standaloneQuestion ? `Checking: ${r.standaloneQuestion}` : r.runId ? "Started" : "Sending your question"}
          {r.startedAt ? ` · ${formatClock(r.startedAt, locale, timeZone)}` : ""}
        </p>
        <StepChecklist steps={r.steps} locale={locale} timeZone={timeZone} />
      </section>
      <p className="xs faint">Numbers appear once the Verifier has checked them.</p>
      <div aria-hidden="true">
        <div className="skel h1" />
        <div className="skel line" />
        <div className="skel-grid">
          <div className="skel block short" />
          <div className="skel block short" />
          <div className="skel block short" />
        </div>
      </div>
    </div>
  );
}

function Welcome({ onAsk, paused, onEarlier }: { onAsk: (q: string) => void; paused: boolean; onEarlier: () => void }) {
  return (
    <div className="welcome">
      <div className="welcome-inner">
        <BotAvatar />
        <h1 className="welcome-h serif">Ask anything about your money.</h1>
        <p className="welcome-sub">
          Answers come from your transactions and the forecast engine — every number is computed, then checked.
        </p>
        {paused ? <p className="welcome-paused">{PAUSED}</p> : null}
        <ul className="starters" aria-label={paused ? "What still works" : "Start with a question"}>
          {paused
            ? STILL_WORKS.map((s) => (
                <li key={s.q}>
                  {s.href ? (
                    <Link className="starter" href={s.href}>
                      <span className="icon-chip sm">
                        <Icon name={s.icon} />
                      </span>
                      <span className="s-q">{s.q}</span>
                      <span className="s-n">{s.note}</span>
                      <Icon name="arrowright" className="s-go" />
                    </Link>
                  ) : (
                    <button type="button" className="starter" onClick={onEarlier}>
                      <span className="icon-chip sm">
                        <Icon name={s.icon} />
                      </span>
                      <span className="s-q">{s.q}</span>
                      <span className="s-n">{s.note}</span>
                      <Icon name="arrowright" className="s-go" />
                    </button>
                  )}
                </li>
              ))
            : STARTERS.map((s) => (
                <li key={s.q}>
                  <button type="button" className="starter" onClick={() => onAsk(s.q)}>
                    <span className="icon-chip sm">
                      <Icon name={s.icon} />
                    </span>
                    <span className="s-q">{s.q}</span>
                    <span className="s-n">{s.note}</span>
                    <Icon name="arrowright" className="s-go" />
                  </button>
                </li>
              ))}
        </ul>
        <p className="disclaimer">
          <Icon name="info" />
          Guidance, not regulated financial advice.
        </p>
      </div>
    </div>
  );
}

/**
 * Activity (docs/05 "Traces stay in-house"): each agent run is a trace and its steps are the
 * spans — which agent ran, on which model, how long it took, what it cost and how the Verifier
 * judged the advice. Metadata only: no prompt or model output is shown. Below, the profile's
 * hash-chained audit log in words.
 */
import { Icon } from "@/components/icons/Icon";
import { Badge, CardHead } from "@/components/ui/primitives";
import type { ActivityFeed as Feed, ActivityRun } from "@/ui-contracts/types";

const WORKFLOW: Record<string, string> = {
  conversation: "Answered a question",
  recommendation: "Advised on a question",
  scenario: "Ran a what-if",
  ingestion: "Checked an import",
  risk_detection: "Proactive check",
  advice_followup: "Finished checking advice",
};
const TRIGGER: Record<string, string> = {
  user: "You asked",
  event: "After a change",
  cron: "Scheduled",
  eval: "Evaluation",
};

const seconds = (ms: number | null | undefined) => (ms == null ? "—" : `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`);
// Estimated: Mesh-reported usage × catalogue prices, not a bill (docs/00 §7, owner decision 13 Oct).
const dollars = (usd: number | null | undefined) =>
  usd == null ? "—" : `about $${usd < 0.01 ? usd.toFixed(4) : usd.toFixed(3)}`;
const when = (iso: string, locale: string, timeZone: string) =>
  new Date(iso).toLocaleString(locale, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  });

function Run({ run, locale, timeZone }: { run: ActivityRun; locale: string; timeZone: string }) {
  const steps = run.steps ?? [];
  const tone =
    run.status === "succeeded" ? (run.partial ? "amber" : "green") : run.status === "running" ? "blue" : "red";
  return (
    // Linked from Home's "How it was checked" (`/activity#run-…`); OpenLinkedRun opens it.
    <li className="act-run" id={`run-${run.run_id}`}>
      <details>
        <summary>
          <span className="act-run-main">
            <span className="act-run-title">{WORKFLOW[run.workflow] ?? "Background run"}</span>
            <span className="act-run-sub">
              {TRIGGER[run.trigger] ?? run.trigger} · {when(run.started_at, locale, timeZone)}
              {run.question ? ` · “${run.question}”` : ""}
            </span>
          </span>
          <span className="act-run-facts">
            <Badge tone={tone}>{run.partial ? "Partial" : run.status === "succeeded" ? "Done" : run.status}</Badge>
            {(run.approved ?? 0) + (run.rejected ?? 0) > 0 ? (
              run.approved ? (
                <Badge tone="green" icon="checkcircle">
                  {run.approved} checked{run.rejected ? ` · ${run.rejected} rejected` : ""}
                </Badge>
              ) : (
                // Nothing passed the Verifier: a caution, never the green of a positive outcome.
                <Badge tone="amber" icon="alert">
                  None passed · {run.rejected} rejected
                </Badge>
              )
            ) : null}
            <span className="num">{seconds(run.duration_ms)}</span>
            <span className="num">{dollars(run.cost_usd)}</span>
          </span>
        </summary>
        <div className="scroll-x" tabIndex={0} role="region" aria-label="Steps of this run">
          <table className="data act-steps">
            <caption className="sr-only">Steps: agent, model, time, tokens and estimated cost</caption>
            <thead>
              <tr>
                <th scope="col">Step</th>
                <th scope="col">Agent</th>
                <th scope="col">Model</th>
                <th scope="col" className="num">
                  Time
                </th>
                <th scope="col" className="num">
                  Tokens in / out
                </th>
                <th scope="col" className="num">
                  Est. cost
                </th>
              </tr>
            </thead>
            <tbody>
              {steps.map((s) => (
                <tr key={s.seq}>
                  <td className="lead">
                    {s.label || s.node}
                    {s.status !== "ok" ? <span className="act-status"> · {s.status}</span> : null}
                    {s.cached ? <span className="act-status"> · cached</span> : null}
                  </td>
                  <td data-label="Agent">{s.agent}</td>
                  <td data-label="Model">{s.model ?? (s.kind === "llm" ? "—" : "no model")}</td>
                  <td data-label="Time" className="num">
                    {seconds(s.latency_ms)}
                  </td>
                  <td data-label="Tokens in / out" className="num">
                    {s.kind === "llm" ? `${s.tokens_in} / ${s.tokens_out}` : "—"}
                  </td>
                  <td data-label="Est. cost" className="num">
                    {dollars(s.cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="act-note">
          {run.llm_calls} model call{run.llm_calls === 1 ? "" : "s"} through Mesh · {run.tokens_in} tokens in,{" "}
          {run.tokens_out} out
          {run.revisions ? ` · revised ${run.revisions === 1 ? "once" : `${run.revisions} times`} before showing` : ""}.
        </p>
      </details>
    </li>
  );
}

export function ActivityFeed({ feed, locale, timeZone }: { feed: Feed; locale: string; timeZone: string }) {
  const runs = feed.runs ?? [];
  const events = feed.events ?? [];
  return (
    <div className="activity">
      <section className="card act-card" aria-labelledby="runs-h">
        <CardHead
          icon="pulse"
          title="Agent runs"
          titleId="runs-h"
          sub="Each run with its steps: which agent ran, on which model, how long it took and its estimated cost."
        />
        {runs.length ? (
          <ul className="act-runs">
            {runs.map((r) => (
              <Run key={r.run_id} run={r} locale={locale} timeZone={timeZone} />
            ))}
          </ul>
        ) : (
          <p className="act-empty">No agent runs yet. Ask a question, import a statement or run a proactive check.</p>
        )}
      </section>

      <section className="card act-card" aria-labelledby="changes-h">
        <CardHead
          icon="shield"
          title="Changes"
          titleId="changes-h"
          sub="The latest changes to this profile, newest first."
        />
        <p className="act-chain">
          {feed.audit_chain_intact ? (
            <Badge tone="green" icon="checkcircle">
              Audit chain intact · {feed.audit_events} entries
            </Badge>
          ) : (
            <Badge tone="red" icon="alert">
              Audit chain broken
            </Badge>
          )}
          <span>Each entry is hashed with the one before, so a change to an earlier entry would show.</span>
        </p>
        {events.length ? (
          <ol className="act-events">
            {events.map((e) => (
              <li key={e.seq}>
                <span className="act-event">{e.summary}</span>
                <span className="act-when">
                  {e.actor === "user" ? "You" : "Foresight"} · {when(e.occurred_at, locale, timeZone)}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="act-empty">No changes yet.</p>
        )}
      </section>
      <p className="act-foot">
        <Icon name="lock" /> Traces stay on Foresight’s own servers: no prompts or answers are sent to a tracing
        service.
      </p>
    </div>
  );
}

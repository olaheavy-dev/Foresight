"use client";

/**
 * The inline agent-step checklist (docs/08 §5.10 compact form): built from the run's step events
 * while the answer streams, then folded into the Overview evidence line. Icon plus words carry
 * each result, never colour alone.
 */
import { useId, useState } from "react";
import { Icon, type IconName } from "@/components/icons/Icon";
import type { RunStep } from "@/lib/ask";
import { formatClock } from "@/lib/format";
import type { AgentExecutionTimeline, EvidenceLine as EvidenceLineData } from "@/ui-contracts/types";

const RESULT: Record<RunStep["status"], { result: string; word: string; icon: IconName | null }> = {
  started: { result: "active", word: "In progress", icon: null },
  done: { result: "done", word: "Done", icon: "check" },
  revised: { result: "done", word: "Revised", icon: "check" },
  cached: { result: "done", word: "Reused", icon: "check" },
  rejected: { result: "rejected", word: "Rejected", icon: "xcircle" },
  skipped: { result: "skipped", word: "Skipped", icon: "info" },
};

export function StepChecklist({
  steps,
  locale,
  timeZone,
  label = "Steps behind this answer",
}: {
  steps: RunStep[];
  locale: string;
  timeZone: string;
  label?: string;
}) {
  if (steps.length === 0) return null;
  return (
    <ol className="agent-steps" aria-label={label}>
      {steps.map((s) => {
        const r = RESULT[s.status];
        return (
          <li key={s.step_id} data-result={r.result} data-state={s.status === "started" ? "active" : "done"}>
            <span className="ico">{r.icon ? <Icon name={r.icon} /> : null}</span>
            <span className="label">
              <span className="sr-only">{r.word}: </span>
              <span className="lt">{s.status === "cached" ? `${s.label} · reused` : s.label}</span>
            </span>
            <span className="time">{s.at ? formatClock(s.at, locale, timeZone) : ""}</span>
            {s.reason ? <span className="d">{s.reason}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}

/** Steps from a stored timeline block, for an answer reopened from its snapshot. */
export function stepsFromTimeline(t: AgentExecutionTimeline | null): RunStep[] {
  if (!t) return [];
  const map: Record<string, RunStep["status"]> = {
    ok: "done",
    rejected: "rejected",
    retried: "revised",
    error: "skipped",
    skipped: "skipped",
    cached: "cached",
  };
  return t.steps.map((s) => ({
    step_id: s.step_id,
    agent: s.agent,
    label: s.label,
    status: map[s.status] ?? "done",
    reason: s.note ?? null,
    at: s.started_at,
  }));
}

export function evidenceText(line: EvidenceLineData | null | undefined, steps: RunStep[]): string {
  const agents = line?.agents ?? new Set(steps.map((s) => s.agent)).size;
  const rejected = line?.rejected_drafts ?? steps.filter((s) => s.status === "rejected").length;
  const drafts = rejected === 0 ? "no drafts rejected" : `${rejected} ${rejected === 1 ? "draft" : "drafts"} rejected`;
  return `Checked by ${agents} ${agents === 1 ? "agent" : "agents"} · ${drafts}`;
}

/** The Overview's last slot: one line that opens the step checklist in place. */
export function EvidenceLine({
  line,
  steps,
  locale,
  timeZone,
  showFullDetails,
}: {
  line: EvidenceLineData | null | undefined;
  steps: RunStep[];
  locale: string;
  timeZone: string;
  showFullDetails: boolean;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!line && steps.length === 0) return null;
  const times = steps.map((s) => s.at).filter((t): t is string => Boolean(t));
  return (
    <div className="evidence">
      <button type="button" className="evidence-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        <Icon name="checkcircle" className="ok" />
        <span className="ev-t">{evidenceText(line, steps)}</span>
        <span className="go">
          {open ? "Hide steps" : "View how"}
          <Icon name="chevdown" />
        </span>
      </button>
      <div className="evidence-body" id={id} hidden={!open}>
        {steps.length ? (
          <StepChecklist steps={steps} locale={locale} timeZone={timeZone} />
        ) : (
          <p className="evidence-foot">The step-by-step record is in “How it was checked”.</p>
        )}
        <p className="evidence-foot">
          <span>
            {times.length
              ? `Started ${formatClock(times[0], locale, timeZone)} · checked ${formatClock(times[times.length - 1], locale, timeZone)}`
              : ""}
          </span>
          {showFullDetails ? (
            <a href="#checked">
              Full details <Icon name="arrowright" />
            </a>
          ) : null}
        </p>
      </div>
    </div>
  );
}

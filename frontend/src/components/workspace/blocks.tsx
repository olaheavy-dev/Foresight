"use client";

/**
 * Renderers for the answer blocks (docs/08 §5): one component per contract type, selected by the
 * `type` discriminator. A block that failed validation never reaches these; it is shown as a
 * BlockError tile in its slot (§9), so one bad block never blanks the answer.
 */
import { createContext, type ReactNode, useContext } from "react";
import { CashFlowChart } from "@/components/charts/CashFlowChart";
import { Icon, type IconName } from "@/components/icons/Icon";
import { NotShipped } from "@/components/ui/NotShipped";
import type { BlockResult } from "@/lib/api";
import {
  formatClock,
  formatCount,
  formatDuration,
  formatLongDate,
  formatShortDate,
  formatUsdEstimate,
} from "@/lib/format";
import type {
  AgentExecutionTimeline,
  Block,
  CashFlowForecastChart,
  ClarifyingQuestion,
  EvidencePanel,
  FinancialMetricGroup,
  GoalProjection,
  InterventionCard,
  Narrative,
  RiskAssessment,
  ScenarioComparison,
  SpendingBreakdownChart,
  TransactionTable,
} from "@/ui-contracts/types";
import { Cite, Sources } from "./citations";
import { Columns, HBars, LineChart } from "./charts";
import { Segments } from "./values";

export type BlockEnv = {
  currency: string;
  locale: string;
  timeZone: string;
  /** Send a follow-up question (clarifying options). */
  ask: (question: string) => void;
  /** Checked advice ships behind its own flag (features.yaml `checked_advice`). */
  checkedAdvice: boolean;
};

const EnvCtx = createContext<BlockEnv>({
  currency: "GBP",
  locale: "en-GB",
  timeZone: "Europe/London",
  ask: () => {},
  checkedAdvice: true,
});
export const BlockEnvProvider = EnvCtx.Provider;
const useEnv = () => useContext(EnvCtx);

function Head({
  icon,
  title,
  sub,
  aside,
  chip,
}: {
  icon: IconName;
  title: string | null | undefined;
  sub?: ReactNode;
  aside?: ReactNode;
  chip?: "green" | "red" | "plain" | "blue";
}) {
  if (!title && !sub) return null;
  return (
    <div className="card-head">
      {chip ? (
        <span className={`icon-chip sm ${chip === "blue" ? "" : chip}`}>
          <Icon name={icon} />
        </span>
      ) : (
        <Icon name={icon} className="icon-bare" />
      )}
      <div>
        {title ? <h2 className="card-title">{title}</h2> : null}
        {sub ? <p className="card-sub">{sub}</p> : null}
      </div>
      {aside}
    </div>
  );
}

const toneClass = (tone: string) =>
  tone === "positive" ? "pos" : tone === "negative" ? "neg" : tone === "caution" ? "warn" : "";

// ---------------------------------------------------------------------------------------------

export function NarrativeBlock({ block }: { block: Narrative }) {
  return (
    <article className="card ws-card narrative">
      <Head icon="filetext" title={block.title} />
      <p className="prose">
        <Segments segments={block.segments} />
      </p>
      {block.caption ? <p className="card-sub">{block.caption}</p> : null}
    </article>
  );
}

export function ClarifyBlock({ block }: { block: ClarifyingQuestion }) {
  const { ask } = useEnv();
  return (
    <ClarifyCard
      question={block.question}
      options={block.options.map((o) => ({ label: o.label, question: o.payload.question }))}
      onPick={ask}
    />
  );
}

export function ClarifyCard({
  question,
  options,
  onPick,
}: {
  question: string;
  options: { label: string; question: string }[];
  onPick: (question: string) => void;
}) {
  return (
    <section className="card ws-card clarify" aria-labelledby="clarify-h">
      <div className="card-head">
        <span className="icon-chip sm">
          <Icon name="sparkles" />
        </span>
        <div>
          <h2 className="card-title" id="clarify-h">
            {question}
          </h2>
          <p className="card-sub">Pick one so the answer uses the right numbers.</p>
        </div>
      </div>
      <div className="clarify-options" role="group" aria-label="Choose what you meant">
        {options.map((o) => (
          <button key={o.label} type="button" className="chip" onClick={() => onPick(o.question)}>
            {o.label}
          </button>
        ))}
      </div>
    </section>
  );
}

export function MetricsBlock({ block, inline = false }: { block: FinancialMetricGroup; inline?: boolean }) {
  const list = (
    <dl className={inline ? "keynums card" : "keynums"} aria-label={block.title ?? "Key numbers"}>
      {block.metrics.map((m) => (
        <div key={m.label}>
          <dt>{m.label}</dt>
          <dd className={`v num ${toneClass(m.tone)}`}>
            {m.value.display}
            <Cite refId={m.value.ref} />
          </dd>
          {m.compare ? (
            <dd className="n">
              {m.compare.label} {m.compare.value.display} · {m.compare.delta.display}
            </dd>
          ) : null}
        </div>
      ))}
    </dl>
  );
  if (inline) return list;
  return (
    <article className="card ws-card">
      <Head icon="gauge" title={block.title} />
      {list}
      <Sources refs={block.evidence} />
    </article>
  );
}

export function SpendingBlock({ block }: { block: SpendingBreakdownChart }) {
  const env = useEnv();
  const { locale } = env;
  const currency = block.currency ?? env.currency;
  const period = `${formatShortDate(block.period.from, locale)} – ${formatShortDate(block.period.to, locale)}`;
  return (
    <article className="card ws-card">
      <Head icon="bars" title={block.title ?? "Spending"} sub={block.caption ?? period} />
      {block.mode === "over_time" ? (
        <Columns
          x={block.x}
          values={block.series[0]?.values ?? []}
          baseline={block.baseline?.minor ?? null}
          currency={currency}
          locale={locale}
          ariaLabel={`${block.series[0]?.label ?? "Spending"} for each period, ${period}. Total ${block.total.display}.`}
        />
      ) : (
        <HBars
          label={block.title ?? "Spending"}
          rows={block.series.map((s) => ({
            key: s.key,
            label: s.label,
            minor: s.value.minor,
            display: s.value.display,
            note: s.share ? `${s.share.display} of total` : undefined,
            baselineMinor: block.mode === "vs_baseline" ? (s.baseline?.minor ?? null) : null,
            baselineDisplay: block.mode === "vs_baseline" ? (s.baseline?.display ?? null) : null,
            highlight: (block.highlight_keys ?? []).includes(s.key),
          }))}
        />
      )}
      <p className="total">
        Total <span className="num">{block.total.display}</span>
      </p>
      <Sources refs={block.evidence} />
    </article>
  );
}

export function CashFlowBlock({ block }: { block: CashFlowForecastChart }) {
  const { currency, locale } = useEnv();
  return (
    <article className="card ws-card">
      <Head icon="pulse" title={block.title ?? "Cash-flow forecast"} sub={block.caption ?? block.scope.label} />
      <CashFlowChart
        data={block}
        currency={block.currency ?? currency}
        locale={locale}
        title={block.title ?? "Cash-flow forecast"}
        calloutFirstLow={false}
      />
      <Sources refs={block.evidence} />
    </article>
  );
}

const VERDICT_TONE: Record<string, { tone: string; icon: IconName; word: string }> = {
  comfortable: { tone: "green", icon: "checkcircle", word: "Comfortable" },
  tight: { tone: "amber", icon: "alert", word: "Tight" },
  breaches_buffer: { tone: "red", icon: "alert", word: "Below buffer" },
  goes_negative: { tone: "red", icon: "xcircle", word: "Overdrawn" },
};

export function ScenarioBlock({ block }: { block: ScenarioComparison }) {
  const { currency, locale } = useEnv();
  const inOverview = block.placement.area === "overview";
  const rows = block.comparison_rows ?? [];
  const verdict = block.verdict ? VERDICT_TONE[block.verdict.kind] : null;
  const chart = (
    <LineChart
      currency={block.currency ?? currency}
      locale={locale}
      ariaLabel={`${block.title ?? "Scenario comparison"}: ${[block.baseline.label, ...block.scenarios.map((s) => s.label)].join(", ")}.`}
      lines={[
        {
          key: "baseline",
          label: block.baseline.label,
          kind: "forecast",
          dates: block.baseline.series.dates,
          values: block.baseline.series.p50,
          band:
            block.baseline.series.p10 && block.baseline.series.p90
              ? { lo: block.baseline.series.p10, hi: block.baseline.series.p90 }
              : null,
        },
        ...block.scenarios.map((s) => ({
          key: s.scenario_id,
          label: s.label,
          kind: "scenario" as const,
          dates: s.series.dates,
          values: s.series.p50,
        })),
      ]}
    />
  );
  return (
    <article className="card ws-card">
      <Head
        icon="scale"
        title={block.title ?? "Scenario comparison"}
        sub={block.caption}
        aside={
          verdict ? (
            <span className={`badge ${verdict.tone}`}>
              <Icon name={verdict.icon} />
              {verdict.word}
            </span>
          ) : null
        }
      />
      {block.verdict ? <p className="verdict-line">{block.verdict.text}</p> : null}
      {inOverview || rows.length === 0 ? chart : null}
      {!inOverview && rows.length > 0 ? (
        <div className="scroll-x">
          <table className="data compare-table">
            <thead>
              <tr>
                <th scope="col">Measure</th>
                <th scope="col" className="r">
                  {block.baseline.label}
                </th>
                {block.scenarios.map((s) => (
                  <th key={s.scenario_id} scope="col" className="r">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.metric_label}>
                  <td className="lead">{r.metric_label}</td>
                  <td className="r num" data-label={block.baseline.label}>
                    {r.baseline.display}
                    <Cite refId={r.baseline.ref} />
                  </td>
                  {r.scenarios.map((v, i) => (
                    <td
                      key={i}
                      className={`r num ${toneClass(r.tone[i] ?? "neutral")}`}
                      data-label={block.scenarios[i]?.label ?? ""}
                    >
                      {v.display}
                      {r.delta[i] ? <span className="d2">{r.delta[i].display}</span> : null}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {block.assumptions?.length ? (
        <details className="assumptions">
          <summary>Assumptions</summary>
          <ul>
            {block.assumptions.map((a) => (
              <li key={a.label}>
                <strong>{a.label}:</strong> {a.value} <span className="faint">({a.source})</span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <Sources refs={block.evidence} />
    </article>
  );
}

const COLUMN_LABEL: Record<string, string> = {
  date: "Date",
  narration: "Description",
  counterparty: "Who",
  category: "Category",
  amount: "Amount",
  payment_type: "Type",
  source: "Source",
};

export function TransactionsBlock({ block }: { block: TransactionTable }) {
  const { locale } = useEnv();
  return (
    <article className="card ws-card">
      <Head
        icon="list"
        chip="plain"
        title={block.title ?? "Transactions"}
        sub={`${block.count.display} ${block.count.value === 1 ? "transaction" : "transactions"} · total ${block.total.display}`}
      />
      <div className="scroll-x">
        <table className="data">
          <thead>
            <tr>
              {block.columns.map((c) => (
                <th key={c} scope="col" className={c === "amount" ? "r" : undefined}>
                  {COLUMN_LABEL[c]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((r) => (
              <tr key={r.txn_id}>
                {block.columns.map((c) => {
                  switch (c) {
                    case "date":
                      return (
                        <td key={c} className="lead num">
                          {formatShortDate(r.date, locale)}
                        </td>
                      );
                    case "narration":
                      return (
                        <td key={c} className="desc" data-label="Description" title={r.narration_display}>
                          {r.narration_display}
                        </td>
                      );
                    case "counterparty":
                      return (
                        <td key={c} data-label="Who">
                          {r.counterparty ?? "—"}
                        </td>
                      );
                    case "category":
                      return (
                        <td key={c} data-label="Category">
                          {r.category.label}
                        </td>
                      );
                    case "amount":
                      return (
                        <td key={c} className={`r num ${r.amount.minor > 0 ? "pos" : ""}`} data-label="Amount">
                          {r.amount.minor > 0 ? `+${r.amount.display}` : r.amount.display}
                        </td>
                      );
                    case "payment_type":
                      return (
                        <td key={c} data-label="Type">
                          {r.payment_type ?? "—"}
                        </td>
                      );
                    case "source":
                      return (
                        <td key={c} data-label="Source">
                          {r.source ? `Row ${r.source.row_number}` : "—"}
                        </td>
                      );
                  }
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {block.has_more ? <p className="card-sub">More match this answer than are shown here.</p> : null}
      <Sources refs={block.evidence} />
    </article>
  );
}

const RISK_LEVEL: Record<string, { tone: string; word: string }> = {
  low: { tone: "green", word: "Low" },
  watch: { tone: "amber", word: "Watch" },
  high: { tone: "red", word: "High" },
};

export function RiskBlock({ block }: { block: RiskAssessment }) {
  const { locale } = useEnv();
  return (
    <article className="card ws-card">
      <Head icon="shield" title={block.title ?? "Risks"} />
      <ul className="risks">
        {block.risks.map((r) => (
          <li key={r.risk_id}>
            <div className="risk-top">
              <span className={`badge ${RISK_LEVEL[r.level].tone}`}>
                <Icon name="alert" />
                {RISK_LEVEL[r.level].word}
              </span>
              <strong>{r.headline}</strong>
            </div>
            <p className="risk-meta">
              {r.probability ? (
                <>
                  <span className="num">{r.probability.display}</span> chance
                  <Cite refId={r.probability.ref} />
                </>
              ) : null}
              {r.window
                ? ` · ${formatShortDate(r.window.from, locale)} – ${formatShortDate(r.window.to, locale)}`
                : null}
              {r.impact ? (
                <>
                  {" · "}
                  <span className="num">{r.impact.display}</span>
                </>
              ) : null}
            </p>
            {r.drivers?.length ? (
              <ul className="drivers">
                {r.drivers.map((d) => (
                  <li key={d.ref}>
                    {d.label} <span className="num">{d.impact.display}</span>
                    <Cite refId={d.ref} />
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
      <Sources refs={block.evidence} />
    </article>
  );
}

export function InterventionBlock({ block, compact = false }: { block: InterventionCard; compact?: boolean }) {
  const { checkedAdvice, locale } = useEnv();
  if (!checkedAdvice) {
    return (
      <article className="card ws-card rec">
        <NotShipped
          title="Checked advice"
          compact
          detail="Recommendations appear here once the Advisor and Verifier loop passes its evaluation."
        />
      </article>
    );
  }
  const v = block.verification;
  const impact = block.impact;
  return (
    <article className="card ws-card rec">
      <div className="card-head">
        <span className="icon-chip sm green">
          <Icon name="leaf" />
        </span>
        <div>
          <h2 className="card-title">{compact ? "What to do" : block.title}</h2>
        </div>
        <span className="badge green">
          <Icon name="check" />
          Checked
        </span>
      </div>
      {compact ? <h3>{block.title}</h3> : null}
      <p>
        <Segments segments={block.rationale_segments} strongValues />
      </p>
      {!compact ? (
        <dl className="changes" aria-label="What changes">
          <div>
            <dt>Chance below your buffer</dt>
            <dd className="num">
              {impact.p_breach_before.display} → {impact.p_breach_after.display}
              <span>
                {formatShortDate(impact.p_breach_window.from, locale)} –{" "}
                {formatShortDate(impact.p_breach_window.to, locale)}
              </span>
            </dd>
          </div>
          {(impact.low_deltas ?? []).map((d) => (
            <div key={d.cycle_label}>
              <dt>{d.cycle_label} low</dt>
              <dd className="num">
                {d.before.display} → {d.after.display}
              </dd>
            </div>
          ))}
          {impact.monthly_saving ? (
            <div>
              <dt>At your current rate</dt>
              <dd className="num">{impact.monthly_saving.display} a month</dd>
            </div>
          ) : null}
          {impact.goal_delta ? (
            <div>
              <dt>Goal</dt>
              <dd className="num">{impact.goal_delta.display}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      {!compact && block.actions.length ? (
        <ul className="rec-actions">
          {block.actions.map((a) => (
            <li key={a.label}>
              <strong>{a.label}</strong> {a.detail}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="checked-note">
        <Icon name="checkcircle" />
        {v.checks_passed} of {v.checks_total} checks passed
        {v.revisions > 0 ? ` · revised ${v.revisions === 1 ? "once" : `${v.revisions} times`} before you saw it` : ""}
        <Cite refId={v.verification_id} />
      </p>
      {compact ? (
        <div className="btns">
          <a className="btn primary" href="#recommendation">
            View full recommendation <Icon name="arrowright" />
          </a>
        </div>
      ) : null}
    </article>
  );
}

const GOAL_BAND: Record<string, { tone: string; word: string }> = {
  on_track: { tone: "green", word: "On track" },
  at_risk: { tone: "amber", word: "At risk" },
  off_track: { tone: "red", word: "Off track" },
};

export function GoalBlock({ block }: { block: GoalProjection }) {
  const { currency, locale } = useEnv();
  const band = GOAL_BAND[block.projection.status_band];
  return (
    <article className="card ws-card">
      <Head
        icon="target"
        title={block.title ?? block.goal.name}
        sub={`${block.goal.target.display} by ${block.goal.target_date.display}`}
        aside={
          <span className={`badge ${band.tone}`}>
            <Icon name={band.tone === "green" ? "checkcircle" : "alert"} />
            {band.word}
          </span>
        }
      />
      <dl className="keynums">
        <div>
          {/* Residual funding: nothing is set aside, so this is what's spare above the buffer. */}
          <dt>Spare now</dt>
          <dd className="v num">{block.progress_now.display}</dd>
          <dd className="n">above your buffer, at the next low</dd>
        </div>
        <div>
          <dt>Likely by {block.goal.target_date.display}</dt>
          <dd className="v num">
            {block.projection.p50.display}
            <Cite refId={block.projection.p50.ref} />
          </dd>
          <dd className="n">
            likely {block.projection.p10.display} – {block.projection.p90.display}
          </dd>
        </div>
        <div>
          <dt>Chance of reaching it</dt>
          <dd className="v num">{block.projection.p_achieve.display}</dd>
          {block.required_monthly_change ? (
            <dd className="n">{block.required_monthly_change.display} more a month would close the gap</dd>
          ) : null}
        </div>
      </dl>
      <LineChart
        currency={block.currency ?? currency}
        locale={locale}
        target={block.goal.target.minor}
        targetLabel={`Target ${block.goal.target.display}`}
        ariaLabel={`${block.goal.name}: what's spare above your buffer at each pay-cycle low to ${formatLongDate(block.goal.target_date.value, locale)}, with the likely range.`}
        lines={[
          {
            key: "trajectory",
            label: "Spare at each low",
            kind: "forecast",
            dates: block.trajectory.dates,
            values: block.trajectory.p50,
            band: { lo: block.trajectory.p10, hi: block.trajectory.p90 },
          },
        ]}
      />
      <Sources refs={block.evidence} />
    </article>
  );
}

const PROVENANCE: Record<string, string> = {
  observed: "Observed",
  detected: "Detected",
  confirmed: "Confirmed",
  declared: "Declared",
  user_set: "Set by you",
  default: "Default",
};

export function EvidenceBlock({ block }: { block: EvidencePanel }) {
  return (
    <article
      className={`card ws-card ${block.items.every((i) => i.kind === "verification" && i.critique) ? "rejected" : ""}`}
    >
      <Head
        icon={block.items.some((i) => i.critique) ? "xcircle" : "filetext"}
        chip={block.items.some((i) => i.critique) ? "red" : undefined}
        title={block.title ?? "Evidence"}
        sub={block.items.some((i) => i.critique) ? "The Verifier stopped this before it reached you" : undefined}
      />
      <ul className="evidence-items">
        {block.items.map((item) => (
          <li key={item.ref}>
            {item.critique ? <p className="draft">{item.title}</p> : <p className="ev-title">{item.title}</p>}
            <p className="ev-meta">
              <span className="badge grey">{PROVENANCE[item.provenance]}</span>
              {item.engine_version ? <span>Engine {item.engine_version}</span> : null}
              <Cite refId={item.ref} />
            </p>
            {item.summary_lines.map((l, i) => (
              <p key={i} className="ev-line">
                {l}
              </p>
            ))}
            {item.checks?.length ? (
              <ul className="checks">
                {item.checks.map((c) => (
                  <li key={c.name} data-passed={c.passed}>
                    <Icon name={c.passed ? "check" : "xcircle"} />
                    <span className="sr-only">{c.passed ? "Passed: " : "Failed: "}</span>
                    {c.name}
                    {c.detail ? <span className="faint"> · {c.detail}</span> : null}
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
    </article>
  );
}

export const AGENT_NAME: Record<string, string> = {
  coordinator: "Coordinator",
  ledger: "Ledger",
  analyst: "Behaviour Analyst",
  forecaster: "Forecaster",
  advisor: "Advisor",
  verifier: "Verifier",
};

/** "7 model calls · 18,240 tokens · about $0.05 · 6.4 s" (estimated), or the cache-hit line. */
export function costLine(block: AgentExecutionTimeline, locale = "en-GB"): string {
  const { cost } = block;
  if (cost.cached || cost.model_calls === 0) {
    return `0 model calls · reused your earlier answer · ${formatDuration(block.duration_ms, locale)}`;
  }
  return [
    `${cost.model_calls} model ${cost.model_calls === 1 ? "call" : "calls"}`,
    `${formatCount(cost.tokens, locale)} tokens`,
    cost.usd_estimate === null ? null : formatUsdEstimate(cost.usd_estimate, locale),
    formatDuration(block.duration_ms, locale),
  ]
    .filter(Boolean)
    .join(" · ");
}

export function TimelineBlock({ block }: { block: AgentExecutionTimeline }) {
  const { locale, timeZone } = useEnv();
  const agents = new Set(block.steps.map((s) => s.agent)).size;
  return (
    <article className="card ws-card">
      <Head
        icon="shuffle"
        title={block.title ?? "How it was checked"}
        sub={`${agents} ${agents === 1 ? "agent" : "agents"} · each step is logged and can be inspected`}
      />
      <ol className="timeline">
        {block.steps.map((s) => {
          const rejected = s.status === "rejected" || s.status === "error";
          const extra =
            s.status === "rejected"
              ? " · rejected a draft"
              : s.status === "retried"
                ? " · retried"
                : s.status === "error"
                  ? " · failed"
                  : s.status === "skipped"
                    ? " · skipped"
                    : s.status === "cached"
                      ? " · reused"
                      : "";
          return (
            <li key={s.step_id} className={rejected ? "rej" : undefined}>
              <span className="t">
                {AGENT_NAME[s.agent] ?? s.agent}
                {extra}
              </span>
              <span className="time">{formatClock(s.started_at, locale, timeZone)}</span>
              <Icon
                name={rejected ? "xcircle" : "checkcircle"}
                className={rejected ? "no" : "ok"}
                label={rejected ? "Rejected" : "Done"}
              />
              <span className="d">
                {s.label}
                {s.note ? ` — ${s.note}` : ""}
              </span>
              {s.model ? (
                <span className="m">
                  {s.model}
                  {s.tokens ? ` · ${formatCount(s.tokens, locale)} tokens` : ""}
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
      {block.loops?.length ? (
        <div className="loops">
          {block.loops.map((l) => (
            <p key={l.recommendation_id}>
              <strong>Verification loop:</strong>{" "}
              {l.attempts
                .map(
                  (a) =>
                    `draft ${a.version_id} ${a.verdict === "approve" ? "approved" : a.verdict === "reject" ? `rejected${a.failed_checks?.length ? ` (${a.failed_checks.join(", ")})` : ""}` : "sent back for revision"}`,
                )
                .join(" → ")}
            </p>
          ))}
        </div>
      ) : null}
      <p className="cost">
        <Icon name="gauge" />
        <span>
          {costLine(block, locale)} <span className="faint">· estimated</span>
        </span>
      </p>
      <p className="method">
        <Icon name="info" />
        <span>
          Every number here comes from the forecast engine and your categorised transactions, not written by AI. The AI
          chose which views to show and wrote the sentences around them. Costs are estimated from the tokens each step
          used.
        </span>
      </p>
    </article>
  );
}

/** The fallback tile for a block that failed validation (docs/08 §9). */
export function BlockError({ type }: { type: string | null }) {
  return (
    <article className="card ws-card block-error" role="note">
      <div className="card-head">
        <span className="icon-chip sm amber">
          <Icon name="alert" />
        </span>
        <div>
          <h2 className="card-title">This part of the answer couldn’t be shown</h2>
          <p className="card-sub">
            {type
              ? `The ${type.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase()} didn’t pass our checks`
              : "A view didn’t pass our checks"}
            , so we left it out rather than show figures we couldn’t verify. The rest of the answer is unaffected.
          </p>
        </div>
      </div>
    </article>
  );
}

export function BlockView({ block, compact = false }: { block: Block; compact?: boolean }) {
  switch (block.type) {
    case "Narrative":
      return <NarrativeBlock block={block} />;
    case "ClarifyingQuestion":
      return <ClarifyBlock block={block} />;
    case "FinancialMetricGroup":
      return <MetricsBlock block={block} />;
    case "SpendingBreakdownChart":
      return <SpendingBlock block={block} />;
    case "CashFlowForecastChart":
      return <CashFlowBlock block={block} />;
    case "ScenarioComparison":
      return <ScenarioBlock block={block} />;
    case "TransactionTable":
      return <TransactionsBlock block={block} />;
    case "RiskAssessment":
      return <RiskBlock block={block} />;
    case "InterventionCard":
      return <InterventionBlock block={block} compact={compact} />;
    case "GoalProjection":
      return <GoalBlock block={block} />;
    case "EvidencePanel":
      return <EvidenceBlock block={block} />;
    case "AgentExecutionTimeline":
      return <TimelineBlock block={block} />;
  }
}

export function BlockResultView({ result, compact = false }: { result: BlockResult; compact?: boolean }) {
  return result.ok ? <BlockView block={result.block} compact={compact} /> : <BlockError type={result.type} />;
}

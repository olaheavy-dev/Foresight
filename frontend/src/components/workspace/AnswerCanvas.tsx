"use client";

/**
 * The answer skeleton (docs/08 §7a, owner decision 12 Oct 2026). Every Workspace answer uses the
 * same frame: the Overview's slots in a fixed order (verdict · key numbers · one main visual ·
 * what to do · evidence line), then the fixed tabs Overview · Details · Recommendation ·
 * Transactions · How it was checked. A tab with nothing in it is hidden, never reordered.
 * Placement comes from the server; this only lays blocks out where they were put.
 */
import { useMemo } from "react";
import { Icon } from "@/components/icons/Icon";
import { Tabs, type TabItem } from "@/components/ui/Tabs";
import type { BlockResult, ParsedResponse } from "@/lib/api";
import type { RunStep } from "@/lib/ask";
import { formatDayDate, formatDuration } from "@/lib/format";
import type { AgentExecutionTimeline, Block, Narrative, OverviewPlacement, TabPlacement } from "@/ui-contracts/types";
import { BlockError, BlockResultView, ClarifyBlock, InterventionBlock, MetricsBlock } from "./blocks";
import { CitationProvider, citationOrder } from "./citations";
import { EvidenceLine, StepChecklist, stepsFromTimeline } from "./steps";
import { Segments } from "./values";

type Slot = Exclude<OverviewPlacement["slot"], "evidence">;
type TabName = TabPlacement["tab"];

const SLOTS: Slot[] = ["verdict", "key_numbers", "main_visual", "what_to_do"];
const TABS: { id: TabName; label: string }[] = [
  { id: "details", label: "Details" },
  { id: "recommendation", label: "Recommendation" },
  { id: "transactions", label: "Transactions" },
  { id: "checked", label: "How it was checked" },
];

/** Where a block sits. A block whose placement didn't validate goes to Details. */
function placeOf(b: BlockResult): { area: "overview"; slot: Slot } | { area: "tab"; tab: TabName } {
  const p = b.ok ? b.block.placement : b.placement;
  if (!p) return { area: "tab", tab: "details" };
  if (p.area === "overview")
    return p.slot === "evidence" ? { area: "tab", tab: "checked" } : { area: "overview", slot: p.slot };
  return { area: "tab", tab: p.tab };
}

export function layoutAnswer(response: ParsedResponse) {
  const overview: Record<Slot, BlockResult[]> = { verdict: [], key_numbers: [], main_visual: [], what_to_do: [] };
  const tabs: Record<TabName, BlockResult[]> = { details: [], recommendation: [], transactions: [], checked: [] };
  for (const b of response.blocks) {
    const p = placeOf(b);
    if (p.area === "overview") overview[p.slot].push(b);
    else tabs[p.tab].push(b);
  }
  const reading = [...SLOTS.flatMap((s) => overview[s]), ...TABS.flatMap((t) => tabs[t.id])];
  const okBlocks = reading.flatMap((b) => (b.ok ? [b.block] : []));
  const timeline = okBlocks.find((b): b is AgentExecutionTimeline => b.type === "AgentExecutionTimeline") ?? null;
  return { overview, tabs, okBlocks, timeline };
}

export const isRefusal = (r: ParsedResponse) => r.intent === "smalltalk_or_unsupported";

function Verdict({ result, question }: { result: BlockResult | undefined; question: string | null }) {
  if (!result) return question ? <h1 className="verdict serif">{question}</h1> : null;
  if (!result.ok) return <BlockError type={result.type} />;
  const b = result.block;
  if (b.type === "ClarifyingQuestion") return <ClarifyBlock block={b} />;
  if (b.type !== "Narrative") return null;
  const n = b as Narrative;
  return (
    <div className="verdict-block">
      <h1 className="verdict serif">{n.title ?? <Segments segments={n.segments} />}</h1>
      {n.title ? (
        <p className="verdict-sub">
          <Segments segments={n.segments} strongValues={false} />
        </p>
      ) : null}
    </div>
  );
}

export function AnswerCanvas({
  response,
  liveSteps,
  locale,
  timeZone,
  auditTrail,
  openEvidence,
  partial = false,
}: {
  response: ParsedResponse;
  liveSteps: RunStep[];
  locale: string;
  timeZone: string;
  auditTrail: boolean;
  openEvidence: (ref: string) => void;
  partial?: boolean;
}) {
  const laid = useMemo(() => layoutAnswer(response), [response]);
  const order = useMemo(() => citationOrder(laid.okBlocks), [laid]);
  const steps = liveSteps.length ? liveSteps : stepsFromTimeline(laid.timeline);
  const refusal = isRefusal(response);

  const verdict = laid.overview.verdict[0];
  const keyNumbers = laid.overview.key_numbers[0];
  const main = laid.overview.main_visual;
  const todo = laid.overview.what_to_do[0];
  const showChecked = laid.tabs.checked.length > 0 || steps.length > 0;

  const overviewPanel = (
    <div className="ov">
      {keyNumbers ? (
        keyNumbers.ok && keyNumbers.block.type === "FinancialMetricGroup" ? (
          <MetricsBlock block={keyNumbers.block} inline />
        ) : (
          <BlockResultView result={keyNumbers} />
        )
      ) : null}
      {main.length || todo ? (
        <div className={todo ? "ov-grid" : "ov-grid single"}>
          {main.length ? (
            <div className="slot-main">
              {main.map((b, i) => (
                <BlockResultView key={i} result={b} />
              ))}
            </div>
          ) : null}
          {todo ? (
            <div className="slot-todo">
              {todo.ok && todo.block.type === "InterventionCard" ? (
                <InterventionBlock block={todo.block} compact />
              ) : (
                <BlockResultView result={todo} />
              )}
            </div>
          ) : null}
        </div>
      ) : null}
      {!refusal ? (
        <EvidenceLine
          line={response.evidence_line}
          steps={steps}
          locale={locale}
          timeZone={timeZone}
          showFullDetails={showChecked}
        />
      ) : null}
    </div>
  );

  const items: TabItem[] = [{ id: "overview", label: "Overview", content: overviewPanel }];
  for (const t of TABS) {
    const blocks = laid.tabs[t.id];
    if (t.id === "checked") {
      if (!showChecked) continue;
      items.push({
        id: t.id,
        label: t.label,
        content: (
          <div className="panel-stack">
            {blocks.length ? (
              blocks.map((b, i) => <BlockResultView key={i} result={b} />)
            ) : (
              <article className="card ws-card">
                <div className="card-head">
                  <Icon name="shuffle" className="icon-bare" />
                  <div>
                    <h2 className="card-title">How it was checked</h2>
                    <p className="card-sub">Each step was logged as it ran</p>
                  </div>
                </div>
                <StepChecklist steps={steps} locale={locale} timeZone={timeZone} />
              </article>
            )}
          </div>
        ),
      });
      continue;
    }
    if (blocks.length === 0) continue;
    items.push({
      id: t.id,
      label: t.label,
      content: (
        <div className="panel-stack">
          {blocks.map((b, i) => (
            <BlockResultView key={i} result={b} />
          ))}
        </div>
      ),
    });
  }

  const seconds = laid.timeline ? formatDuration(laid.timeline.duration_ms, locale) : null;

  return (
    <CitationProvider order={order} open={openEvidence} enabled={auditTrail}>
      <div className="analysis">
        <div className="canvas-top">
          <span className="ai">
            <Icon name="sparkles" />
            AI Analysis
          </span>
          <span className="done">
            <Icon name="checkcircle" />
            {seconds ? `Completed in ${seconds} · ` : ""}data to {formatDayDate(response.as_of, locale)}
          </span>
        </div>

        {response.status === "degraded" ? (
          <p className="banner warn" role="status">
            <Icon name="info" />
            AI explanations unavailable for part of this answer. The numbers are unaffected.
          </p>
        ) : null}
        {partial ? (
          <p className="banner warn" role="status">
            <Icon name="alert" />
            Part of this answer couldn’t be finished in time. What’s shown was checked; the rest is missing.
          </p>
        ) : null}

        <Verdict result={verdict} question={response.question ?? null} />

        {refusal ? (
          <p className="scope-note">
            <Icon name="info" />
            Guidance, not regulated financial advice.
          </p>
        ) : (
          <Tabs key={response.response_id} items={items} label="Analysis sections" />
        )}
      </div>
    </CitationProvider>
  );
}

/** Blocks a test or the thread bubble may need without rendering the canvas. */
export function verdictText(response: ParsedResponse): string | null {
  const v = layoutAnswer(response).overview.verdict[0];
  if (!v?.ok) return null;
  const b: Block = v.block;
  if (b.type === "Narrative")
    return (
      b.title ??
      b.segments.map((s) => (s.kind === "text" ? s.text : s.kind === "value" ? s.value.display : s.label)).join("")
    );
  if (b.type === "ClarifyingQuestion") return b.question;
  return null;
}

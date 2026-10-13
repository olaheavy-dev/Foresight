/**
 * Synthetic AI Workspace payloads for tests and the e2e mock API (fictional numbers, made up
 * here; none of them is a design figure). Shapes follow the generated contracts exactly.
 *
 * This file is also loaded by e2e/mock-api.mjs under plain Node (type stripping), so it must stay
 * self-contained: type-only imports and erasable TypeScript syntax only.
 */
import type {
  AgentExecutionTimeline,
  AgentResponse,
  Block,
  CalculationView,
  CashFlowForecastChart,
  ClarifyingQuestion,
  EvidencePanel,
  FinancialMetricGroup,
  FollowUpAction,
  GoalProjection,
  InterventionCard,
  MoneyValue,
  Narrative,
  PercentValue,
  Placement,
  RiskAssessment,
  ScenarioComparison,
  Segment,
  SpendingByCategory,
  SpendingOverTime,
  TransactionTable,
} from "../ui-contracts/types";

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/** A valid, deterministic `<prefix>_<ULID>` id for fixtures. */
export function uid(prefix: string, n: number): string {
  let tail = "";
  let v = n;
  for (let i = 0; i < 6; i += 1) {
    tail = CROCKFORD[v % 32] + tail;
    v = Math.floor(v / 32);
  }
  return `${prefix}_01K7XQZM4C9R7T2X6V3N${tail}`;
}

export const WORKSPACE_ID = uid("wsp", 1);
export const AS_OF = "2026-10-11";
const CALC = "0a1b2c3d4e5f60718293a4b5";
const FC = `fc_${CALC}`;
const BUFFER = 50_000;

const gbpFmt = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 0 });
const gbpExact = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", minimumFractionDigits: 2 });

export function money(minor: number, { exact = false, ref }: { exact?: boolean; ref?: string } = {}): MoneyValue {
  const display = (exact ? gbpExact : gbpFmt).format(minor / 100).replace("-", "−");
  return { kind: "money", minor, currency: "GBP", display, precision: exact ? "exact" : "rounded", ...(ref ? { ref } : {}) };
}

export function percent(value: number, ref?: string): PercentValue {
  return { kind: "percent", value, display: `${Math.round(value * 100)}%`, ...(ref ? { ref } : {}) };
}

const ref = (path: string) => `calc_${CALC}#${path}`;
const overview = (slot: "verdict" | "key_numbers" | "main_visual" | "what_to_do"): Placement => ({ area: "overview", slot });
const tab = (name: "details" | "recommendation" | "transactions" | "checked"): Placement => ({ area: "tab", tab: name });
const text = (t: string): Segment => ({ kind: "text", text: t });

function addDays(iso: string, n: number): string {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------------------------
// Forecast series (90 days): a sawtooth with paydays on the 28th.

const FORECAST_DAYS = Array.from({ length: 90 }, (_, i) => addDays(AS_OF, i + 1));
function balanceOn(iso: string, extra = 0): number {
  const d = new Date(`${iso}T00:00:00Z`);
  const day = d.getUTCDate();
  const sinceLastPay = day >= 28 ? day - 28 : day + 3;
  const month = d.getUTCMonth();
  return 268_000 - sinceLastPay * 7_400 + (month === 11 ? 18_000 : 0) + extra;
}
const P50 = FORECAST_DAYS.map((d) => balanceOn(d));
const HISTORY_DAYS = Array.from({ length: 30 }, (_, i) => addDays(AS_OF, i - 29));

export const forecastChart = (placement: Placement = tab("details")): CashFlowForecastChart => ({
  block_id: "b5",
  type: "CashFlowForecastChart",
  title: "Your balance, day by day",
  caption: "Middle of the simulated paths with the likely range",
  currency: "GBP",
  placement,
  evidence: [FC],
  as_of: AS_OF,
  balance_mode: "absolute",
  buffer_minor: BUFFER,
  resolution: "daily",
  scope: { kind: "account", label: "Everyday current account", account_ids: [uid("acct", 1)], switchable: false },
  history: { dates: HISTORY_DAYS, balance_minor: HISTORY_DAYS.map((d) => balanceOn(d)) },
  forecast: {
    dates: FORECAST_DAYS,
    p50: P50,
    p10: P50.map((v, i) => v - 9_000 - i * 260),
    p90: P50.map((v, i) => v + 9_000 + i * 260),
  },
  events: [],
  pay_cycles: [
    { payday: "2026-10-28", low_date: "2026-10-27", low: money(balanceOn("2026-10-27"), { ref: ref("pay_cycles.0.low.p50") }), below_buffer: false, chance_below_buffer: percent(0.06) },
    { payday: "2026-11-27", low_date: "2026-11-26", low: money(balanceOn("2026-11-26"), { ref: ref("pay_cycles.1.low.p50") }), below_buffer: false, chance_below_buffer: percent(0.09) },
    { payday: "2026-12-24", low_date: "2026-12-23", low: money(balanceOn("2026-12-23"), { ref: ref("pay_cycles.2.low.p50") }), below_buffer: false, chance_below_buffer: percent(0.04) },
  ],
  summary: {
    starting_balance: { money: money(HISTORY_DAYS.length ? balanceOn(AS_OF) : 0, { exact: true }), provenance: "observed" },
    min_balance: money(balanceOn("2026-11-26"), { ref: ref("min_balance_p50_minor") }),
    min_date: { kind: "date", value: "2026-11-26", display: "26 Nov", ref: ref("min_balance_date") },
    p_breach_buffer: percent(0.09, ref("p_breach_buffer")),
  },
});

// ---------------------------------------------------------------------------------------------
// Affordability answer: "Can I afford a trip in December?"

const SIM_A = `sim_${"1b2c3d4e5f60718293a4b5c6"}`;
const SIM_B = `sim_${"2c3d4e5f60718293a4b5c6d7"}`;
const TRIP = 92_000;
const WEEKS = Array.from({ length: 13 }, (_, i) => addDays(AS_OF, 7 * (i + 1)));
const weekly = (shift: number, from: string) =>
  WEEKS.map((d) => balanceOn(d) - (d >= from ? shift : 0));
const REC_ID = uid("rec", 1);

const verdict = (title: string, segments: Segment[], id = "b1"): Narrative => ({
  block_id: id,
  type: "Narrative",
  title,
  placement: overview("verdict"),
  evidence: [FC],
  segments,
});

export const affordabilityTimeline: AgentExecutionTimeline = {
  block_id: "b9",
  type: "AgentExecutionTimeline",
  title: "How it was checked",
  placement: tab("checked"),
  evidence: [],
  run_id: uid("run", 1),
  workflow: "conversation",
  detail: "full",
  duration_ms: 6_400,
  cost: { tokens: 18_240, model_calls: 7, usd_estimate: 0.046, cached: false },
  steps: [
    { step_id: uid("step", 1), agent: "coordinator", node: "understand", label: "Read the question as a one-off trip payment in December", status: "ok", started_at: "2026-10-12T09:14:02Z", duration_ms: 900, model: "openai/gpt-6-luna", tokens: 1_420 },
    { step_id: uid("step", 2), agent: "ledger", node: "ledger_query", label: "Used your categorised transactions, data to 11 Oct", status: "ok", started_at: "2026-10-12T09:14:03Z", duration_ms: 300, tokens: null },
    { step_id: uid("step", 3), agent: "analyst", node: "analyst_step", label: "Checked your usual spending, bills and paydays", status: "ok", started_at: "2026-10-12T09:14:03Z", duration_ms: 700, model: "anthropic/claude-sonnet-5.5", tokens: 3_980 },
    { step_id: uid("step", 4), agent: "forecaster", node: "forecaster_step", label: "Simulated each timing against the same forecast paths", status: "ok", started_at: "2026-10-12T09:14:04Z", duration_ms: 1_100, tokens: null },
    { step_id: uid("step", 5), agent: "advisor", node: "advise", label: "Drafted two ways to pay for the trip", status: "ok", started_at: "2026-10-12T09:14:05Z", duration_ms: 1_300, model: "anthropic/claude-sonnet-5.5", tokens: 6_210 },
    { step_id: uid("step", 6), agent: "verifier", node: "verify", label: "Verifier rejected a draft", status: "rejected", started_at: "2026-10-12T09:14:06Z", duration_ms: 900, model: "openai/gpt-6.1-sol", tokens: 3_150, note: "“Pay on 4 Dec”: below your buffer before the next payday" },
    { step_id: uid("step", 7), agent: "verifier", node: "verify", label: "Checked the revised answer", status: "ok", started_at: "2026-10-12T09:14:08Z", duration_ms: 700, model: "openai/gpt-6.1-sol", tokens: 3_480 },
  ],
  loops: [
    {
      kind: "verification",
      recommendation_id: REC_ID,
      attempts: [
        { version_id: "v1", verdict: "reject", failed_checks: ["V-03 buffer breach"] },
        { version_id: "v2", verdict: "approve", failed_checks: [] },
      ],
    },
  ],
};

const tripScenario = (): ScenarioComparison => ({
  block_id: "b3",
  type: "ScenarioComparison",
  title: "Lowest balance with and without the trip",
  caption: "Same simulated paths for each line",
  currency: "GBP",
  placement: overview("main_visual"),
  evidence: [FC, SIM_A],
  scope: { kind: "account", label: "Everyday current account", account_ids: [uid("acct", 1)], switchable: false },
  baseline: {
    label: "Without the trip",
    series: { dates: WEEKS, p50: weekly(0, "9999"), p10: weekly(0, "9999").map((v) => v - 12_000), p90: weekly(0, "9999").map((v) => v + 12_000) },
  },
  scenarios: [
    {
      label: "With the trip, paid 28 Nov",
      scenario_id: `scn_${"3d4e5f60718293a4b5c6d7e8"}`,
      simulation_id: SIM_A,
      modifiers_summary: ["One-off payment on 28 Nov"],
      series: { dates: WEEKS, p50: weekly(TRIP, "2026-11-28") },
    },
  ],
  comparison_rows: [
    {
      metric_label: "Lowest before a payday",
      baseline: money(balanceOn("2026-11-26")),
      scenarios: [money(balanceOn("2026-12-23") - TRIP)],
      delta: [money(balanceOn("2026-12-23") - TRIP - balanceOn("2026-11-26"))],
      tone: ["caution"],
    },
    {
      metric_label: "Paths below your buffer",
      baseline: percent(0.09),
      scenarios: [percent(0.14)],
      delta: [{ kind: "pp_change", value: 0.05, display: "+5 pts" }],
      tone: ["caution"],
    },
  ],
  verdict: { kind: "comfortable", text: "Stays above your buffer in every pay cycle" },
  assumptions: [{ label: "Trip cost", value: "One payment, as you described", source: "Your question" }],
});

const whatIfTable = (): ScenarioComparison => ({
  ...tripScenario(),
  block_id: "b6",
  title: "Compare timings",
  caption: "Lowest balance in the pay cycle you pay in",
  placement: tab("recommendation"),
  evidence: [FC, SIM_A, SIM_B],
  scenarios: [
    tripScenario().scenarios[0],
    {
      label: "Paid 4 Dec",
      scenario_id: `scn_${"4e5f60718293a4b5c6d7e8f9"}`,
      simulation_id: SIM_B,
      modifiers_summary: ["One-off payment on 4 Dec"],
      series: { dates: WEEKS, p50: weekly(TRIP, "2026-12-04") },
    },
  ],
  comparison_rows: [
    {
      metric_label: "Lowest before a payday",
      baseline: money(balanceOn("2026-11-26")),
      scenarios: [money(balanceOn("2026-12-23") - TRIP), money(balanceOn("2026-12-23") - TRIP - 31_000)],
      delta: [money(-24_000), money(-55_000)],
      tone: ["caution", "negative"],
    },
  ],
  verdict: { kind: "tight", text: "Paying on 4 Dec dips below your buffer in some paths" },
});

const tripCard = (): InterventionCard => ({
  block_id: "b4",
  type: "InterventionCard",
  title: "Pay for the trip after your 27 November payday",
  placement: overview("what_to_do"),
  evidence: [SIM_A],
  currency: "GBP",
  recommendation_id: REC_ID,
  version_id: "v2",
  status: "approved",
  rationale_segments: [
    text("That keeps every pay cycle above your buffer. Paying earlier leaves the lowest point at "),
    { kind: "value", value: money(balanceOn("2026-12-23") - TRIP - 31_000, { ref: `calc_${CALC}#scenario_low` }) },
    text(", so we didn’t recommend it."),
  ],
  actions: [{ type: "timing", label: "Book after payday", detail: "Pay on or after 28 Nov" }],
  impact: {
    p_breach_before: percent(0.14),
    p_breach_after: percent(0.09),
    p_breach_window: { from: "2026-11-28", to: "2026-12-23" },
    low_deltas: [{ cycle_label: "December", before: money(balanceOn("2026-12-23") - TRIP - 31_000), after: money(balanceOn("2026-12-23") - TRIP) }],
  },
  verification: { verdict: "approved", revisions: 1, checks_passed: 9, checks_total: 9, verification_id: uid("ver", 2) },
  triggered_by: [FC],
});

const evidencePanel = (): EvidencePanel => ({
  block_id: "b7",
  type: "EvidencePanel",
  title: "A draft we rejected",
  placement: tab("recommendation"),
  evidence: [uid("ver", 1)],
  items: [
    {
      kind: "verification",
      ref: uid("ver", 1),
      title: "“Pay for the trip on 4 December”",
      provenance: "detected",
      summary_lines: ["Rejected by the Verifier: in some paths the balance goes below your buffer before the next payday."],
      critique: "Below the buffer before payday",
      checks: [
        { name: "Impact recomputed", passed: true, kind: "deterministic" },
        { name: "Stays above the buffer", passed: false, kind: "deterministic", detail: "Fails in the December cycle" },
      ],
    },
  ],
});

const txnTable = (placement: Placement = tab("transactions"), title = "Transactions behind this answer"): TransactionTable => ({
  block_id: "b8",
  type: "TransactionTable",
  title,
  placement,
  evidence: [`calc_${CALC}#txn_query`],
  currency: "GBP",
  columns: ["date", "narration", "category", "amount"],
  count: { kind: "count", value: 4, display: "4" },
  total: money(-197_300, { exact: true }),
  has_more: false,
  query: { date_from: "2026-10-01", date_to: AS_OF, direction: "out", sort: "date_desc", limit: 20 },
  rows: [
    { txn_id: uid("txn", 1), date: "2026-10-09", narration_display: "Broadband", category: { key: "bills.broadband", label: "Bills" }, amount: money(-2_900, { exact: true }) },
    { txn_id: uid("txn", 2), date: "2026-10-05", narration_display: "Weekly shop", category: { key: "food.groceries", label: "Groceries" }, amount: money(-6_420, { exact: true }) },
    { txn_id: uid("txn", 3), date: "2026-10-02", narration_display: "Rent · Hillside Lettings", category: { key: "housing.rent", label: "Housing" }, amount: money(-118_000, { exact: true }) },
    { txn_id: uid("txn", 4), date: "2026-10-01", narration_display: "Savings transfer", category: { key: "savings.transfer", label: "Savings" }, amount: money(-70_000, { exact: true }) },
  ],
});

const askFollowUp = (n: number, label: string, question: string): FollowUpAction => ({
  action_id: `fu_${n}`,
  kind: "ask",
  label,
  requires_confirmation: false,
  payload: { question, context_refs: [] },
});

function envelope(over: Partial<AgentResponse> & Pick<AgentResponse, "blocks" | "response_id" | "run_id">): AgentResponse {
  return {
    schema_version: "agent_response/1",
    surface: "workspace",
    created_at: "2026-10-12T09:14:08Z",
    as_of: AS_OF,
    workspace_id: WORKSPACE_ID,
    currency: "GBP",
    locale: "en-GB",
    data_version: 2,
    prefs_version: 1,
    engine_version: "fc-test",
    status: "complete",
    forecast_id: FC,
    provenance: { calc_ids: [`calc_${CALC}`], finding_ids: [], recommendation_ids: [] },
    follow_ups: [],
    ...over,
  };
}

export const affordabilityResponse = (): AgentResponse =>
  envelope({
    response_id: uid("rsp", 1),
    run_id: uid("run", 1),
    intent: "affordability",
    question: "Can I afford a trip in December?",
    evidence_line: { agents: 6, rejected_drafts: 1, run_id: uid("run", 1) },
    verification: { recommendations: [{ recommendation_id: REC_ID, verdict: "approve", revisions: 1 }] },
    provenance: { calc_ids: [`calc_${CALC}`], finding_ids: [], recommendation_ids: [REC_ID] },
    blocks: [
      verdict("Yes, if you pay for it after your 27 November payday.", [
        text("Your lowest point would then be "),
        { kind: "value", value: money(balanceOn("2026-12-23") - TRIP, { ref: `calc_${CALC}#scenario_low` }) },
        text(", above your buffer. Paying on 4 December dips below it in some paths."),
      ]),
      {
        block_id: "b2",
        type: "FinancialMetricGroup",
        placement: overview("key_numbers"),
        evidence: [SIM_A],
        currency: "GBP",
        metrics: [
          { label: "Lowest after paying", value: money(balanceOn("2026-12-23") - TRIP, { ref: `calc_${CALC}#scenario_low` }), emphasis: "primary", tone: "neutral" },
          { label: "Above your buffer", value: money(balanceOn("2026-12-23") - TRIP - BUFFER), emphasis: "secondary", tone: "positive" },
          { label: "Paths below the buffer", value: percent(0.09, ref("p_breach_buffer")), emphasis: "secondary", tone: "neutral" },
        ],
      } satisfies FinancialMetricGroup,
      tripScenario(),
      tripCard(),
      forecastChart(),
      whatIfTable(),
      evidencePanel(),
      txnTable(),
      affordabilityTimeline,
    ],
    follow_ups: [
      askFollowUp(1, "What if it costs more?", "What if the trip costs a bit more?"),
      askFollowUp(2, "What if my salary is late?", "What if my salary is a week late?"),
      { action_id: "fu_3", kind: "open_evidence", label: "See the forecast inputs", requires_confirmation: false, payload: { ref: `calc_${CALC}` } },
    ],
  });

// ---------------------------------------------------------------------------------------------
// Spending answer: "Why is my spending up?"

const spendingOverTime = (): SpendingOverTime => ({
  block_id: "b3",
  type: "SpendingBreakdownChart",
  mode: "over_time",
  title: "Eating out each week",
  caption: "Last 8 weeks",
  placement: overview("main_visual"),
  evidence: [`calc_${CALC}#weekly_eating_out`],
  currency: "GBP",
  period: { from: "2026-08-17", to: AS_OF },
  x: ["17 Aug", "24 Aug", "31 Aug", "7 Sep", "14 Sep", "21 Sep", "28 Sep", "5 Oct"],
  series: [{ key: "food.eating_out", label: "Eating out", values: [3_900, 4_200, 3_600, 4_100, 5_800, 6_900, 7_400, 8_100] }],
  baseline: money(4_000, { exact: true, ref: `calc_${CALC}#usual_week` }),
  total: money(44_000, { exact: true }),
  highlight_keys: ["food.eating_out"],
});

const spendingByMerchant = (): SpendingByCategory => ({
  block_id: "b5",
  type: "SpendingBreakdownChart",
  mode: "by_merchant",
  title: "Where it went",
  caption: "Last 30 days",
  placement: tab("details"),
  evidence: [`calc_${CALC}#by_merchant`],
  currency: "GBP",
  period: { from: "2026-09-12", to: AS_OF },
  total: money(27_300, { exact: true }),
  series: [
    { key: "m1", label: "Corner Café", nature: "discretionary", tone: "accent", value: money(11_900, { exact: true }), share: percent(0.44) },
    { key: "m2", label: "Noodle Bar", nature: "discretionary", tone: "neutral", value: money(8_400, { exact: true }), share: percent(0.31) },
    { key: "m3", label: "Pizza Place", nature: "discretionary", tone: "neutral", value: money(7_000, { exact: true }), share: percent(0.25) },
  ],
});

export const spendingResponse = (): AgentResponse =>
  envelope({
    response_id: uid("rsp", 2),
    run_id: uid("run", 2),
    intent: "spending_question",
    question: "Why is my spending up?",
    evidence_line: { agents: 4, rejected_drafts: 0, run_id: uid("run", 2) },
    blocks: [
      verdict("Eating out is up on a usual month.", [
        text("You spent "),
        { kind: "value", value: money(27_300, { exact: true, ref: `calc_${CALC}#last_30` }) },
        text(" in the last 30 days against a usual "),
        { kind: "value", value: money(17_400, { exact: true, ref: `calc_${CALC}#usual_30` }) },
        text(". The rise started three weeks ago at "),
        { kind: "entity", ref: uid("fnd", 1), label: "Corner Café" },
        text("."),
      ]),
      {
        block_id: "b2",
        type: "FinancialMetricGroup",
        placement: overview("key_numbers"),
        evidence: [`calc_${CALC}#last_30`],
        currency: "GBP",
        metrics: [
          { label: "Last 30 days", value: money(27_300, { exact: true }), emphasis: "primary", tone: "neutral" },
          { label: "A usual month", value: money(17_400, { exact: true }), emphasis: "secondary", tone: "neutral" },
          { label: "Above usual", value: { kind: "pct_change", value: 0.57, display: "+57%" }, emphasis: "secondary", tone: "negative" },
        ],
      },
      spendingOverTime(),
      spendingByMerchant(),
      txnTable(tab("transactions"), "Recent orders"),
      {
        ...affordabilityTimeline,
        run_id: uid("run", 2),
        duration_ms: 4_100,
        cost: { tokens: 0, model_calls: 0, usd_estimate: 0, cached: true },
        steps: affordabilityTimeline.steps.slice(0, 3).map((s) => ({ ...s, model: null, tokens: null })),
        loops: [],
      },
    ],
    follow_ups: [askFollowUp(1, "Which nights do I order most?", "Which nights do I eat out most?")],
  });

// ---------------------------------------------------------------------------------------------
// Other states

export const refusalResponse = (): AgentResponse =>
  envelope({
    response_id: uid("rsp", 3),
    run_id: uid("run", 3),
    intent: "smalltalk_or_unsupported",
    question: "Which shares should I buy?",
    evidence_line: null,
    forecast_id: null,
    blocks: [
      {
        block_id: "b1",
        type: "Narrative",
        placement: overview("verdict"),
        evidence: [],
        title: "I can’t recommend investments.",
        segments: [
          text("Foresight looks at your own transactions and forecast. Ask about a decision, a change in your spending or the months ahead."),
        ],
      },
    ],
    follow_ups: [askFollowUp(1, "How does next month look?", "How does next month look?")],
  });

export const degradedResponse = (): AgentResponse => ({
  ...spendingResponse(),
  response_id: uid("rsp", 4),
  run_id: uid("run", 4),
  status: "degraded",
});

export const clarifyingBlock: ClarifyingQuestion = {
  block_id: "b1",
  type: "ClarifyingQuestion",
  placement: overview("verdict"),
  question: "Which trip did you mean?",
  options: [askFollowUp(1, "A one-off trip", "Can I afford a one-off trip in December?") as ClarifyingQuestion["options"][number], askFollowUp(2, "A monthly getaway", "Can I afford a short trip every month?") as ClarifyingQuestion["options"][number]],
};

export const riskBlock: RiskAssessment = {
  block_id: "b10",
  type: "RiskAssessment",
  title: "Risks before payday",
  placement: tab("details"),
  evidence: [FC],
  currency: "GBP",
  risks: [
    {
      risk_id: "r1",
      level: "watch",
      headline: "Late October is tight",
      status: "open",
      probability: percent(0.06),
      impact: money(-12_000),
      window: { from: "2026-10-20", to: "2026-10-27" },
      drivers: [{ label: "Car insurance renewal", impact: money(-41_000), ref: uid("rob", 1) }],
    },
  ],
};

export const goalBlock: GoalProjection = {
  block_id: "b11",
  type: "GoalProjection",
  title: "Emergency fund",
  placement: overview("main_visual"),
  evidence: [`calc_${CALC}#goal`],
  currency: "GBP",
  scope: { kind: "mine", label: "Your accounts", account_ids: [], switchable: false },
  goal: { goal_id: uid("goal", 1), name: "Emergency fund", funding_rule: "residual", target: money(300_000), target_date: { kind: "date", value: "2027-03-31", display: "31 Mar 2027" } },
  progress_now: money(110_000),
  projection: { p10: money(240_000), p50: money(282_000), p90: money(321_000), p_achieve: percent(0.41), status_band: "at_risk" },
  required_monthly_change: money(5_000),
  trajectory: {
    dates: WEEKS,
    p50: WEEKS.map((_, i) => 110_000 + i * 12_000),
    p10: WEEKS.map((_, i) => 110_000 + i * 9_000),
    p90: WEEKS.map((_, i) => 110_000 + i * 15_000),
  },
};

export const spendingByCategoryBlock: SpendingByCategory = {
  ...spendingByMerchant(),
  block_id: "b12",
  mode: "vs_baseline",
  title: "Against a usual month",
  series: spendingByMerchant().series.map((s) => ({ ...s, baseline: money(s.value.minor - 2_000, { exact: true }) })),
};

/** One of each block type, for renderer tests. */
export const everyBlock = (): Block[] => {
  const a = affordabilityResponse().blocks;
  const s = spendingResponse().blocks;
  return [...a, s[2], s[3], clarifyingBlock, riskBlock, goalBlock, spendingByCategoryBlock];
};

export const calculation = (): CalculationView => ({
  calc_id: `calc_${CALC}`,
  workspace_id: WORKSPACE_ID,
  kind: "forecast",
  created_at: "2026-10-12T09:14:04Z",
  data_version: 2,
  duration_ms: 31,
  engine_version: "fc-test",
  inputs_hash: "9f".repeat(32),
  result_hash: "4c".repeat(32),
  currency: "GBP",
  params: { horizon_days: 90, paths: 500, seed: 1729 },
  result: { min_balance_p50_minor: balanceOn("2026-11-26") },
});

// ---------------------------------------------------------------------------------------------
// Event scripts for the run stream (what the backend would send, in order).

export type ScriptEvent = { event: string; data: Record<string, unknown>; delayMs: number };

const step = (n: number, agent: string, label: string, status: string, extra: Record<string, unknown> = {}) => ({
  step_id: uid("step", n),
  agent,
  label,
  status,
  ...extra,
});

export function answerScript(response: AgentResponse, standalone: string): ScriptEvent[] {
  const t = (s: number) => `2026-10-12T09:14:0${s}Z`;
  const rejected = (response.evidence_line?.rejected_drafts ?? 0) > 0;
  return [
    { event: "run.started", data: { standalone_question: standalone, at: t(2) }, delayMs: 150 },
    { event: "step", data: step(1, "coordinator", "Understanding your question", "started", { at: t(2) }), delayMs: 250 },
    { event: "step", data: step(1, "coordinator", "Understood your question", "done", { at: t(2) }), delayMs: 350 },
    { event: "step", data: step(2, "ledger", "Read your transactions", "done", { at: t(3) }), delayMs: 350 },
    { event: "step", data: step(3, "forecaster", "Built your forecast", "done", { at: t(4) }), delayMs: 450 },
    ...(rejected
      ? [
          { event: "step", data: step(4, "verifier", "Verifier rejected a draft", "rejected", { reason: "“Pay on 4 Dec”: below your buffer before payday", at: t(6) }), delayMs: 450 },
          { event: "step", data: step(5, "advisor", "Revised: pay after 27 Nov", "revised", { at: t(6) }), delayMs: 350 },
        ]
      : []),
    { event: "step", data: step(6, "verifier", "Checked", "done", { at: t(8) }), delayMs: 400 },
    { event: "answer", data: { rsp_id: response.response_id, snapshot: response }, delayMs: 200 },
  ];
}

export const clarifyScript = (): ScriptEvent[] => [
  { event: "run.started", data: { standalone_question: null }, delayMs: 150 },
  { event: "step", data: step(1, "coordinator", "Understood your question", "done"), delayMs: 300 },
  {
    event: "clarify",
    data: { question: clarifyingBlock.question, options: clarifyingBlock.options },
    delayMs: 200,
  },
];

export const errorScript = (partial: AgentResponse | null = null): ScriptEvent[] => [
  { event: "run.started", data: { standalone_question: "How does next month look?" }, delayMs: 150 },
  { event: "step", data: step(1, "coordinator", "Understood your question", "done"), delayMs: 300 },
  { event: "step", data: step(2, "forecaster", "Building your forecast", "started"), delayMs: 300 },
  {
    event: "error",
    data: { code: "engine_timeout", retryable: true, partial_rsp_id: partial ? partial.response_id : null },
    delayMs: 600,
  },
];

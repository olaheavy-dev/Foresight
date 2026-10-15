"use client";

/**
 * Decision Lab (review R8; docs/01 F-30): test a decision before making it. One change at a time,
 * built from the profile's own bills, income and categories, run through the engine on the same
 * simulated paths as the forecast (deterministic, no AI). The result is the same comparison block
 * the Workspace shows; anything the engine can't simulate comes back with its reason.
 */
import { type FormEvent, useEffect, useId, useState } from "react";

import { Button, CardHead } from "@/components/ui/primitives";
import { categoryName } from "@/components/transactions/Transactions";
import { BlockEnvProvider, ScenarioBlock } from "@/components/workspace/blocks";
// The blocks reused from the Workspace bring their styles with them.
import "@/components/workspace/workspace.css";
import { fetchCategories, fetchDetected, simulateWithReason } from "@/lib/api";
import { parseAmountMinor } from "@/lib/format";
import type {
  CategoryOption,
  DetectedFlows,
  ScenarioComparison,
  ScenarioModifierSpec,
  SimulationView,
} from "@/ui-contracts/types";

type Kind = "purchase" | "spread" | "cancel" | "cut" | "income" | "late";

const KINDS: { id: Kind; label: string; hint: string }[] = [
  { id: "purchase", label: "A one-off purchase", hint: "Can I afford it, and when?" },
  { id: "spread", label: "Spread a purchase", hint: "Pay in instalments instead" },
  { id: "cancel", label: "Cancel a regular payment", hint: "From one of your bills" },
  { id: "cut", label: "Spend less on something", hint: "Cut a category by a share" },
  { id: "income", label: "My income changes", hint: "A raise or a pay cut" },
  { id: "late", label: "My next pay arrives late", hint: "Only the next payday moves" },
];

const DEFAULT_HORIZON = 90;
const MAX_HORIZON = 365;
const CADENCE_DAYS: Record<string, number> = { weekly: 7, fortnightly: 14, monthly: 31 };

/** A forecast long enough to include a spread purchase's last payment; null past a year. */
export function spreadHorizon(start: string, instalments: number, cadence: string, today = new Date()): number | null {
  const first = new Date(`${start}T00:00:00`);
  const days = Math.ceil((first.getTime() - today.getTime()) / 86_400_000);
  const last = days + (instalments - 1) * (CADENCE_DAYS[cadence] ?? 31) + 7;
  if (last > MAX_HORIZON) return null;
  return Math.max(DEFAULT_HORIZON, last);
}

const isoInDays = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString("en-CA"); // YYYY-MM-DD in the browser's zone
};

export function DecisionLab({ currency, locale, timeZone }: { currency: string; locale: string; timeZone: string }) {
  const id = useId();
  const [kind, setKind] = useState<Kind>("purchase");
  const [flows, setFlows] = useState<DetectedFlows | null>(null);
  const [categories, setCategories] = useState<CategoryOption[]>([]);
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(isoInDays(14));
  const [instalments, setInstalments] = useState("3");
  const [cadence, setCadence] = useState("monthly");
  const [recurring, setRecurring] = useState("");
  const [category, setCategory] = useState("");
  const [pct, setPct] = useState("20");
  const [stream, setStream] = useState("");
  const [days, setDays] = useState("5");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [result, setResult] = useState<{ view: SimulationView; name: string } | null>(null);

  useEffect(() => {
    void fetchDetected().then((f) => {
      setFlows(f);
      setRecurring(f?.recurring[0]?.recurring_id ?? "");
      setStream(f?.income.find((s) => (s.provenance as string) !== "rejected")?.income_stream_id ?? "");
    });
    void fetchCategories().then((c) => {
      const spend = (c?.categories ?? []).filter((x) => x.flow_kind === "spend");
      setCategories(spend);
      setCategory(spend.find((x) => x.key === "food.delivery")?.key ?? spend[0]?.key ?? "");
    });
  }, []);

  // Income the user said isn't income (R4) can't be changed or delayed.
  const income = (flows?.income ?? []).filter((s) => (s.provenance as string) !== "rejected");

  const build = (): { name: string; modifier: ScenarioModifierSpec; horizon?: number } | string => {
    const minor = parseAmountMinor(amount, currency);
    switch (kind) {
      case "purchase":
        if (!minor || minor <= 0) return "Enter an amount, like 450 or 450.00.";
        return {
          name: "One-off purchase",
          modifier: { type: "one_off_outflow", date, amount_minor: minor, label: "Purchase" },
        };
      case "spread":
        if (!minor || minor <= 0) return "Enter the total amount, like 900.";
        if (spreadHorizon(date, Number(instalments), cadence) === null)
          return "That plan runs past the year the forecast covers. Choose fewer payments or a shorter gap.";
        return {
          name: `Spread over ${instalments} payments`,
          modifier: {
            type: "split_outflow",
            date,
            amount_minor: minor,
            instalments: Number(instalments),
            cadence,
            label: "Purchase",
          },
          horizon: spreadHorizon(date, Number(instalments), cadence) ?? undefined,
        };
      case "cancel":
        if (!recurring) return "There are no regular payments to cancel yet.";
        return {
          name: "Cancel a regular payment",
          modifier: { type: "recurring_cancel", recurring_id: recurring, from_date: date },
        };
      case "cut":
        if (!category) return "Choose a category.";
        return {
          name: `Spend ${pct}% less`,
          modifier: { type: "category_cut_pct", category_key: category, pct: Number(pct) },
        };
      case "income":
        if (!stream) return "There's no regular income to change yet.";
        return {
          name: `Income ${Number(pct) >= 0 ? "+" : ""}${pct}%`,
          modifier: { type: "income_change_pct", income_stream_id: stream, pct: Number(pct) },
        };
      case "late":
        if (!stream) return "There's no regular income to delay yet.";
        return {
          name: `Next pay ${days} days late`,
          modifier: { type: "income_delay", income_stream_id: stream, days: Number(days), occurrences: 1 },
        };
    }
  };

  const run = async (e: FormEvent) => {
    e.preventDefault();
    setResult(null); // a new run never shows the last one's figures beside its own outcome
    const built = build();
    if (typeof built === "string") {
      setProblem(built);
      return;
    }
    setBusy(true);
    setProblem(null);
    const outcome = await simulateWithReason({
      schema: "scenario_spec/1",
      name: built.name,
      scope: "mine",
      currency,
      modifiers: [built.modifier],
      ...(built.horizon ? { horizon_days: built.horizon } : {}),
    });
    setBusy(false);
    if (!outcome) setProblem("The simulation couldn’t run just now. Try again.");
    else if ("error" in outcome) setProblem(outcome.error);
    else setResult({ view: outcome.view, name: built.name });
  };

  const choose = (next: Kind) => {
    setKind(next);
    setProblem(null);
    if (next === "income") setPct("-10");
    if (next === "cut") setPct("20");
  };

  const block: ScenarioComparison | null = result
    ? {
        ...result.view.comparison,
        type: "ScenarioComparison",
        block_id: "lab-result",
        title: result.name,
        currency: result.view.currency,
        placement: { area: "overview", slot: "main_visual" },
      }
    : null;

  return (
    <div className="lab">
      <section className="card lab-form" aria-labelledby={`${id}-h`}>
        <CardHead
          icon="flask"
          title="What do you want to test?"
          titleId={`${id}-h`}
          sub="One change, on the same simulated paths as your forecast."
        />
        <div className="lab-kinds" role="radiogroup" aria-label="Kind of change">
          {KINDS.map((k) => (
            <label key={k.id} className={`lab-kind${kind === k.id ? " on" : ""}`}>
              <input type="radio" name={`${id}-kind`} checked={kind === k.id} onChange={() => choose(k.id)} />
              <span className="lab-kind-label">{k.label}</span>
              <span className="lab-kind-hint">{k.hint}</span>
            </label>
          ))}
        </div>

        <form className="lab-fields" onSubmit={run} aria-label="Scenario details">
          {kind === "purchase" || kind === "spread" ? (
            <Field id={`${id}-amount`} label={kind === "spread" ? "Total amount" : "Amount"}>
              <input
                id={`${id}-amount`}
                inputMode="decimal"
                placeholder="450.00"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
            </Field>
          ) : null}
          {kind === "purchase" || kind === "spread" || kind === "cancel" ? (
            <Field
              id={`${id}-date`}
              label={kind === "cancel" ? "Cancel from" : kind === "spread" ? "First payment" : "Date"}
            >
              <input id={`${id}-date`} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </Field>
          ) : null}
          {kind === "spread" ? (
            <>
              <Field id={`${id}-n`} label="Payments">
                <select id={`${id}-n`} value={instalments} onChange={(e) => setInstalments(e.target.value)}>
                  {[2, 3, 4, 6, 12].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id={`${id}-cad`} label="Every">
                <select id={`${id}-cad`} value={cadence} onChange={(e) => setCadence(e.target.value)}>
                  <option value="monthly">Month</option>
                  <option value="fortnightly">Two weeks</option>
                  <option value="weekly">Week</option>
                </select>
              </Field>
            </>
          ) : null}
          {kind === "cancel" ? (
            <Field id={`${id}-rec`} label="Regular payment">
              <select id={`${id}-rec`} value={recurring} onChange={(e) => setRecurring(e.target.value)}>
                {(flows?.recurring ?? []).map((r) => (
                  <option key={r.recurring_id} value={r.recurring_id}>
                    {r.label} · {r.amount.display}
                  </option>
                ))}
              </select>
            </Field>
          ) : null}
          {kind === "cut" ? (
            <>
              <Field id={`${id}-cat`} label="Category">
                <select id={`${id}-cat`} value={category} onChange={(e) => setCategory(e.target.value)}>
                  {categories.map((c) => (
                    <option key={c.key} value={c.key}>
                      {categoryName(c.key)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id={`${id}-pct`} label="Spend less by">
                <select id={`${id}-pct`} value={pct} onChange={(e) => setPct(e.target.value)}>
                  {[10, 20, 30, 50, 75, 100].map((n) => (
                    <option key={n} value={n}>
                      {n}%
                    </option>
                  ))}
                </select>
              </Field>
            </>
          ) : null}
          {kind === "income" || kind === "late" ? (
            <Field id={`${id}-inc`} label="Income">
              <select id={`${id}-inc`} value={stream} onChange={(e) => setStream(e.target.value)}>
                {income.map((s) => (
                  <option key={s.income_stream_id} value={s.income_stream_id}>
                    {s.source} · {s.amount.display}
                  </option>
                ))}
              </select>
            </Field>
          ) : null}
          {kind === "income" ? (
            <Field id={`${id}-chg`} label="Change">
              <select id={`${id}-chg`} value={pct} onChange={(e) => setPct(e.target.value)}>
                {[-50, -25, -10, 5, 10, 20].map((n) => (
                  <option key={n} value={n}>
                    {n > 0 ? `+${n}` : n}%
                  </option>
                ))}
              </select>
            </Field>
          ) : null}
          {kind === "late" ? (
            <Field id={`${id}-days`} label="Days late">
              <select id={`${id}-days`} value={days} onChange={(e) => setDays(e.target.value)}>
                {[2, 3, 5, 7, 10, 14].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </Field>
          ) : null}
          <div className="lab-actions">
            <Button type="submit" variant="primary" disabled={busy} iconEnd="arrowright">
              {busy ? "Running the simulation…" : "Test it"}
            </Button>
          </div>
          {problem ? (
            <p className="form-error" role="alert">
              {problem}
            </p>
          ) : null}
        </form>
      </section>

      {block ? (
        <section className="lab-result ws-body block-host" aria-label="Result" aria-live="polite">
          <BlockEnvProvider value={{ currency, locale, timeZone, checkedAdvice: false, ask: () => {} }}>
            <ScenarioBlock block={block} />
          </BlockEnvProvider>
          <p className="lab-note">
            Calculated by the forecast engine on the same simulated paths as your current forecast, so the difference is
            this change alone. No AI was used.
          </p>
        </section>
      ) : null}
    </div>
  );
}

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="field lab-field">
      <label htmlFor={id}>{label}</label>
      {children}
    </div>
  );
}

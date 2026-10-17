"use client";

/**
 * Goals (docs/01 F-55; docs/07 §6.7): save by a date from what's left above the buffer, projected
 * on the same simulated paths as the forecast. Each goal shows the Workspace's goal block (every
 * figure from the engine's stored calculation); a goal that can't be projected says why. No AI is
 * used, and goals don't yet get their own advice.
 */
import { type FormEvent, useEffect, useId, useState } from "react";

import { Button, CardHead } from "@/components/ui/primitives";
import { BlockEnvProvider, GoalBlock } from "@/components/workspace/blocks";
import "@/components/workspace/workspace.css";
import { createGoal, fetchGoals, type GoalOutcome, updateGoal } from "@/lib/api";
import { formatLongDate, minorDigits, parseAmountMinor, toMajor } from "@/lib/format";
import type { GoalView } from "@/ui-contracts/types";

const isoInMonths = (months: number) => {
  const d = new Date();
  d.setMonth(d.getMonth() + months);
  return d.toLocaleDateString("en-CA"); // YYYY-MM-DD in the browser's zone
};

type Draft = { name: string; amount: string; date: string };

function GoalForm({
  id,
  currency,
  initial,
  submit,
  cancel,
  label,
}: {
  id: string;
  currency: string;
  initial: Draft;
  submit: (d: { name: string; targetMinor: number; targetDate: string }) => Promise<string | null>;
  cancel?: () => void;
  label: string;
}) {
  const [draft, setDraft] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const minor = parseAmountMinor(draft.amount, currency);
    if (!draft.name.trim()) return setProblem("Give the goal a name, like “Trip home”.");
    if (!minor || minor <= 0) return setProblem("Enter the amount to save, like 1500 or 1500.00.");
    if (!draft.date) return setProblem("Choose the date you want it by.");
    setBusy(true);
    setProblem(null);
    const failed = await submit({ name: draft.name.trim(), targetMinor: minor, targetDate: draft.date });
    setBusy(false);
    setProblem(failed);
    if (!failed && !cancel) setDraft(initial); // a new goal was added: the form starts again
  };

  return (
    <form className="goal-form" onSubmit={onSubmit} aria-label={label}>
      {/* Locked while the engine projects it, so the result is for what the form shows. */}
      <fieldset className="lab-fields" disabled={busy}>
        <legend className="sr-only">{label}</legend>
        <div className="field lab-field">
          <label htmlFor={`${id}-name`}>Goal</label>
          <input
            id={`${id}-name`}
            maxLength={80}
            placeholder="Trip home"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
        </div>
        <div className="field lab-field">
          <label htmlFor={`${id}-amount`}>Amount ({currency})</label>
          <input
            id={`${id}-amount`}
            inputMode="decimal"
            placeholder="1500.00"
            value={draft.amount}
            onChange={(e) => setDraft({ ...draft, amount: e.target.value })}
          />
        </div>
        <div className="field lab-field">
          <label htmlFor={`${id}-date`}>By</label>
          <input
            id={`${id}-date`}
            type="date"
            value={draft.date}
            onChange={(e) => setDraft({ ...draft, date: e.target.value })}
          />
        </div>
        <div className="lab-actions btns">
          <Button type="submit" variant="primary" disabled={busy}>
            {busy ? "Projecting…" : label}
          </Button>
          {cancel ? (
            <Button type="button" disabled={busy} onClick={cancel}>
              Cancel
            </Button>
          ) : null}
        </div>
        {problem ? (
          <p className="form-error" role="alert">
            {problem}
          </p>
        ) : null}
      </fieldset>
    </form>
  );
}

export function Goals({ currency, locale, timeZone }: { currency: string; locale: string; timeZone: string }) {
  const id = useId();
  const [goals, setGoals] = useState<GoalView[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [actionProblem, setActionProblem] = useState<string | null>(null);

  useEffect(() => {
    void fetchGoals().then((list) => {
      if (list) setGoals(list.goals);
      else setFailed(true);
    });
  }, []);

  const replace = (goal: GoalView) =>
    setGoals((all) =>
      goal.status === "abandoned"
        ? (all ?? []).filter((g) => g.goal_id !== goal.goal_id)
        : (all ?? []).map((g) => (g.goal_id === goal.goal_id ? goal : g)),
    );
  // Goals share one pool of spare cash, funded in date order: a change to one moves what's set
  // aside for the others, so every projection is read again (#54 review).
  const refresh = () =>
    void fetchGoals().then((list) => {
      if (list) setGoals(list.goals);
    });

  const reason = (outcome: GoalOutcome | null) =>
    !outcome ? "That couldn’t be saved just now. Please try again." : "error" in outcome ? outcome.error : null;

  const add = async (d: { name: string; targetMinor: number; targetDate: string }) => {
    const outcome = await createGoal(d);
    if (outcome && "goal" in outcome) {
      setGoals((all) => [...(all ?? []), outcome.goal]);
      refresh();
    }
    return reason(outcome);
  };

  const edit = (goal: GoalView) => async (d: { name: string; targetMinor: number; targetDate: string }) => {
    const outcome = await updateGoal(goal.goal_id, d);
    if (outcome && "goal" in outcome) {
      replace(outcome.goal);
      setEditing(null);
      refresh();
    }
    return reason(outcome);
  };

  const setStatus = async (goal: GoalView, status: GoalView["status"]) => {
    setActionProblem(null);
    const outcome = await updateGoal(goal.goal_id, { status });
    if (outcome && "goal" in outcome) {
      replace(outcome.goal);
      refresh();
    } else setActionProblem(reason(outcome));
  };

  const env = { currency, locale, timeZone, checkedAdvice: false, ask: () => {} };
  const active = (goals ?? []).filter((g) => g.status === "active");
  const achieved = (goals ?? []).filter((g) => g.status === "achieved");

  return (
    <section className="goals" aria-labelledby={`${id}-h`}>
      <div className="card lab-form">
        <CardHead
          icon="target"
          title="Goals"
          titleId={`${id}-h`}
          sub="Save by a date from what’s left above your buffer, checked against the same simulated paths as your forecast. No AI is used."
        />
        <GoalForm
          id={`${id}-new`}
          currency={currency}
          initial={{ name: "", amount: "", date: isoInMonths(6) }}
          submit={add}
          label="Add goal"
        />
      </div>

      {failed ? (
        <p className="form-error" role="alert">
          Your goals couldn’t load just now. Please reload the page.
        </p>
      ) : goals === null ? (
        <p className="lab-note" role="status">
          Projecting your goals…
        </p>
      ) : active.length === 0 ? (
        <p className="lab-note">
          {achieved.length
            ? "No goals in progress. Add another above to see how likely it is."
            : "No goals yet. Add one above to see how likely it is."}
        </p>
      ) : null}

      {actionProblem ? (
        <p className="form-error" role="alert">
          {actionProblem}
        </p>
      ) : null}

      {/* Reused Workspace blocks bring their styles with them (as in DecisionLab). */}
      <div className="ws-body block-host goal-list">
        <BlockEnvProvider value={env}>
          {active.map((goal) => (
            <div key={goal.goal_id} className="goal-item" role="region" aria-label={goal.name}>
              {goal.projection ? (
                <GoalBlock block={goal.projection} />
              ) : (
                <article className="card ws-card goal-problem">
                  <h3>{goal.name}</h3>
                  <p>
                    {goal.target.display} by {formatLongDate(goal.target_date, locale)}
                  </p>
                  <p className="lab-note">{goal.problem}</p>
                </article>
              )}
              {goal.reserved ? (
                <p className="lab-note">
                  After {goal.reserved.display} set aside for goals due earlier: goals share what’s spare, in date
                  order.
                </p>
              ) : null}
              {goal.lower_confidence ? (
                <p className="lab-note">More than 90 days out: the range is wider and less certain.</p>
              ) : null}
              {editing === goal.goal_id ? (
                <GoalForm
                  id={`${id}-${goal.goal_id}`}
                  currency={currency}
                  initial={{
                    name: goal.name,
                    amount: toMajor(goal.target.minor, currency).toFixed(minorDigits(currency)),
                    date: goal.target_date,
                  }}
                  submit={edit(goal)}
                  cancel={() => setEditing(null)}
                  label="Save changes"
                />
              ) : (
                <div className="btns goal-actions">
                  <Button onClick={() => setEditing(goal.goal_id)}>Edit</Button>
                  <Button onClick={() => void setStatus(goal, "achieved")}>Mark achieved</Button>
                  <Button onClick={() => void setStatus(goal, "abandoned")}>Archive</Button>
                </div>
              )}
            </div>
          ))}
        </BlockEnvProvider>
      </div>

      {achieved.length ? (
        <div className="card goal-done">
          <h3>Achieved</h3>
          <ul>
            {achieved.map((g) => (
              <li key={g.goal_id}>
                {g.name}: {g.target.display}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

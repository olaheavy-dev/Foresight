"use client";

/**
 * Evidence drawer (TASKS: "Evidence drawer"): opened from any citation [n] or entity chip, and
 * linkable as `?evidence=<ref>`. It shows what the answer itself carries about the reference
 * (evidence items, checks, the run) and, for a calculation, the stored record from
 * GET /api/calculations/{id}: kind, engine version, data version, inputs and result hashes, seed.
 * Anything not available is said plainly; nothing is reconstructed.
 */
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icons/Icon";
import { fetchCalculation, type ParsedResponse } from "@/lib/api";
import { formatClock, formatLongDate } from "@/lib/format";
import type { CalculationView, EvidenceItem } from "@/ui-contracts/types";
import { baseRef, blockRefs } from "./citations";

const KIND: Record<string, string> = {
  calc: "Calculation",
  fc: "Forecast",
  sim: "Simulation",
  scn: "Scenario",
  fnd: "Finding",
  rec: "Recommendation",
  ver: "Check by the Verifier",
  txn: "Transaction",
  run: "Agent run",
  goal: "Goal",
  rob: "Recurring bill",
  imp: "Import",
  inc: "Income stream",
};

/** fc_ and sim_ ids share the hash of the calculation that produced them (docs/07). */
function calcIdFor(ref: string): string | null {
  const base = baseRef(ref);
  const m = /^(calc|fc|sim)_([0-9a-f]{24}|[0-9A-HJKMNP-TV-Z]{26})$/.exec(base);
  return m ? `calc_${m[2]}` : null;
}

const short = (hash: string) => (hash.length > 16 ? `${hash.slice(0, 12)}…` : hash);

export function EvidenceDrawer({
  refId,
  response,
  locale,
  timeZone,
  onClose,
}: {
  refId: string;
  response: ParsedResponse | null;
  locale: string;
  timeZone: string;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const [calc, setCalc] = useState<CalculationView | null | "loading" | "missing">("loading");
  const base = baseRef(refId);
  const prefix = base.split("_")[0];
  const calcId = calcIdFor(base);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
  }, [onClose]);

  useEffect(() => {
    let live = true;
    if (!calcId) {
      setCalc("missing");
      return;
    }
    setCalc("loading");
    fetchCalculation(calcId).then((c) => {
      if (live) setCalc(c ?? "missing");
    });
    return () => {
      live = false;
    };
  }, [calcId]);

  const blocks = (response?.blocks ?? []).flatMap((b) => (b.ok ? [b.block] : []));
  const items: EvidenceItem[] = blocks.flatMap((b) => (b.type === "EvidencePanel" ? b.items.filter((i) => baseRef(i.ref) === base) : []));
  const usedBy = blocks.filter((b) => blockRefs(b).some((r) => baseRef(r) === base)).map((b) => b.title ?? b.type.replace(/([a-z])([A-Z])/g, "$1 $2"));
  const run = blocks.find((b) => b.type === "AgentExecutionTimeline" && b.run_id === base);

  return (
    <div className="drawer-scrim" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-h"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="drawer-head">
          <div>
            <p className="kicker">Evidence</p>
            <h2 id="drawer-h">{KIND[prefix] ?? "Reference"}</h2>
            <p className="ref">{refId}</p>
          </div>
          <button ref={closeRef} type="button" className="icon-btn" aria-label="Close evidence" onClick={onClose}>
            <Icon name="xcircle" />
          </button>
        </header>

        <div className="drawer-body">
          {items.map((item) => (
            <section key={item.ref} className="drawer-sec">
              <h3>{item.title}</h3>
              {item.summary_lines.map((l, i) => (
                <p key={i}>{l}</p>
              ))}
              {item.checks?.length ? (
                <ul className="checks">
                  {item.checks.map((c) => (
                    <li key={c.name} data-passed={c.passed}>
                      <Icon name={c.passed ? "check" : "xcircle"} />
                      <span className="sr-only">{c.passed ? "Passed: " : "Failed: "}</span>
                      {c.name}
                      {c.kind ? <span className="faint"> · {c.kind === "model" ? "model check" : "computed check"}</span> : null}
                      {c.detail ? <span className="faint"> · {c.detail}</span> : null}
                    </li>
                  ))}
                </ul>
              ) : null}
              {item.reproducible ? (
                <dl className="facts-dl">
                  <dt>Data version</dt>
                  <dd>{item.reproducible.data_version}</dd>
                  <dt>Inputs</dt>
                  <dd className="mono">{short(item.reproducible.inputs_hash)}</dd>
                  {item.reproducible.seed != null ? (
                    <>
                      <dt>Seed</dt>
                      <dd className="mono">{item.reproducible.seed}</dd>
                    </>
                  ) : null}
                </dl>
              ) : null}
            </section>
          ))}

          {run && run.type === "AgentExecutionTimeline" ? (
            <section className="drawer-sec">
              <h3>Agent run</h3>
              <p>
                {run.steps.length} logged steps. The full record is in “How it was checked”.
              </p>
            </section>
          ) : null}

          {calcId ? (
            <section className="drawer-sec">
              <h3>Stored calculation</h3>
              {calc === "loading" ? (
                <p className="faint">Loading the stored record…</p>
              ) : calc === "missing" ? (
                <p className="faint">The stored record isn’t available right now.</p>
              ) : calc ? (
                <dl className="facts-dl">
                  <dt>What</dt>
                  <dd>{calc.kind.replace(/_/g, " ")}</dd>
                  {refId.includes("#") ? (
                    <>
                      <dt>Figure</dt>
                      <dd className="mono">{refId.split("#")[1]}</dd>
                    </>
                  ) : null}
                  <dt>Computed</dt>
                  <dd>
                    {formatLongDate(calc.created_at.slice(0, 10), locale)} {formatClock(calc.created_at, locale, timeZone)}
                  </dd>
                  <dt>Engine</dt>
                  <dd>{calc.engine_version}</dd>
                  <dt>Data version</dt>
                  <dd>{calc.data_version}</dd>
                  {"seed" in (calc.params as Record<string, unknown>) ? (
                    <>
                      <dt>Seed</dt>
                      <dd className="mono">{String((calc.params as Record<string, unknown>).seed)}</dd>
                    </>
                  ) : null}
                  <dt>Inputs hash</dt>
                  <dd className="mono">{short(calc.inputs_hash)}</dd>
                  <dt>Result hash</dt>
                  <dd className="mono">{short(calc.result_hash)}</dd>
                </dl>
              ) : null}
              <p className="faint">The same inputs always give the same result: rerun it and the result hash matches.</p>
            </section>
          ) : null}

          {!items.length && !calcId && !run ? (
            <section className="drawer-sec">
              <p>The full record for this item isn’t available in the Workspace yet.</p>
            </section>
          ) : null}

          {usedBy.length ? (
            <section className="drawer-sec">
              <h3>Used in this answer</h3>
              <ul className="used-by">
                {usedBy.map((t, i) => (
                  <li key={i}>{t}</li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

"use client";

/**
 * Home · Proactive insights (review R2, docs/01 PRO-01). Findings come straight from the engine
 * (every figure from a stored calculation); recommendations are the cards the Verifier approved
 * in the latest proactive check, the same card the Workspace shows. While a check runs the card
 * polls; when advice can't run it says why instead of showing nothing.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Icon } from "@/components/icons/Icon";
import { Badge, Button, CardHead } from "@/components/ui/primitives";
import { BlockEnvProvider, InterventionBlock } from "@/components/workspace/blocks";
// The blocks reused from the Workspace bring their styles with them.
import "@/components/workspace/workspace.css";
import { fetchHomeInsights, startProactiveCheck } from "@/lib/api";
import type { HomeInsights, InsightFinding } from "@/ui-contracts/types";

const POLL_MS = 4000;
const POLL_LIMIT = 60; // about four minutes, longer than a run's deadline

const SEVERITY: Record<InsightFinding["severity"], { tone: "red" | "amber" | "grey"; word: string }> = {
  act: { tone: "red", word: "Act" },
  watch: { tone: "amber", word: "Watch" },
  info: { tone: "grey", word: "Note" },
};

function statusLine(insights: HomeInsights, demo: boolean): string {
  switch (insights.status) {
    case "checking":
      return "Checking your latest changes. Findings first, then advice the Verifier has checked.";
    case "ready":
      return (insights.checked_data_version ?? 0) < insights.data_version
        ? "Your data changed since the last check; these may be out of date."
        : "Checked against your latest data.";
    case "paused":
      return insights.reason === "daily_limit"
        ? "Today’s proactive checks are used. The findings below stay up to date."
        : "Checked advice is paused right now. The findings below come straight from your data.";
    case "failed":
      return "The last check didn’t finish. The findings below come straight from your data.";
    default:
      if (!demo) return "Findings and checked advice appear here after you import a statement or change a category.";
      return insights.can_check
        ? "These findings come straight from the demo’s data. Run the proactive check to see advice the Verifier has checked."
        : "These findings come straight from the demo’s data. Checked advice is paused right now.";
  }
}

export function ProactiveInsights({
  initial,
  demo,
  currency,
  locale,
  timeZone,
  checkedAdvice,
}: {
  initial: HomeInsights;
  demo: boolean;
  currency: string;
  locale: string;
  timeZone: string;
  checkedAdvice: boolean;
}) {
  const [insights, setInsights] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [refused, setRefused] = useState<string | null>(null); // a limit a retry can't clear

  const refresh = useCallback(async () => {
    const next = await fetchHomeInsights();
    if (next) setInsights(next);
  }, []);

  useEffect(() => {
    if (insights.status !== "checking") return;
    let polls = 0;
    const t = setInterval(() => {
      polls += 1;
      if (polls > POLL_LIMIT) clearInterval(t);
      else void refresh();
    }, POLL_MS);
    return () => clearInterval(t);
  }, [insights.status, refresh]);

  const check = async () => {
    setBusy(true);
    setFailed(false);
    const next = await startProactiveCheck();
    setBusy(false);
    if (next && "refused" in next) setRefused(next.refused);
    else if (next) setInsights(next);
    else setFailed(true);
  };

  const env = { currency, locale, timeZone, checkedAdvice, ask: () => {} };
  const findings = insights.findings ?? [];
  const cards = insights.recommendations ?? [];
  return (
    <section className="card insights" aria-labelledby="insights-h">
      <CardHead
        icon="sparkles"
        title="Proactive insights"
        titleId="insights-h"
        sub="Found in your data and, where it applies, advice checked before you see it."
      />
      <p className="insights-status" aria-live="polite">
        {insights.status === "checking" ? <span className="spinner" aria-hidden="true" /> : null}
        {statusLine(insights, demo)}
      </p>

      {findings.length ? (
        <ul className="insight-list" aria-label="Findings">
          {findings.map((f) => (
            <li key={f.finding_id} className="insight">
              <Badge tone={SEVERITY[f.severity].tone}>{SEVERITY[f.severity].word}</Badge>
              <div>
                <p className="insight-headline">{f.headline}</p>
                {f.detail ? <p className="insight-detail">{f.detail}</p> : null}
                {f.link ? (
                  <Link className="insight-link" href={f.link}>
                    See the transactions <Icon name="arrowright" />
                  </Link>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : insights.status !== "checking" ? (
        <p className="insights-empty">Nothing stands out in your data right now.</p>
      ) : null}

      {cards.length && checkedAdvice ? (
        <div className="insight-recs ws-body block-host">
          <h3 className="insight-recs-h">Checked advice</h3>
          <BlockEnvProvider value={env}>
            {cards.map((card) => (
              <InterventionBlock key={card.recommendation_id} block={card} />
            ))}
          </BlockEnvProvider>
        </div>
      ) : null}

      {insights.can_check && insights.status !== "ready" && !refused ? (
        <div className="btns">
          <Button variant="primary" onClick={check} disabled={busy} iconEnd="arrowright">
            {busy
              ? "Starting the check…"
              : insights.status === "failed"
                ? "Try the check again"
                : "Run the proactive check"}
          </Button>
        </div>
      ) : null}
      {refused ? (
        // A limit (the network's day, or the profile's) that a retry can't clear: say why, no button.
        <p className="form-error" role="alert">
          {refused}
        </p>
      ) : failed ? (
        <p className="form-error" role="alert">
          The check couldn’t be started. Please try again.
        </p>
      ) : null}
    </section>
  );
}

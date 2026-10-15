"use client";

/**
 * The user's word on a detected income stream (review R4): confirm it, say it isn't income (the
 * forecast stops counting it), or undo either. Used on the import check step and on
 * Transactions › Recurring and income.
 */
import { useState } from "react";

import { Badge } from "@/components/ui/primitives";
import { decideIncome } from "@/lib/api";
import type { IncomeStreamView } from "@/ui-contracts/types";

const STATE: Record<IncomeStreamView["provenance"], { tone: "grey" | "green" | "blue"; word: string }> = {
  detected: { tone: "grey", word: "Detected" },
  confirmed: { tone: "green", word: "Confirmed by you" },
  declared: { tone: "blue", word: "Added by you" },
  rejected: { tone: "grey", word: "Not counted as income" },
};

export function IncomeControls({
  stream,
  readOnly = false,
  onChange,
}: {
  stream: IncomeStreamView;
  readOnly?: boolean;
  onChange: (next: IncomeStreamView) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const state = STATE[stream.provenance];

  const decide = async (decision: "confirm" | "reject" | "undo") => {
    setBusy(true);
    setFailed(false);
    const next = await decideIncome(stream.income_stream_id, decision);
    setBusy(false);
    if (next) onChange(next);
    else setFailed(true);
  };

  return (
    <div className="income-controls" role="group" aria-label={`Is ${stream.source} your income?`}>
      <Badge tone={state.tone}>{state.word}</Badge>
      {readOnly || stream.provenance === "declared" ? null : stream.provenance === "detected" ? (
        <>
          <button type="button" className="btn sm" disabled={busy} onClick={() => decide("confirm")}>
            Yes, it’s my income
          </button>
          <button type="button" className="btn sm" disabled={busy} onClick={() => decide("reject")}>
            Not income
          </button>
        </>
      ) : (
        <button type="button" className="link-btn" disabled={busy} onClick={() => decide("undo")}>
          Undo
        </button>
      )}
      {failed ? (
        <span className="form-error" role="alert">
          That didn’t save. Try again.
        </span>
      ) : null}
    </div>
  );
}

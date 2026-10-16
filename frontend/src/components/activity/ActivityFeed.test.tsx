import { render, screen, within } from "@testing-library/react";

import type { ActivityFeed as Feed } from "@/ui-contracts/types";

import { ActivityFeed } from "./ActivityFeed";

const U = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
export const ACTIVITY_FIXTURE: Feed = {
  workspace_id: `wsp_${U}`,
  audit_events: 12,
  audit_chain_intact: true,
  runs: [
    {
      run_id: `run_${U}`,
      workflow: "recommendation",
      trigger: "user",
      status: "succeeded",
      question: "Can I afford a £600 laptop next week?",
      started_at: "2026-10-15T09:12:00Z",
      duration_ms: 21400,
      llm_calls: 3,
      tokens_in: 5200,
      tokens_out: 1100,
      cost_usd: 0.041,
      revisions: 1,
      approved: 1,
      rejected: 1,
      steps: [
        {
          seq: 1,
          node: "understand",
          agent: "coordinator",
          kind: "llm",
          label: "Understanding the question",
          model: "openai/gpt-6-luna",
          status: "ok",
          latency_ms: 1800,
          tokens_in: 900,
          tokens_out: 120,
          cost_usd: 0.0009,
        },
        {
          seq: 2,
          node: "simulate",
          agent: "forecaster",
          kind: "tool",
          label: "Simulating the purchase",
          status: "ok",
          latency_ms: 640,
        },
        {
          seq: 3,
          node: "advise",
          agent: "advisor",
          kind: "llm",
          label: "Drafting advice",
          model: "anthropic/claude-sonnet-5.5",
          status: "retried",
          latency_ms: 11800,
          tokens_in: 3400,
          tokens_out: 800,
          cost_usd: 0.032,
        },
      ],
    },
  ],
  events: [
    {
      seq: 12,
      occurred_at: "2026-10-15T09:10:00Z",
      actor: "user",
      action: "txn.recategorised",
      summary: "Changed the category of 23 transactions",
    },
    {
      seq: 3,
      occurred_at: "2026-10-14T18:00:00Z",
      actor: "system",
      action: "import.committed",
      summary: "Imported a table of transactions",
    },
  ],
};

describe("ActivityFeed", () => {
  it("shows each run as a trace: steps, models, time, cost and the Verifier's verdicts", () => {
    render(<ActivityFeed feed={ACTIVITY_FIXTURE} locale="en-GB" timeZone="Europe/London" />);
    expect(screen.getByText("Advised on a question")).toBeInTheDocument();
    expect(screen.getByText(/1 checked · 1 rejected/)).toBeInTheDocument();
    const steps = screen.getByRole("table");
    expect(within(steps).getByText("anthropic/claude-sonnet-5.5")).toBeInTheDocument();
    expect(within(steps).getByText("no model")).toBeInTheDocument();
    expect(within(steps).getByText(/retried/)).toBeInTheDocument();
    expect(screen.getByText(/Audit chain intact · 12 entries/)).toBeInTheDocument();
    // Costs are estimates (usage × catalogue prices), never shown as a bill (docs/00 §7).
    expect(screen.getByText("about $0.041")).toBeInTheDocument();
    expect(within(steps).getByRole("columnheader", { name: "Est. cost" })).toBeInTheDocument();
    expect(screen.getByText("Changed the category of 23 transactions")).toBeInTheDocument();
  });
});

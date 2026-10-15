import { render, screen } from "@testing-library/react";
import { CoreMetrics, type CoreMetricsData } from "./CoreMetrics";

const data: CoreMetricsData = {
  run_id: "evalrun_x",
  gate: "fail",
  tiers: [
    {
      tier: "verifier",
      models: ["anthropic/claude-sonnet-5.5"],
      accuracy_gates: { "E-VER": "pass" },
      accuracy_pass: true,
      cost_per_answer_usd: 0.004,
      call_latency_p50_s: 4.8,
      call_latency_p95_s: null,
    },
  ],
  answers: [
    {
      type: "advice",
      label: "Advice answers",
      count: 9,
      cost_mean_usd: 0.02,
      cost_p95_usd: 0.03,
      latency_p50_s: 31,
      latency_p95_s: 61,
    },
  ],
  targets: [],
};

describe("CoreMetrics", () => {
  it("shows per-tier accuracy, cost and latency, and — for anything not measured", () => {
    render(<CoreMetrics data={data} />);
    expect(screen.getByRole("region", { name: /Core metrics/ })).toBeInTheDocument();
    expect(screen.getByText("anthropic/claude-sonnet-5.5")).toBeInTheDocument();
    expect(screen.getByText("E-VER passes")).toBeInTheDocument();
    expect(screen.getByText("4.8 s / —")).toBeInTheDocument();
    expect(screen.getByText("31.0 s · 61.0 s")).toBeInTheDocument();
    expect(screen.getByText(/checks: fails/)).toBeInTheDocument();
  });
});

describe("runLabel", () => {
  it("names the run by date and commit instead of its raw id", async () => {
    const { runLabel } = await import("./CoreMetrics");
    expect(runLabel("evalrun_20261014T124926Z_4c6fc75")).toBe("the evaluation run of 14 Oct 2026 (commit 4c6fc75)");
    expect(runLabel(null)).toBe("an evaluation run not recorded here");
  });
});

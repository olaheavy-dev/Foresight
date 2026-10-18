import { render, screen } from "@testing-library/react";
import { parseAgentResponse } from "@/lib/api";
import { affordabilityTimeline, everyBlock, spendingResponse } from "@/test/workspaceFixtures";
import type { Block } from "@/ui-contracts/types";
import { BlockEnvProvider, BlockResultView, BlockView, costLine } from "./blocks";
import { CitationProvider } from "./citations";

class RO {
  observe() {}
  disconnect() {}
}
beforeAll(() => {
  vi.stubGlobal("ResizeObserver", RO);
});

const env = { currency: "GBP", locale: "en-GB", timeZone: "Europe/London", ask: vi.fn(), checkedAdvice: true };

function renderBlock(block: Block, overrides: Partial<typeof env> = {}) {
  return render(
    <BlockEnvProvider value={{ ...env, ...overrides }}>
      <CitationProvider order={[]} open={() => {}} enabled={false}>
        <BlockView block={block} />
      </CitationProvider>
    </BlockEnvProvider>,
  );
}

describe("block renderers", () => {
  it.each(everyBlock().map((b) => [`${b.type} ${b.block_id}`, b] as const))(
    "%s renders from its contract without NaN",
    (_n, block) => {
      const { container } = renderBlock(block);
      expect(container.textContent).not.toMatch(/NaN|undefined|\[object Object\]/);
      for (const path of container.querySelectorAll("path")) expect(path.getAttribute("d") ?? "").not.toMatch(/NaN/);
      expect(container.firstChild).not.toBeNull();
    },
  );

  it("shows the server's display strings, never re-formatted figures", () => {
    const blocks = everyBlock();
    const metrics = blocks.find((b) => b.type === "FinancialMetricGroup");
    if (metrics?.type !== "FinancialMetricGroup") throw new Error("fixture");
    renderBlock(metrics);
    for (const m of metrics.metrics) expect(screen.getByText(m.value.display, { exact: false })).toBeInTheDocument();
  });

  it("hides checked advice when its flag is off, saying so honestly", () => {
    const card = everyBlock().find((b) => b.type === "InterventionCard")!;
    renderBlock(card, { checkedAdvice: false });
    expect(screen.getByText("Not shipped yet")).toBeInTheDocument();
    expect(screen.queryByText("Checked")).toBeNull();
  });

  it("a clarifying question offers its options as buttons that ask", () => {
    const ask = vi.fn();
    const q = everyBlock().find((b) => b.type === "ClarifyingQuestion")!;
    renderBlock(q, { ask });
    screen.getByRole("button", { name: "A monthly getaway" }).click();
    expect(ask).toHaveBeenCalledWith("Can I afford a short trip every month?");
  });

  it("an invalid block becomes a fallback tile in its place", () => {
    const raw = spendingResponse();
    const broken = { ...raw, blocks: [raw.blocks[0], { ...raw.blocks[2], series: "oops" }] };
    const parsed = parseAgentResponse(broken)!;
    expect(parsed.blocks[1].ok).toBe(false);
    render(
      <BlockEnvProvider value={env}>
        <BlockResultView result={parsed.blocks[1]} />
      </BlockEnvProvider>,
    );
    expect(screen.getByText("This part of the answer couldn’t be shown")).toBeInTheDocument();
  });
});

describe("cost line (How it was checked only)", () => {
  it("reports model calls, tokens, an estimated cost and the time", () => {
    expect(costLine(affordabilityTimeline)).toBe("7 model calls · 18,240 tokens · about $0.05 · 6.4 s");
  });

  it("says a cached answer used no model calls", () => {
    const cached = {
      ...affordabilityTimeline,
      duration_ms: 400,
      cost: { tokens: 0, model_calls: 0, usd_estimate: 0, cached: true },
    };
    expect(costLine(cached)).toBe("0 model calls · reused your earlier answer · 0.4 s");
  });
});

describe("the evidence chain in How it was checked (mandatory F)", () => {
  it("shows the Verifier's checks and the finding's transactions, file and link", () => {
    const U = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
    renderBlock({
      type: "EvidencePanel",
      block_id: "b9-evidence",
      title: "Where the numbers come from",
      placement: { area: "tab", tab: "checked" },
      items: [
        {
          ref: `ver_${U}`,
          kind: "verification",
          title: "How the Verifier checked it",
          provenance: "detected",
          summary_lines: ["Approved by the Verifier in round 2."],
          checks: [
            { name: "It's achievable, not too big a cut", passed: true, kind: "deterministic" },
            { name: "Its reasoning is grounded in the evidence", passed: true, kind: "model" },
          ],
        },
        {
          ref: `fnd_${U}`,
          kind: "finding",
          title: "Spending on food delivery is up 39% on usual",
          provenance: "detected",
          summary_lines: ["£286 in the month to 11 Oct (23 payments), against a usual £206."],
          inputs: { transaction_count: 23, date_range: { from: "2026-09-12", to: "2026-10-11" } },
          source_chain: {
            import_id: `imp_${U}`,
            filename: "monzo.csv",
            importer: "csv_statement",
            rows: "23 rows of this file",
            reconciliation: { status: "reconciled", method: "balances" },
          },
          link: "/transactions?category=food.delivery",
        },
      ],
    } as Block);
    expect(screen.getByText("It's achievable, not too big a cut")).toBeInTheDocument();
    expect(screen.getByText(/Based on 23 transactions, 12 Sept? 2026 to 11 Oct 2026/)).toBeInTheDocument();
    expect(screen.getByText("monzo.csv")).toBeInTheDocument();
    expect(screen.getByText("Every row adds up to the running balance")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /See these transactions/ })).toHaveAttribute(
      "href",
      "/transactions?category=food.delivery",
    );
  });
});

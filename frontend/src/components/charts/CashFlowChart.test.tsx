import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen } from "@testing-library/react";
import { forecastView } from "@/test/forecastFixture";
import type { CashFlowForecastData } from "@/ui-contracts/types";
import { CashFlowChart } from "./CashFlowChart";

class RO {
  observe() {}
  disconnect() {}
}
globalThis.ResizeObserver = globalThis.ResizeObserver ?? (RO as unknown as typeof ResizeObserver);

function noNaN(container: HTMLElement) {
  const attrs = ["x", "y", "x1", "x2", "y1", "y2", "cx", "cy", "points", "viewBox", "width", "height"];
  for (const el of Array.from(container.querySelectorAll("svg, svg *"))) {
    for (const a of attrs) {
      const v = el.getAttribute(a);
      if (v !== null) expect(v, `${el.tagName}[${a}]`).not.toMatch(/NaN|Infinity/);
    }
  }
}

describe("CashFlowChart", () => {
  it("renders the forecast with a generated description, markers and a data table", () => {
    const { container } = render(<CashFlowChart data={forecastView().chart} currency="GBP" />);
    const img = screen.getByRole("img");
    expect(img.getAttribute("aria-label")).toMatch(/first low is £\d/);
    expect(container.querySelectorAll(".cf-low")).toHaveLength(2);
    expect(container.querySelector(".cf-buffer")).not.toBeNull();
    expect(screen.getByRole("table", { hidden: true })).toBeInTheDocument();
    noNaN(container);
  });

  it("rings a low that falls below the buffer", () => {
    const view = forecastView({ buffer_minor: 400_000 });
    const { container } = render(<CashFlowChart data={view.chart} currency="GBP" />);
    expect(container.querySelectorAll(".cf-breach").length).toBeGreaterThan(0);
  });

  it("shows an honest empty state when there is nothing to draw", () => {
    const view = forecastView({ history: { dates: [], balance_minor: [] }, forecast: { dates: [], p10: [], p50: [], p90: [] }, pay_cycles: [] });
    render(<CashFlowChart data={view.chart} currency="GBP" />);
    expect(screen.getByRole("status")).toHaveTextContent(/isn’t enough data/i);
  });

  it.each(["02-holiday-affordability", "03-proactive-risk-alert"])(
    "draws the %s contract example without NaN",
    (name) => {
      const file = join(__dirname, "../../../../design/contracts", `${name}.json`);
      const response = JSON.parse(readFileSync(file, "utf8")).response as { blocks: Array<{ type: string }> };
      const block = response.blocks.find((b) => b.type === "CashFlowForecastChart") as unknown as CashFlowForecastData;
      const { container } = render(<CashFlowChart data={block} currency="GBP" />);
      noNaN(container);
    },
  );

  it("formats other currencies with their own minor units", () => {
    const view = forecastView();
    const { container } = render(<CashFlowChart data={view.chart} currency="JPY" locale="ja-JP" />);
    noNaN(container);
    expect(container.querySelector(".axis text")?.textContent).toMatch(/￥|¥/);
  });
});

import { fireEvent, render, screen, within } from "@testing-library/react";
import { parseAgentResponse } from "@/lib/api";
import { affordabilityResponse, degradedResponse, refusalResponse, spendingResponse } from "@/test/workspaceFixtures";
import type { AgentResponse } from "@/ui-contracts/types";
import { AnswerCanvas, layoutAnswer } from "./AnswerCanvas";
import { BlockEnvProvider } from "./blocks";

class RO {
  observe() {}
  disconnect() {}
}
beforeAll(() => vi.stubGlobal("ResizeObserver", RO));
beforeEach(() => window.history.replaceState(null, "", "/workspace"));

const env = { currency: "GBP", locale: "en-GB", timeZone: "Europe/London", ask: vi.fn(), checkedAdvice: true };

function show(raw: AgentResponse, { auditTrail = true, open = vi.fn() } = {}) {
  const response = parseAgentResponse(raw)!;
  render(
    <BlockEnvProvider value={env}>
      <AnswerCanvas response={response} liveSteps={[]} locale="en-GB" timeZone="Europe/London" auditTrail={auditTrail} openEvidence={open} />
    </BlockEnvProvider>,
  );
  return { response, open };
}

describe("answer skeleton (docs/08 §7a)", () => {
  it("uses the fixed tab names in the fixed order", () => {
    show(affordabilityResponse());
    const tabs = within(screen.getByRole("tablist", { name: "Analysis sections" })).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Overview", "Details", "Recommendation", "Transactions", "How it was checked"]);
  });

  it("hides an empty tab instead of reordering the rest", () => {
    show(spendingResponse());
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Overview", "Details", "Transactions", "How it was checked"]);
  });

  it("lays the Overview out in slot order: verdict, key numbers, main visual, what to do, evidence line", () => {
    const { response } = show(affordabilityResponse());
    const laid = layoutAnswer(response);
    expect(laid.overview.verdict).toHaveLength(1);
    expect(laid.overview.main_visual).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Yes, if you pay for it after your 27 November payday.");
    expect(screen.getByRole("button", { name: /Checked by 6 agents · 1 draft rejected/ })).toBeInTheDocument();
    expect(screen.getByText("Pay for the trip after your 27 November payday")).toBeInTheDocument();
  });

  it("shows cost and tokens only in How it was checked", () => {
    show(affordabilityResponse());
    const overview = screen.getByRole("tabpanel", { name: "Overview" });
    expect(within(overview).queryByText(/model calls|tokens/)).toBeNull();
    expect(screen.getByText(/model calls/)).not.toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "How it was checked" }));
    expect(screen.getByText(/7 model calls · 18,240 tokens · about \$0\.05 · 6\.4 s/)).toBeVisible();
    expect(screen.getByText("· estimated")).toBeVisible();
  });

  it("the evidence line opens the step checklist in place", () => {
    show(affordabilityResponse());
    const toggle = screen.getByRole("button", { name: /Checked by 6 agents/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("list", { name: "Steps behind this answer" })).toBeVisible();
  });
});

describe("citations [n]", () => {
  it("numbers sources in reading order and opens the Evidence drawer for the base reference", () => {
    const { open } = show(affordabilityResponse());
    const first = screen.getAllByRole("button", { name: /^Source 1:/ })[0];
    expect(first).toHaveTextContent("[1]");
    fireEvent.click(first);
    expect(open).toHaveBeenCalledWith(expect.stringMatching(/^calc_[0-9a-f]{24}$/));
  });

  it("are not shown when the audit trail is not shipped", () => {
    show(affordabilityResponse(), { auditTrail: false });
    expect(screen.queryByRole("button", { name: /^Source \d/ })).toBeNull();
  });
});

describe("other answer states", () => {
  it("a refusal is a calm scope statement with no tabs and no evidence line", () => {
    show(refusalResponse());
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("I can’t recommend investments.");
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryByText(/Checked by/)).toBeNull();
  });

  it("a degraded answer says AI explanations were unavailable and keeps the numbers", () => {
    show(degradedResponse());
    expect(screen.getByRole("status")).toHaveTextContent("AI explanations unavailable for part of this answer. The numbers are unaffected.");
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
  });
});

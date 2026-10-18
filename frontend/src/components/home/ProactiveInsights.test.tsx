import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";

import * as api from "@/lib/api";
import { tripCard } from "@/test/workspaceFixtures";

import type { HomeInsights } from "@/ui-contracts/types";

import { ProactiveInsights } from "./ProactiveInsights";

const U = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
const base: HomeInsights = {
  workspace_id: `wsp_${U}`,
  status: "empty",
  reason: "not_run",
  data_version: 3,
  findings: [
    {
      finding_id: `fnd_${U}`,
      kind: "category_spike",
      severity: "watch",
      headline: "Spending on food delivery is up 39% on usual",
      detail: "£286 in the month to 11 Oct (23 payments), against a usual £206.",
      link: "/transactions?category=food.delivery",
    },
  ],
  recommendations: [],
  can_check: false,
};
const env = { currency: "GBP", locale: "en-GB", timeZone: "Europe/London", checkedAdvice: true };

describe("ProactiveInsights", () => {
  it("shows findings with their link, and offers a check only when one is allowed", () => {
    const { rerender } = render(<ProactiveInsights initial={base} demo {...env} />);
    expect(screen.getByText("Spending on food delivery is up 39% on usual")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /See the transactions/ })).toHaveAttribute(
      "href",
      "/transactions?category=food.delivery",
    );
    expect(screen.getByText(/Checked advice is paused right now/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run the proactive check" })).not.toBeInTheDocument();

    rerender(<ProactiveInsights key="b" initial={{ ...base, can_check: true }} demo {...env} />);
    expect(screen.getByRole("button", { name: "Run the proactive check" })).toBeEnabled();
    expect(screen.getByText(/Run the proactive check to see advice/)).toBeInTheDocument();
  });

  it("says why advice is missing, and when a check is out of date", () => {
    const { rerender } = render(
      <ProactiveInsights initial={{ ...base, status: "paused", reason: "daily_limit" }} demo={false} {...env} />,
    );
    expect(screen.getByText(/Today’s proactive checks are used/)).toBeInTheDocument();
    rerender(
      <ProactiveInsights
        key="ready"
        initial={{ ...base, status: "ready", reason: null, checked_data_version: 2 }}
        demo={false}
        {...env}
      />,
    );
    expect(screen.getByText(/Your data changed since the last check/)).toBeInTheDocument();
  });

  it("says why a refused check can't run and offers no retry (#59 review)", async () => {
    const reason =
      "Today’s guest allowance for your network is used. Sign in with Google to keep going, or come back tomorrow.";
    const spy = vi.spyOn(api, "startProactiveCheck").mockResolvedValue({ refused: reason });
    render(<ProactiveInsights initial={{ ...base, can_check: true }} demo {...env} />);
    fireEvent.click(screen.getByRole("button", { name: "Run the proactive check" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(reason);
    expect(screen.queryByRole("button", { name: /proactive check/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Please try again/)).not.toBeInTheDocument();
    spy.mockRestore();
  });

  it("shows how its checked advice was checked, down to the source file (mandatory F)", () => {
    const run = "run_01ARZ3NDEKTSV4RRFFQ69G5FAV";
    render(
      <ProactiveInsights
        initial={{
          ...base,
          status: "ready",
          recommendations: [tripCard()],
          run_id: run,
          evidence: [
            {
              ref: "ver_01ARZ3NDEKTSV4RRFFQ69G5FAV",
              kind: "verification",
              title: "How the Verifier checked it",
              provenance: "detected",
              summary_lines: ["Approved by the Verifier in round 1."],
              checks: [{ name: "It's achievable, not too big a cut", passed: true, kind: "deterministic" }],
            },
            {
              ref: "fnd_01ARZ3NDEKTSV4RRFFQ69G5FAV",
              kind: "finding",
              title: "Spending on food delivery is up 39% on usual",
              provenance: "detected",
              summary_lines: [],
              inputs: { transaction_count: 23 },
              source_chain: {
                import_id: "imp_01ARZ3NDEKTSV4RRFFQ69G5FAV",
                filename: "monzo.csv",
                importer: "csv_statement",
                rows: "23 rows of this file",
              },
              link: "/transactions?category=food.delivery",
            },
          ],
        }}
        demo
        {...env}
      />,
    );
    fireEvent.click(screen.getByText("How it was checked"));
    expect(screen.getByText("It's achievable, not too big a cut")).toBeInTheDocument();
    expect(screen.getByText("monzo.csv")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /See these transactions/ })).toHaveAttribute(
      "href",
      "/transactions?category=food.delivery",
    );
    expect(screen.getByRole("link", { name: /Every step of this check/ })).toHaveAttribute(
      "href",
      `/activity#run-${run}`,
    );
  });
});

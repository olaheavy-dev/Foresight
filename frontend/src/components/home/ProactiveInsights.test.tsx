import { render, screen } from "@testing-library/react";

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
});

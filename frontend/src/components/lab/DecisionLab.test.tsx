// #49: the Lab fetches the forecast only for a spread, the one change measured from its date.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import { DecisionLab } from "./DecisionLab";

const api = vi.hoisted(() => ({
  fetchForecast: vi.fn(async () => ({ chart: { as_of: "2026-10-11" } })),
  fetchDetected: vi.fn(async () => null),
  fetchCategories: vi.fn(async () => null),
  simulateWithReason: vi.fn(async () => ({ error: "not simulated in this test" })),
}));
vi.mock("@/lib/api", () => api);

const lab = () => render(<DecisionLab currency="GBP" locale="en-GB" timeZone="Europe/London" />);

beforeEach(() => vi.clearAllMocks());

describe("Decision Lab", () => {
  it("runs a one-off purchase without fetching the forecast", async () => {
    lab();
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "450" } });
    fireEvent.submit(screen.getByRole("form", { name: "Scenario details" }));
    await waitFor(() => expect(api.simulateWithReason).toHaveBeenCalledTimes(1));
    expect(api.fetchForecast).not.toHaveBeenCalled();
  });

  it("fetches the forecast once, when a spread is chosen, and runs the spread from its date", async () => {
    lab();
    expect(api.fetchForecast).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("radio", { name: /Spread a purchase/ }));
    expect(api.fetchForecast).toHaveBeenCalledTimes(1);
    fireEvent.change(screen.getByLabelText("Total amount"), { target: { value: "900" } });
    fireEvent.submit(screen.getByRole("form", { name: "Scenario details" }));
    await waitFor(() => expect(api.simulateWithReason).toHaveBeenCalledTimes(1));
    expect(api.fetchForecast).toHaveBeenCalledTimes(1);
  });
});

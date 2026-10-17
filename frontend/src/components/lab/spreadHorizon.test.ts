import { spreadHorizon } from "./DecisionLab";

describe("spreadHorizon", () => {
  const asOf = "2026-10-15";
  it("keeps the default horizon for a short plan", () => {
    expect(spreadHorizon("2026-10-29", 3, "monthly", asOf)).toBe(90);
  });
  it("extends the forecast to include the last of 6 monthly payments (#46 review)", () => {
    expect(spreadHorizon("2026-10-29", 6, "monthly", asOf)).toBeGreaterThanOrEqual(14 + 5 * 31);
  });
  it("never asks for more than 180 days, leaving the exact schedule to the engine (docs/00 §6)", () => {
    expect(spreadHorizon("2026-10-29", 6, "monthly", asOf)).toBeLessThanOrEqual(180);
    expect(spreadHorizon("2026-10-29", 12, "monthly", asOf)).toBe(180); // the engine refuses it
    // From 1 Jan, six monthly payments from 20 Jan end near day 170: the estimate (181) is
    // capped, not refused, and the engine fits the exact schedule (#55 review).
    expect(spreadHorizon("2027-01-20", 6, "monthly", "2027-01-01")).toBe(180);
  });
  it("measures from the forecast date, not today, when the statement is a month old", () => {
    // Statement ends 15 Sep; first payment 29 Oct is 44 days after the forecast starts.
    expect(spreadHorizon("2026-10-29", 4, "monthly", "2026-09-15")).toBeGreaterThanOrEqual(44 + 3 * 31);
    expect(spreadHorizon("2026-10-29", 6, "monthly", "2026-09-15")).toBe(180); // capped; engine decides
  });
});

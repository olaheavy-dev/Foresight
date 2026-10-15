import { spreadHorizon } from "./DecisionLab";

describe("spreadHorizon", () => {
  const asOf = "2026-10-15";
  it("keeps the default horizon for a short plan", () => {
    expect(spreadHorizon("2026-10-29", 3, "monthly", asOf)).toBe(90);
  });
  it("extends the forecast to include the last of 6 monthly payments (#46 review)", () => {
    const h = spreadHorizon("2026-10-29", 6, "monthly", asOf);
    expect(h).not.toBeNull();
    expect(h!).toBeGreaterThanOrEqual(14 + 5 * 31);
  });
  it("allows 12 monthly payments that end within the year, and refuses one that doesn't", () => {
    expect(spreadHorizon("2026-10-29", 12, "monthly", asOf)).toBeLessThanOrEqual(365);
    expect(spreadHorizon("2026-12-15", 12, "monthly", asOf)).toBeNull();
  });
  it("measures from the forecast date, not today, when the statement is a month old", () => {
    // Statement ends 15 Sep; first payment 29 Oct is 44 days after the forecast starts.
    expect(spreadHorizon("2026-10-29", 6, "monthly", "2026-09-15")).toBeGreaterThanOrEqual(44 + 5 * 31);
  });
});

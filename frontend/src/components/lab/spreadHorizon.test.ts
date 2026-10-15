import { spreadHorizon } from "./DecisionLab";

describe("spreadHorizon", () => {
  const today = new Date("2026-10-15T09:00:00");
  it("keeps the default horizon for a short plan", () => {
    expect(spreadHorizon("2026-10-29", 3, "monthly", today)).toBe(90);
  });
  it("extends the forecast to include the last of 6 monthly payments (#46 review)", () => {
    const h = spreadHorizon("2026-10-29", 6, "monthly", today);
    expect(h).not.toBeNull();
    expect(h!).toBeGreaterThanOrEqual(14 + 5 * 31);
  });
  it("allows 12 monthly payments that end within the year, and refuses one that doesn't", () => {
    expect(spreadHorizon("2026-10-29", 12, "monthly", today)).toBeLessThanOrEqual(365);
    expect(spreadHorizon("2026-12-15", 12, "monthly", today)).toBeNull();
  });
});

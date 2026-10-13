import { isShipped } from "./flags";

describe("isShipped", () => {
  const features = [
    { key: "forecast", stage: 1, title: "Forecast", enabled: true },
    { key: "briefing", stage: 3, title: "Home", enabled: false },
  ];
  it("is on only when the flag is enabled", () => {
    expect(isShipped(features, "forecast")).toBe(true);
    expect(isShipped(features, "briefing")).toBe(false);
    expect(isShipped(features, "unknown")).toBe(false);
  });
  it("treats an unreachable service as off", () => {
    expect(isShipped(null, "forecast")).toBe(false);
  });
});

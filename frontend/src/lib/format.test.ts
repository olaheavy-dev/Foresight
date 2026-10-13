import { formatDayDate, formatMoney, formatMoneyCompact, formatShortDate } from "./format";

describe("format", () => {
  it("formats minor units for any currency", () => {
    expect(formatMoney(128_450, "GBP")).toBe("£1,284.50");
    expect(formatMoney(128_450, "GBP", "en-GB", { whole: true })).toBe("£1,285");
    expect(formatMoney(1_000, "JPY", "en-GB")).toBe("JP¥1,000");
    expect(formatMoney(12_345_678, "INR", "en-IN")).toBe("₹1,23,456.78");
    expect(formatMoney(-5_000, "GBP")).toBe("-£50.00");
  });

  it("compacts axis labels", () => {
    expect(formatMoneyCompact(100_000, "GBP")).toBe("£1K");
    expect(formatMoneyCompact(0, "GBP")).toBe("£0");
    expect(formatMoneyCompact(250_000, "GBP")).toBe("£2.5K");
    expect(formatMoneyCompact(-50_000, "GBP")).toBe("−£500");
    expect(formatMoneyCompact(150_000_000, "GBP")).toBe("£1.5M");
  });

  it("formats dates in UTC so they never shift a day", () => {
    expect(formatShortDate("2026-10-27")).toBe("27 Oct");
    expect(formatDayDate("2026-10-27")).toBe("Tue 27 Oct");
  });
});

describe("run timing and cost formatting", () => {
  it("formats clock times in the profile's time zone", async () => {
    const { formatClock } = await import("./format");
    expect(formatClock("2026-10-12T08:14:06Z", "en-GB", "Europe/London")).toBe("09:14:06");
    expect(formatClock("not a date")).toBe("");
  });

  it("formats durations, counts and estimated cost", async () => {
    const { formatCount, formatDuration, formatUsdEstimate } = await import("./format");
    expect(formatDuration(6_400)).toBe("6.4 s");
    expect(formatDuration(48_000)).toBe("48 s");
    expect(formatDuration(125_000)).toBe("2 min 5 s");
    expect(formatCount(18_240)).toBe("18,240");
    expect(formatUsdEstimate(0.046)).toBe("about $0.05");
    expect(formatUsdEstimate(0.004)).toBe("under $0.01");
  });
});

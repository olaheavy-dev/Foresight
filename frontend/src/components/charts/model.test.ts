import { forecastView } from "@/test/forecastFixture";
import { forecastEnd, layout, lowsSeries, monthTicks, nearest, niceScale } from "./model";

describe("lowsSeries", () => {
  it("starts at today's balance, then one point per pay-cycle low with its band", () => {
    const s = lowsSeries(forecastView().chart);
    expect(s.points[0]).toMatchObject({ date: "2026-01-30", low: false });
    expect(s.points.filter((p) => p.low)).toHaveLength(2);
    for (const p of s.points) expect(p.p10).toBeLessThanOrEqual(p.value);
    for (const p of s.points) expect(p.p90).toBeGreaterThanOrEqual(p.value);
  });

  it("keeps only the last 14 days of observed history by default", () => {
    const s = lowsSeries(forecastView().chart);
    expect(s.history.length).toBeLessThanOrEqual(15);
    expect(s.history.at(-1)?.date).toBe("2026-01-30");
  });

  it("drops non-finite values instead of drawing them", () => {
    const view = forecastView();
    view.chart.history.balance_minor[29] = Number.NaN;
    view.chart.pay_cycles![0].low.minor = Number.POSITIVE_INFINITY;
    const s = lowsSeries(view.chart);
    expect(s.history.every((p) => Number.isFinite(p.value))).toBe(true);
    expect(s.points.filter((p) => p.low)).toHaveLength(1);
  });
});

describe("niceScale", () => {
  it("uses round steps that cover the range", () => {
    const s = niceScale(-15_438, 154_561);
    expect(s.lo).toBeLessThanOrEqual(-15_438);
    expect(s.hi).toBeGreaterThanOrEqual(154_561);
    expect([1, 2, 2.5, 5].some((m) => s.step / 10 ** Math.floor(Math.log10(s.step)) === m)).toBe(true);
    expect(s.ticks.every(Number.isFinite)).toBe(true);
  });

  it("never divides by zero on a flat series", () => {
    const s = niceScale(0, 0);
    expect(s.hi).toBeGreaterThan(s.lo);
  });
});

describe("layout", () => {
  it("maps every point to finite pixels", () => {
    const s = lowsSeries(forecastView().chart);
    const g = layout(s, { width: 600, height: 300, buffer: 50_000, narrow: false })!;
    for (const p of [...s.history, ...s.points]) {
      expect(Number.isFinite(g.x(p.date))).toBe(true);
      expect(Number.isFinite(g.y(p.value))).toBe(true);
    }
  });

  it("returns null when there is nothing to draw", () => {
    expect(
      layout({ history: [], today: null, points: [] }, { width: 600, height: 300, buffer: null, narrow: false }),
    ).toBeNull();
  });
});

describe("helpers", () => {
  it("monthTicks thins to the requested maximum", () => {
    expect(monthTicks("2026-01-15", "2026-12-20", 4).length).toBeLessThanOrEqual(4);
    expect(monthTicks("2026-01-15", "2026-01-10", 4)).toEqual([]);
  });

  it("nearest picks the closest date", () => {
    const pts = [{ date: "2026-01-01" }, { date: "2026-01-10" }];
    expect(nearest(pts, Date.parse("2026-01-08T00:00:00Z"))?.date).toBe("2026-01-10");
  });

  it("forecastEnd reads the last day of the fan", () => {
    expect(forecastEnd(forecastView().chart)?.date).toBe("2026-04-09");
  });
});

/** A synthetic ForecastView shaped exactly like the API's (fictional numbers, made up for tests). */
import type { ForecastView } from "@/ui-contracts/types";

const days = (from: string, n: number) =>
  Array.from({ length: n }, (_, i) => new Date(Date.parse(`${from}T00:00:00Z`) + i * 86_400_000).toISOString().slice(0, 10));

const histDates = days("2026-01-01", 30);
const fanDates = days("2026-01-30", 70);
const p50 = fanDates.map((_, i) => 300_000 - (i % 30) * 9_000 + Math.floor(i / 30) * 20_000);

export function forecastView(overrides: Partial<ForecastView["chart"]> = {}): ForecastView {
  return {
    forecast_id: "fc_0123456789abcdef01234567",
    workspace_id: "wsp_01ARZ3NDEKTSV4RRFFQ69G5FAV",
    currency: "GBP",
    locale: "en-GB",
    engine_version: "fc-test",
    data_version: 1,
    chart: {
      as_of: "2026-01-30",
      balance_mode: "absolute",
      buffer_minor: 50_000,
      resolution: "daily",
      scope: { kind: "mine", label: "Test current account", account_ids: [], switchable: false },
      history: { dates: histDates, balance_minor: histDates.map((_, i) => 250_000 + i * 1_000) },
      forecast: { dates: fanDates, p50, p10: p50.map((v) => v - 40_000), p90: p50.map((v) => v + 40_000) },
      events: [],
      pay_cycles: [
        {
          payday: "2026-02-28",
          low_date: fanDates[29],
          low: { kind: "money", minor: p50[29], currency: "GBP", display: "£390", precision: "rounded" },
          below_buffer: false,
          chance_below_buffer: { kind: "percent", value: 0.12, display: "12%" },
        },
        {
          payday: "2026-03-30",
          low_date: fanDates[59],
          low: { kind: "money", minor: p50[59], currency: "GBP", display: "£590", precision: "rounded" },
          below_buffer: false,
          chance_below_buffer: { kind: "percent", value: 0.03, display: "3%" },
        },
      ],
      summary: {
        min_balance: { kind: "money", minor: p50[29], currency: "GBP", display: "£390", precision: "rounded" },
        min_date: { kind: "date", value: fanDates[29], display: "28 Feb" },
        starting_balance: {
          money: { kind: "money", minor: p50[0], currency: "GBP", display: "£3,000.00", precision: "exact" },
          provenance: "observed",
        },
      },
      ...overrides,
    },
  };
}

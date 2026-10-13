import { IconChip } from "@/components/ui/primitives";
import { formatDayDate, formatShortDate } from "@/lib/format";
import type { ForecastView } from "@/ui-contracts/types";

/** Three demo figures under the Landing preview, all from the demo profile's forecast. */
export function LandingMetrics({ forecast }: { forecast: ForecastView }) {
  const c = forecast.chart;
  const loc = forecast.locale;
  const low = c.pay_cycles?.[0];
  return (
    <div className="mini-metrics">
      <div className="card metric">
        <IconChip icon="wallet" />
        <div>
          <p className="m-label">Current balance</p>
          <p className="m-value serif num">{c.summary.starting_balance.money.display}</p>
          <p className="m-note">{`Demo · as of ${formatShortDate(c.as_of, loc)}`}</p>
        </div>
      </div>
      <div className="card metric">
        <IconChip icon="bars" tone={low?.below_buffer ? "red" : "blue"} />
        <div>
          <p className="m-label">Lowest before payday</p>
          <p className="m-value serif num">{low ? low.low.display : "—"}</p>
          <p className="m-note">{low ? formatDayDate(low.low_date, loc) : "No payday found yet"}</p>
        </div>
      </div>
      <div className="card metric">
        <IconChip icon="alert" tone={low?.below_buffer ? "red" : "green"} />
        <div>
          <p className="m-label">Chance below buffer</p>
          <p className="m-value serif num">{low?.chance_below_buffer ? low.chance_below_buffer.display : "—"}</p>
          <p className="m-note">{low ? `Before payday on ${formatShortDate(low.payday, loc)}` : "Needs a buffer and a payday"}</p>
        </div>
      </div>
    </div>
  );
}

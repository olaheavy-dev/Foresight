import { Badge, IconChip } from "@/components/ui/primitives";
import { lowsSeries } from "@/components/charts/model";
import { formatDayDate, formatMoney, formatShortDate } from "@/lib/format";
import type { ForecastView } from "@/ui-contracts/types";

const PROVENANCE: Record<string, string> = {
  observed: "from your statement",
  detected: "detected from your data",
  confirmed: "confirmed by you",
  declared: "as you told us",
  user_set: "set by you",
  default: "not known yet",
};

/**
 * The four key numbers (IA: Home §2). Every figure is the API's own display string or a
 * formatted API value; a figure the API does not provide yet says so instead of guessing.
 */
export function HomeMetrics({ forecast }: { forecast: ForecastView }) {
  const c = forecast.chart;
  const cur = forecast.currency;
  const loc = forecast.locale;
  const start = c.summary.starting_balance;
  const firstLow = c.pay_cycles?.[0];
  const lowPoint = lowsSeries(c).points.find((p) => p.low);
  const relative = c.balance_mode === "relative";
  return (
    <section className="metrics" aria-label="Key figures">
      <div className="card metric">
        <IconChip icon="wallet" />
        <div>
          <p className="m-label">Current balance</p>
          <p className="m-value serif num">{relative ? "—" : start.money.display}</p>
          <p className="m-note">
            {relative
              ? "Add today’s balance to see absolute figures"
              : `As of ${formatShortDate(c.as_of, loc)} · ${PROVENANCE[start.provenance] ?? start.provenance}`}
          </p>
        </div>
      </div>

      <div className="card metric">
        <IconChip icon="bars" tone={firstLow?.below_buffer ? "red" : "blue"} />
        <div>
          <p className="m-label">Lowest before payday</p>
          {firstLow ? (
            <>
              <p className="m-value serif num">
                {firstLow.low.display}
                {firstLow.below_buffer ? (
                  <Badge tone="red" icon="alert">
                    Below buffer
                  </Badge>
                ) : null}
              </p>
              <p className="m-note">
                {formatShortDate(firstLow.low_date, loc)}
                {lowPoint && lowPoint.p10 !== lowPoint.p90
                  ? ` · likely ${formatMoney(lowPoint.p10, cur, loc, { whole: true })} to ${formatMoney(lowPoint.p90, cur, loc, { whole: true })}`
                  : ""}
              </p>
            </>
          ) : (
            <>
              <p className="m-value serif num">—</p>
              <p className="m-note">No payday found in the forecast yet</p>
            </>
          )}
        </div>
      </div>

      <div className="card metric">
        <IconChip icon="coins" tone="green" />
        <div>
          <p className="m-label">Next payday</p>
          {firstLow ? (
            <>
              <p className="m-value serif num">{formatShortDate(firstLow.payday, loc)}</p>
              <p className="m-note">{`${formatDayDate(firstLow.payday, loc).split(" ")[0]} · detected from your income`}</p>
            </>
          ) : (
            <>
              <p className="m-value serif num">—</p>
              <p className="m-note">No regular income detected yet</p>
            </>
          )}
        </div>
      </div>

      <div className="card metric muted-card">
        <IconChip icon="bulb" tone="grey" />
        <div>
          <p className="m-label">Insights to review</p>
          <p className="m-value serif">Not shipped yet</p>
          <p className="m-note">Arrives with proactive insights</p>
        </div>
      </div>
    </section>
  );
}

import { CashFlowChart } from "@/components/charts/CashFlowChart";
import { forecastEnd } from "@/components/charts/model";
import { Icon } from "@/components/icons/Icon";
import { CardHead } from "@/components/ui/primitives";
import { formatLongDate, formatMoney } from "@/lib/format";
import type { ForecastView } from "@/ui-contracts/types";

/** Cash-flow forecast card: pay-cycle lows with the likely range, legend and "if nothing changes". */
export function ForecastCard({ forecast, compact = false }: { forecast: ForecastView; compact?: boolean }) {
  // On Landing the card sits under the page’s h2, so its title is an h3.
  const level = compact ? 3 : 2;
  const c = forecast.chart;
  const cur = forecast.currency;
  const loc = forecast.locale;
  const end = forecastEnd(c);
  const buffer = c.buffer_minor;
  const money = (m: number) => formatMoney(m, cur, loc, { whole: true });
  return (
    <article className="card forecast" aria-labelledby="fc-h">
      <CardHead
        icon="pulse"
        title="Cash-flow forecast"
        titleId="fc-h"
        level={level}
        sub={
          end
            ? `Lowest balance before each payday, to ${formatLongDate(end.date, loc)} · middle of the simulated paths · ${c.scope.label}`
            : c.scope.label
        }
      />
      <CashFlowChart
        data={c}
        currency={cur}
        locale={loc}
        height={compact ? 230 : 300}
        heightNarrow={compact ? 210 : 230}
      />
      <div className="legend">
        <span>
          <svg viewBox="0 0 26 10" aria-hidden="true">
            <line x1="1" y1="5" x2="25" y2="5" className="lg-observed" />
          </svg>
          Observed
        </span>
        <span>
          <svg viewBox="0 0 26 10" aria-hidden="true">
            <line x1="1" y1="5" x2="25" y2="5" className="lg-forecast" />
          </svg>
          Lowest balance before each payday
        </span>
        <span>
          <svg viewBox="0 0 26 10" aria-hidden="true">
            <rect x="1" y="1" width="24" height="8" rx="2" className="lg-band" />
          </svg>
          Likely range (P10–P90)
        </span>
        {buffer !== null ? (
          <span>
            <svg viewBox="0 0 26 10" aria-hidden="true">
              <line x1="1" y1="5" x2="25" y2="5" className="lg-buffer" />
            </svg>
            {`Your buffer · ${money(buffer)}`}
          </span>
        ) : null}
      </div>
      {end && !compact ? (
        <p className="info-bar">
          <Icon name="info" />
          <span>
            If nothing changes you’d have about <strong className="num">{money(end.p50)}</strong> on{" "}
            {formatLongDate(end.date, loc)} (likely {money(end.p10)} to {money(end.p90)}).
          </span>
        </p>
      ) : null}
    </article>
  );
}

import { firstName, greeting } from "@/components/home/greeting";
import { ForecastCard } from "@/components/home/ForecastCard";
import { HomeMetrics } from "@/components/home/HomeMetrics";
import { ButtonLink, CardHead } from "@/components/ui/primitives";
import { NotShipped, Unavailable } from "@/components/ui/NotShipped";
import { fetchForecast } from "@/lib/api";
import { isShipped } from "@/lib/flags";
import { loadShell } from "@/lib/server";

export const metadata = { title: "Home · Foresight" };
export const dynamic = "force-dynamic";

export default async function HomePage() {
  const { profile, features, options } = await loadShell();

  if (!profile) {
    return (
      <main className="page home" id="main">
        <section className="hero">
          <h1 className="serif">Your money, a few steps ahead.</h1>
          <p className="lede">Choose the demo profile or import a statement to see your forecast.</p>
        </section>
        <div className="primary-actions inline">
          <ButtonLink href="/" variant="primary" size="lg" iconEnd="arrowright">
            Choose how to start
          </ButtonLink>
        </div>
      </main>
    );
  }

  const forecastOn = isShipped(features, "forecast");
  const forecast = forecastOn ? await fetchForecast("mine", options) : null;
  const { part, date } = greeting(new Date(), profile.timezone, profile.locale);

  return (
    <main className="page home" id="main">
      <section className="hero">
        <div className="hero-art" aria-hidden="true" />
        <blockquote className="quote serif">
          “A calm mind
          <br />
          builds a richer future.”<span />
        </blockquote>
        <p className="date">{date}</p>
        <p className="greet">{`${part}, ${firstName(profile.name)}`}</p>
        <h1 className="serif">Your money, a few steps ahead.</h1>
        <p className="lede">
          A clearer today, a calmer month. Foresight reads your transactions, forecasts what’s next and checks its advice before
          it reaches you.
        </p>
      </section>

      {!forecastOn ? (
        <article className="card forecast" aria-labelledby="fc-h">
          <CardHead icon="pulse" title="Cash-flow forecast" titleId="fc-h" />
          <NotShipped
            title="Forecast"
            detail="The forecast is switched on once its backtest meets its accuracy targets. Until then no forecast figures are shown here."
          />
        </article>
      ) : forecast ? (
        <>
          <HomeMetrics forecast={forecast} />
          <section className="row-2">
            <ForecastCard forecast={forecast} />
            <article className="card briefing" aria-labelledby="brief-h">
              <CardHead icon="filetext" title="Financial briefing" titleId="brief-h" />
              <NotShipped title="Briefing" compact detail="Written from your data each morning once the agents ship." />
            </article>
          </section>
        </>
      ) : (
        <Unavailable what="Your forecast" />
      )}

      <section className="card insights" aria-labelledby="ins-h">
        <div className="ins-head">
          <CardHead icon="sparkles" title="Proactive insights" titleId="ins-h" sub="Things we’ve noticed, and suggested next steps." />
        </div>
        <NotShipped title="Proactive insights" compact detail="Each insight will come with one checked action." />
      </section>
    </main>
  );
}

import { DemoButton } from "@/components/landing/DemoButton";
import { LandingMetrics } from "@/components/landing/LandingMetrics";
import { ForecastCard } from "@/components/home/ForecastCard";
import { Icon } from "@/components/icons/Icon";
import { Logo } from "@/components/Logo";
import { ThemeControl } from "@/components/shell/ThemeControl";
import { ButtonLink, CardHead, IconChip } from "@/components/ui/primitives";
import { NotShipped } from "@/components/ui/NotShipped";
import { fetchFeatures } from "@/lib/api";
import { isShipped } from "@/lib/flags";
import { apiOptions, demoForecast } from "@/lib/server";

export const dynamic = "force-dynamic";

/** Landing (IA): demo and CSV entry; sign-in shown but disabled until after the hackathon. */
export default async function Landing() {
  const features = await fetchFeatures(await apiOptions());
  const forecastOn = isShipped(features, "forecast");
  const preview = forecastOn ? await demoForecast() : null;

  return (
    <div className="landing-frame">
      <main className="auth" id="main" aria-labelledby="auth-h">
        <Logo />
        <p className="kicker">Your financial intelligence partner</p>
        <h1 id="auth-h" className="serif">
          Start with your own statements
        </h1>
        <p className="sub">
          Turn your transactions into a clear view of what’s next, with advice that’s checked before you see it.
        </p>

        <div className="primary-actions">
          <DemoButton />
          <ButtonLink href="/start" size="lg" icon="upload">
            Import a CSV statement
          </ButtonLink>
        </div>

        <div className="divider">or sign in</div>
        <form className="signin" aria-describedby="soon" aria-label="Sign in (coming after the hackathon)">
          <div className="seg" aria-hidden="true">
            <span className="on">Sign in</span>
            <span>Create account</span>
          </div>
          <div className="field">
            <label htmlFor="em">Email address</label>
            <div className="input">
              <Icon name="mail" />
              <input id="em" type="email" placeholder="you@example.com" disabled />
            </div>
          </div>
          <div className="field">
            <label htmlFor="pw">Password</label>
            <div className="input">
              <Icon name="lock" />
              <input id="pw" type="password" disabled />
            </div>
          </div>
          <button className="btn primary lg" type="button" disabled style={{ width: "100%" }}>
            Sign in <Icon name="arrowright" />
          </button>
          <p className="soon" id="soon">
            <Icon name="clock" />
            Accounts are coming after the hackathon. For now, try the demo or import a CSV.
          </p>
        </form>

        <p className="privacy">
          <Icon name="shield" />
          <span>
            Your statements stay private. Every model call goes through one gateway, account numbers are masked first,
            and we never ask for bank logins.
          </span>
        </p>
        <div className="theme-footer">
          <span className="um-label" id="landing-theme">
            Theme
          </span>
          <ThemeControl labelledBy="landing-theme" />
        </div>
      </main>

      <section className="market" aria-labelledby="mk-h">
        <div className="market-art" aria-hidden="true" />
        <blockquote className="quote serif">
          “A calm mind
          <br />
          builds a richer future.”
          <span />
        </blockquote>
        <p className="kicker">From data to a calmer month</p>
        <div className="market-top">
          <div>
            <h2 id="mk-h">
              Your money,
              <br />a few steps ahead.
            </h2>
            <p className="lede">
              Foresight reads your transactions, forecasts what’s next and tests your decisions before you make them, so
              you can stay in control today and plan for tomorrow.
            </p>
          </div>
          <ul className="features">
            <li>
              <IconChip icon="bars" />
              <div>
                <h3>See what’s next</h3>
                <p>A forecast of your balance ahead, with a likely range.</p>
              </div>
            </li>
            <li>
              <IconChip icon="bulb" />
              <div>
                <h3>Get warned early</h3>
                <p>Risks spotted before they happen, like a buffer about to run thin.</p>
              </div>
            </li>
            <li>
              <IconChip icon="target" tone="red" />
              <div>
                <h3>Test decisions first</h3>
                <p>Ask “can I afford it?” and see the answer on your own numbers.</p>
              </div>
            </li>
          </ul>
        </div>

        <div className="preview single">
          {preview ? (
            <ForecastCard forecast={preview} compact />
          ) : (
            <article className="card forecast" aria-labelledby="fc-h">
              <CardHead icon="pulse" title="Cash-flow forecast" titleId="fc-h" sub="Demo profile · fictional data" />
              <NotShipped
                title="Forecast preview"
                detail="The demo forecast appears here once the forecast meets its accuracy targets."
              />
            </article>
          )}
        </div>
        {preview ? <LandingMetrics forecast={preview} /> : null}
      </section>
    </div>
  );
}

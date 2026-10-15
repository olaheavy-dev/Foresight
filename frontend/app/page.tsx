import { DemoButton } from "@/components/landing/DemoButton";
import { LandingMetrics } from "@/components/landing/LandingMetrics";
import { ForecastCard } from "@/components/home/ForecastCard";
import { Icon } from "@/components/icons/Icon";
import { Logo } from "@/components/Logo";
import { ThemeControl } from "@/components/shell/ThemeControl";
import { ButtonLink, CardHead, IconChip } from "@/components/ui/primitives";
import { NotShipped } from "@/components/ui/NotShipped";
import { GoogleButton } from "@/components/landing/GoogleButton";
import { fetchAuthProviders, fetchFeatures, fetchProfile } from "@/lib/api";
import { isShipped } from "@/lib/flags";
import { apiOptions, demoForecast } from "@/lib/server";

export const dynamic = "force-dynamic";

const NOTICES: Record<string, { text: string; error: boolean }> = {
  failed: { text: "Google sign-in didn’t finish. Please try again, or continue as a guest.", error: true },
  unverified: { text: "That Google account’s email isn’t verified, so we can’t sign you in with it.", error: true },
  unavailable: { text: "Google sign-in isn’t available just now. You can continue as a guest.", error: true },
  signedin: { text: "You’re signed in. Explore the demo or import a statement to start.", error: false },
  signedout: { text: "You’re signed out.", error: false },
  deleted: { text: "Your profiles and their data have been deleted.", error: false },
};

/** Landing (IA): guest demo and CSV entry, plus Google sign-in once it is configured. */
export default async function Landing({ searchParams }: { searchParams: Promise<{ auth?: string | string[] }> }) {
  const options = await apiOptions();
  const [features, providers, profile, params] = await Promise.all([
    fetchFeatures(options),
    fetchAuthProviders(options),
    fetchProfile(options),
    searchParams,
  ]);
  const auth = typeof params.auth === "string" ? params.auth : "";
  const notice = NOTICES[auth] ?? null;
  const signedIn = profile?.account?.kind === "google" || auth === "signedin";
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

        {signedIn ? null : providers?.google ? (
          <>
            <div className="divider">or keep your profiles</div>
            <div className="signin">
              <GoogleButton />
              <p className="soon">
                <Icon name="lock" />
                Sign in to keep your profiles between visits. As a guest, everything is private to this browser and
                deleted after a week unused.
              </p>
            </div>
          </>
        ) : null}
        {notice ? (
          <p className={notice.error ? "form-error" : "soon"} role={notice.error ? "alert" : "status"}>
            {notice.text}
          </p>
        ) : null}

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

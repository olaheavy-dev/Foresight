import Link from "next/link";
import { Logo } from "@/components/Logo";

export const metadata = { title: "Privacy · Foresight" };

const UPDATED = "20 October 2026";
const ISSUES = "https://github.com/olaheavy-dev/Foresight/issues";

/** Public privacy notice (linked from Landing and Google's consent screen). Plain facts only. */
export default function PrivacyPage() {
  return (
    <div className="landing-frame single">
      <main className="auth legal" id="main" aria-labelledby="privacy-h">
        <Logo />
        <p className="kicker">Privacy</p>
        <h1 id="privacy-h" className="serif">
          How Foresight handles your data
        </h1>
        <p className="sub">Last updated {UPDATED}. Foresight is a personal portfolio project run by one person.</p>

        <h2>What we store</h2>
        <ul>
          <li>
            <strong>Statements you import</strong> (CSV files) and what Foresight works out from them: transactions,
            categories, recurring payments, balances you enter, forecasts and the checks behind them.
          </li>
          <li>
            <strong>Your questions and Foresight’s answers</strong>, with an audit trail of how each answer was checked.
          </li>
          <li>
            <strong>If you sign in with Google</strong>: your name, email address and Google’s account identifier.
            Nothing else from your Google account, and Google is used only to sign you in.
          </li>
        </ul>
        <p>
          We never ask for bank logins and don’t connect to your bank. There are no analytics or advertising trackers.
        </p>

        <h2>Guests and accounts</h2>
        <ul>
          <li>
            <strong>As a guest</strong>, your profiles belong to this browser only. They’re deleted when you sign out,
            or after 7 days without use.
          </li>
          <li>
            <strong>Signed in with Google</strong>, your profiles are kept until you delete them. Signing in after using
            Foresight as a guest moves your guest profiles to your account.
          </li>
          <li>
            The demo profile is fictional. Each visitor gets a private copy, so nobody sees anyone else’s questions.
          </li>
          <li>
            Guests share a daily allowance of AI questions and checks per network, so one visitor can’t use up
            everyone’s. To count it, Foresight keeps a one-way code made from your network and the date, in memory only,
            never your address. It’s never written to disk, and it’s cleared on the first count after midnight (UTC) or
            when the app restarts.
          </li>
        </ul>

        <h2>When AI is used</h2>
        <p>
          Every figure you see is calculated by Foresight’s own engine, not by an AI model. When you ask a question,
          Foresight sends your question and summaries the engine has computed (such as category totals, forecast figures
          and findings) to an AI model from OpenAI, through OpenAI’s API and under its terms. It doesn’t send your raw
          transaction list or account numbers, and account numbers and payment references are masked before any text
          leaves the app.
        </p>

        <h2>Cookies and storage</h2>
        <ul>
          <li>
            <code>foresight_session</code>: keeps you signed in or keeps your guest profiles. It’s needed for the app to
            work, and only a one-way hash of it is stored on the server.
          </li>
          <li>
            <code>foresight_oidc</code>: lasts up to 10 minutes while you sign in with Google, to check the sign-in came
            back to the browser that started it.
          </li>
          <li>Your theme choice (light, dark or system) is kept in your browser’s local storage.</li>
        </ul>

        <h2>Deleting your data</h2>
        <p>
          Open the account menu and choose <strong>Delete my data</strong>. It removes every profile, import, question
          and answer you own, and your account record if you signed in with Google, from the live database straight
          away. Signing out of a Google account keeps your data for next time. When a guest signs out, their guest
          profiles are deleted at the same moment.
        </p>

        <h2>Questions</h2>
        <p>
          Open an issue on <a href={ISSUES}>the project’s GitHub page</a>. Please don’t include any personal or
          financial details there.
        </p>

        <p className="sub" style={{ marginTop: "var(--space-6)" }}>
          <Link href="/">Back to Foresight</Link>
        </p>
      </main>
    </div>
  );
}

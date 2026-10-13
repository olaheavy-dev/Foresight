import { Logo } from "@/components/Logo";
import { ButtonLink } from "@/components/ui/primitives";
import { NotShipped } from "@/components/ui/NotShipped";

export const metadata = { title: "Import a statement · Foresight" };

export default function StartPage() {
  return (
    <div className="landing-frame single">
      <main className="auth" id="main">
        <Logo />
        <p className="kicker">Import</p>
        <h1 className="serif">Drop your statements</h1>
        <p className="sub">
          CSV exports from your bank: Foresight finds the table, checks it against the running balance and shows you what it
          found before anything is used.
        </p>
        <NotShipped title="Statement import" />
        <p className="sub" style={{ marginTop: "var(--space-6)" }}>
          Until then, explore the demo profile, built from fictional data.
        </p>
        <div className="primary-actions">
          <ButtonLink href="/" variant="secondary" size="lg" icon="arrowright">
            Back to the start
          </ButtonLink>
        </div>
      </main>
    </div>
  );
}

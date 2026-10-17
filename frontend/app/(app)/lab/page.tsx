import { SectionPage } from "@/components/SectionPage";
import { DecisionLab } from "@/components/lab/DecisionLab";
import { Goals } from "@/components/lab/Goals";
import { isShipped } from "@/lib/flags";
import { loadShell } from "@/lib/server";

export const metadata = { title: "Decision Lab · Foresight" };
export const dynamic = "force-dynamic";

const LEDE =
  "Test a decision before you make it: compare your current path with a what-if on the same simulated paths.";

export default async function LabPage() {
  const { profile, features } = await loadShell();
  if (!isShipped(features, "decision_lab")) {
    return <SectionPage title="Decision Lab" lede={LEDE} what="Scenario comparison" />;
  }
  return (
    <main className="page section-page" id="main">
      <h1>Decision Lab</h1>
      <p className="lede">{LEDE}</p>
      {profile ? (
        <>
          <DecisionLab currency={profile.home_currency} locale={profile.locale} timeZone={profile.timezone} />
          {isShipped(features, "goals") ? (
            <Goals currency={profile.home_currency} locale={profile.locale} timeZone={profile.timezone} />
          ) : null}
        </>
      ) : (
        <p className="lede">Choose the demo profile or import a statement first.</p>
      )}
    </main>
  );
}

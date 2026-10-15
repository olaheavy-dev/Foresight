import { ActivityFeed } from "@/components/activity/ActivityFeed";
import { SectionPage } from "@/components/SectionPage";
import { Unavailable } from "@/components/ui/NotShipped";
import { fetchActivity } from "@/lib/api";
import { isShipped } from "@/lib/flags";
import { loadShell } from "@/lib/server";

export const metadata = { title: "Activity · Foresight" };
export const dynamic = "force-dynamic";

const LEDE = "What Foresight did and when: every agent run with its steps, and every change to this profile.";

export default async function ActivityPage() {
  const { profile, features, options } = await loadShell();
  if (!isShipped(features, "agents") || !isShipped(features, "audit_trail")) {
    return <SectionPage title="Activity" lede={LEDE} what="Activity feed" />;
  }
  if (!profile) {
    return (
      <main className="page section-page" id="main">
        <h1>Activity</h1>
        <p className="lede">Choose the demo profile or import a statement first.</p>
      </main>
    );
  }
  const feed = await fetchActivity(options);
  return (
    <main className="page section-page" id="main">
      <h1>Activity</h1>
      <p className="lede">{LEDE}</p>
      {feed ? (
        <ActivityFeed feed={feed} locale={profile.locale} timeZone={profile.timezone} />
      ) : (
        <Unavailable what="Activity" />
      )}
    </main>
  );
}

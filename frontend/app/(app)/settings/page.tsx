import { Settings } from "@/components/settings/Settings";
import { loadShell } from "@/lib/server";

export const metadata = { title: "Settings · Foresight" };
export const dynamic = "force-dynamic";

const LEDE = "Your profile, the buffer your forecast keeps to, and your data: sign out or delete it at any time.";

export default async function SettingsPage() {
  const { profile } = await loadShell();
  return (
    <main className="page section-page" id="main">
      <h1>Settings</h1>
      <p className="lede">{LEDE}</p>
      {profile ? (
        <Settings initial={profile} />
      ) : (
        <p className="lede">Choose the demo profile or import a statement first.</p>
      )}
    </main>
  );
}

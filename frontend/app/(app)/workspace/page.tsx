import { firstName } from "@/components/home/greeting";
import { SectionPage } from "@/components/SectionPage";
import { ButtonLink } from "@/components/ui/primitives";
import { Workspace } from "@/components/workspace/Workspace";
import "@/components/workspace/workspace.css";
import { isShipped } from "@/lib/flags";
import { loadShell } from "@/lib/server";

export const metadata = { title: "AI Workspace · Foresight" };
export const dynamic = "force-dynamic";

const LEDE =
  "Ask anything about your money. Every number is computed from your transactions and the forecast engine, then checked before you see it.";

export default async function WorkspacePage({ searchParams }: { searchParams: Promise<{ q?: string | string[] }> }) {
  const [{ profile, features }, params] = await Promise.all([loadShell(), searchParams]);

  // The Workspace ships behind the `ask` flag (features.yaml): off means an honest placeholder.
  if (!isShipped(features, "ask")) {
    return <SectionPage title="AI Workspace" lede={LEDE} what="Questions and checked answers" />;
  }

  if (!profile) {
    return (
      <main className="page section-page" id="main">
        <h1>AI Workspace</h1>
        <p className="lede">Choose the demo profile or import a statement, then ask about your money.</p>
        <ButtonLink href="/" variant="primary" size="lg" iconEnd="arrowright">
          Choose how to start
        </ButtonLink>
      </main>
    );
  }

  const q = Array.isArray(params.q) ? params.q[0] : params.q;
  return (
    <main className="ws-main" id="main">
      <h1 className="sr-only">AI Workspace</h1>
      <Workspace
        workspaceId={profile.workspace_id}
        firstName={firstName(profile.name)}
        locale={profile.locale}
        timeZone={profile.timezone}
        currency={profile.home_currency}
        initialQuestion={q?.trim() ? q.trim().slice(0, 2000) : null}
        flags={{
          auditTrail: isShipped(features, "audit_trail"),
          checkedAdvice: isShipped(features, "checked_advice"),
          anomalyDetection: isShipped(features, "anomaly_detection"),
        }}
      />
    </main>
  );
}

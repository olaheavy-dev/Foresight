import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "@/components/icons/Icon";
import { Logo } from "@/components/Logo";
import type { ProfileView } from "@/ui-contracts/types";
import { AskBox } from "./AskBox";
import { AvatarMenu } from "./AvatarMenu";
import { SideNav } from "./SideNav";

/**
 * App frame (IA §Navigation): sidebar from 1024px, bottom tab bar below; top bar with the ask
 * box, Activity and the avatar menu. A "Demo data" badge marks the read-only demo profile.
 */
export function AppShell({ profile, children }: { profile: ProfileView | null; children: ReactNode }) {
  const subtitle = !profile
    ? "Choose the demo or import a statement"
    : profile.kind === "demo"
      ? "Demo profile · fictional data"
      : "Your profile";
  return (
    <div className="frame">
      <aside className="sidebar">
        <Logo href="/home" label="Foresight home" />
        <SideNav />
        <div className="spacer" />
        <section className="side-card" aria-labelledby="quality-h">
          <div className="head">
            <span className="icon-chip sm">
              <Icon name="flask" />
            </span>
            <h2 id="quality-h">Quality checks</h2>
          </div>
          <p>How accurate categorisation and forecasts are, measured on test data.</p>
          <Link className="link" href="/quality">
            See evaluation results <Icon name="arrowright" />
          </Link>
        </section>
      </aside>

      <div className="main">
        <header className="topbar">
          <Logo href="/home" label="Foresight home" />
          <AskBox />
          {profile?.kind === "demo" ? (
            <span className="env-tag">
              <Icon name="info" /> Demo data
            </span>
          ) : null}
          <div className="right">
            <Link className="icon-btn" href="/activity" aria-label="Activity">
              <Icon name="bell" />
            </Link>
            <AvatarMenu name={profile?.name ?? null} subtitle={subtitle} />
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}

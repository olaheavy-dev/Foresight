import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { loadShell } from "@/lib/server";

export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: ReactNode }) {
  const { profile } = await loadShell();
  return <AppShell profile={profile}>{children}</AppShell>;
}

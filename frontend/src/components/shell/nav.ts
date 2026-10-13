import type { IconName } from "@/components/icons/Icon";

/** Primary navigation (IA: at most five sections, plus Settings on desktop). */
export type NavItem = { href: string; label: string; short?: string; icon: IconName; desktopOnly?: boolean };

export const NAV: NavItem[] = [
  { href: "/home", label: "Home", icon: "home" },
  { href: "/workspace", label: "AI Workspace", short: "Workspace", icon: "grid" },
  { href: "/lab", label: "Decision Lab", short: "Lab", icon: "bars" },
  { href: "/transactions", label: "Transactions", icon: "swap" },
  { href: "/activity", label: "Activity", icon: "clock" },
  { href: "/settings", label: "Settings", icon: "settings", desktopOnly: true },
];

export function isCurrent(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "@/components/icons/Icon";
import { isCurrent, NAV } from "./nav";

/** Sidebar from 1024px; the same links become the bottom tab bar below that. */
export function SideNav() {
  const pathname = usePathname() ?? "";
  return (
    <nav className="nav" aria-label="Main">
      {NAV.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          aria-current={isCurrent(pathname, item.href) ? "page" : undefined}
          className={item.desktopOnly ? "nav-settings" : undefined}
        >
          <Icon name={item.icon} />
          {item.short ? (
            <>
              <span className="long">{item.label}</span>
              <span className="short">{item.short}</span>
            </>
          ) : (
            <span>{item.label}</span>
          )}
        </Link>
      ))}
    </nav>
  );
}

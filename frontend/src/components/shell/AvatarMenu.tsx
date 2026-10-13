"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { Icon } from "@/components/icons/Icon";
import { ThemeControl } from "./ThemeControl";

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? [parts[0], parts[parts.length - 1]] : parts.slice(0, 1);
  return letters.map((p) => p[0]?.toUpperCase() ?? "").join("") || "?";
}

/** Avatar → menu: Switch profile, Settings, Quality checks, Theme. Esc and outside click close. */
export function AvatarMenu({ name, subtitle }: { name: string | null; subtitle: string }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const display = name ?? "No profile";
  return (
    <div className="user-wrap" ref={wrap}>
      <button
        ref={button}
        type="button"
        className="user"
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={`${id}-menu`}
        aria-label={`Account menu for ${display}`}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="avatar" aria-hidden="true">
          {name ? initials(name) : <Icon name="lock" />}
        </span>
        <span className="name">{display}</span>
        <Icon name="chevdown" className="chev" />
      </button>
      <div className="user-menu" id={`${id}-menu`} hidden={!open}>
        <p className="um-head">
          <strong>{display}</strong>
          <span>{subtitle}</span>
        </p>
        <Link className="um-item" href="/">
          Switch profile
        </Link>
        <Link className="um-item" href="/settings">
          Settings
        </Link>
        <Link className="um-item" href="/quality">
          Quality checks
        </Link>
        <div className="um-sep" role="separator" />
        <p className="um-label" id={`${id}-theme`}>
          Theme
        </p>
        <ThemeControl labelledBy={`${id}-theme`} />
      </div>
    </div>
  );
}

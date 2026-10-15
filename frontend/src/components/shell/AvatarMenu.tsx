"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { Icon } from "@/components/icons/Icon";
import { deleteMyData, signOut } from "@/lib/api";
import type { SessionAccount } from "@/ui-contracts/types";
import { ThemeControl } from "./ThemeControl";

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? [parts[0], parts[parts.length - 1]] : parts.slice(0, 1);
  return letters.map((p) => p[0]?.toUpperCase() ?? "").join("") || "?";
}

/**
 * Avatar → menu: who is signed in, Switch profile, Settings, Quality checks, Theme, then Sign in
 * with Google (guests), Sign out and Delete my data (inline confirm). Esc and outside click close.
 */
export function AvatarMenu({
  name,
  subtitle,
  account = null,
}: {
  name: string | null;
  subtitle: string;
  account?: SessionAccount | null;
}) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) {
      setConfirming(false);
      setFailed(false);
      return;
    }
    const onClick = (e: MouseEvent) => {
      // composedPath: a click that swaps the clicked button out (Delete → confirm) still counts as inside.
      if (wrap.current && !e.composedPath().includes(wrap.current)) setOpen(false);
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

  const leave = async (action: typeof signOut, to: string) => {
    setBusy(true);
    setFailed(false);
    if (await action()) {
      window.location.assign(to); // a full load: every server component re-reads the session
      return;
    }
    setBusy(false);
    setFailed(true);
  };

  const display = name ?? "No profile";
  const who =
    account?.kind === "google"
      ? `Signed in as ${account.email ?? account.name ?? "your Google account"}`
      : account
        ? "Guest: private to this browser, deleted after a week unused"
        : null;
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
        {account ? (
          <>
            <div className="um-sep" role="separator" />
            {who ? <p className="um-note">{who}</p> : null}
            {account.kind === "guest" ? (
              <a className="um-item" href="/api/auth/google/start?next=%2Fhome">
                Sign in with Google to keep your profiles
              </a>
            ) : null}
            <button
              type="button"
              className="um-item"
              disabled={busy}
              onClick={() => leave(signOut, "/?auth=signedout")}
            >
              Sign out
            </button>
            {confirming ? (
              <div className="um-confirm" role="group" aria-label="Confirm deleting your data">
                <p>
                  Delete every profile, import and conversation{" "}
                  {account.kind === "google" ? "on this account" : "in this browser"}? This can’t be undone.
                </p>
                <div className="um-actions">
                  <button
                    type="button"
                    className="btn danger"
                    disabled={busy}
                    onClick={() => leave(deleteMyData, "/?auth=deleted")}
                  >
                    {busy ? "Deleting…" : "Delete my data"}
                  </button>
                  <button type="button" className="btn" disabled={busy} onClick={() => setConfirming(false)}>
                    Keep it
                  </button>
                </div>
              </div>
            ) : (
              <button type="button" className="um-item danger" onClick={() => setConfirming(true)}>
                Delete my data
              </button>
            )}
            {failed ? (
              <p className="form-error" role="alert">
                That didn’t go through. Please try again.
              </p>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}

"use client";

/**
 * Settings: the profile's name, its buffer (the balance the forecast tries to stay above), the
 * fixed details imports depend on, and the person's data: sign out, delete, privacy. Each change
 * saves on its own and says when it's saved; a demo copy changes only this browser's copy.
 */
import Link from "next/link";
import { type FormEvent, useId, useState } from "react";

import { Button, CardHead } from "@/components/ui/primitives";
import { deleteMyData, signOut, updateProfile } from "@/lib/api";
import { formatMoney, minorDigits, parseAmountMinor, toMajor } from "@/lib/format";
import type { ProfileView } from "@/ui-contracts/types";

const COUNTRY: Record<string, string> = { GB: "United Kingdom", IN: "India" };

export function Settings({ initial }: { initial: ProfileView }) {
  const id = useId();
  const [profile, setProfile] = useState(initial);
  const [name, setName] = useState(initial.name);
  const [buffer, setBuffer] = useState(
    initial.buffer_minor == null
      ? ""
      : toMajor(initial.buffer_minor, initial.home_currency).toFixed(minorDigits(initial.home_currency)),
  );
  const [saved, setSaved] = useState<"name" | "buffer" | null>(null);
  const [problem, setProblem] = useState<{ on: "name" | "buffer" | "data"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<"delete" | "signout" | null>(null);
  const currency = profile.home_currency;
  const guest = profile.account?.kind !== "google";
  const demo = profile.kind === "demo";

  const save = async (on: "name" | "buffer", changes: Parameters<typeof updateProfile>[0]) => {
    setBusy(on);
    setSaved(null);
    setProblem(null);
    const next = await updateProfile(changes);
    setBusy(null);
    if (!next) {
      setProblem({ on, text: "That couldn’t be saved just now. Please try again." });
      return;
    }
    setProfile(next);
    setSaved(on);
  };

  const saveName = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return setProblem({ on: "name", text: "Enter a name for this profile." });
    void save("name", { name: name.trim() });
  };

  const saveBuffer = (e: FormEvent) => {
    e.preventDefault();
    if (!buffer.trim()) return void save("buffer", { bufferMinor: null });
    const minor = parseAmountMinor(buffer, currency);
    if (minor === null || minor < 0)
      return setProblem({ on: "buffer", text: "Enter an amount of zero or more, like 500 or 500.00." });
    void save("buffer", { bufferMinor: minor });
  };

  const leave = async (action: () => Promise<unknown>, to: string) => {
    setBusy("data");
    setProblem(null);
    if (await action()) {
      window.location.assign(to); // a full load: every server component re-reads the session
      return;
    }
    setBusy(null);
    setProblem({ on: "data", text: "That didn’t go through. Please try again." });
  };

  const note = (on: "name" | "buffer") =>
    problem?.on === on ? (
      <p className="form-error" role="alert">
        {problem.text}
      </p>
    ) : saved === on ? (
      <p className="set-saved" role="status">
        Saved.
      </p>
    ) : null;

  return (
    <div className="settings">
      <section className="card set-card" aria-labelledby={`${id}-profile`}>
        <CardHead
          icon="settings"
          title="Profile"
          titleId={`${id}-profile`}
          sub={
            demo ? "Fictional demo data. Changes stay in this browser’s copy." : "How this profile is named and set up."
          }
        />
        <form className="set-row" onSubmit={saveName} aria-label="Profile name">
          <div className="lab-field">
            <label htmlFor={`${id}-name`}>Name</label>
            <input
              id={`${id}-name`}
              value={name}
              maxLength={60}
              autoComplete="off"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={busy !== null || name.trim() === profile.name}>
            {busy === "name" ? "Saving…" : "Save name"}
          </Button>
          {note("name")}
        </form>
        <dl className="set-facts">
          <div>
            <dt>Country</dt>
            <dd>{COUNTRY[profile.country] ?? profile.country}</dd>
          </div>
          <div>
            <dt>Currency</dt>
            <dd>{currency}</dd>
          </div>
          <div>
            <dt>Time zone</dt>
            <dd>{profile.timezone}</dd>
          </div>
        </dl>
        <p className="set-note">
          These come from how the profile was created; imports and every figure use them, so they can’t be changed here.
        </p>
      </section>

      <section className="card set-card" aria-labelledby={`${id}-buffer`}>
        <CardHead
          icon="shield"
          title="Buffer"
          titleId={`${id}-buffer`}
          sub="The balance you’d like to stay above. Once Foresight knows your balance, the forecast draws it as a line and flags lows that dip below it."
        />
        <form className="set-row" onSubmit={saveBuffer} aria-label="Buffer amount">
          <div className="lab-field">
            <label htmlFor={`${id}-buf`}>Amount ({currency})</label>
            <input
              id={`${id}-buf`}
              inputMode="decimal"
              placeholder="500.00"
              value={buffer}
              onChange={(e) => setBuffer(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={busy !== null}>
            {busy === "buffer" ? "Saving…" : buffer.trim() ? "Save buffer" : "Clear buffer"}
          </Button>
          {note("buffer")}
        </form>
        <p className="set-note">
          {profile.buffer_minor == null
            ? "No buffer set. Leave it empty to keep it that way."
            : `Currently ${formatMoney(profile.buffer_minor, currency, profile.locale)}. Leave it empty and save to clear it.`}
        </p>
      </section>

      <section className="card set-card" aria-labelledby={`${id}-data`}>
        <CardHead icon="lock" title="Your data" titleId={`${id}-data`} sub="Sign out, or delete everything." />
        <p className="set-note">
          {guest
            ? "You’re a guest: your profiles are private to this browser and deleted after a week unused."
            : `Signed in as ${profile.account?.email ?? profile.account?.name ?? "your Google account"}.`}{" "}
          <Link href="/privacy">How Foresight handles your data</Link>
        </p>
        {confirming === "signout" ? (
          <div className="um-confirm" role="group" aria-label="Confirm signing out as a guest">
            <p>Signing out as a guest deletes your guest profiles. Sign in with Google first to keep them.</p>
            <div className="um-actions">
              <button
                type="button"
                className="btn danger"
                disabled={busy !== null}
                onClick={() => leave(signOut, "/?auth=signedout")}
              >
                {busy === "data" ? "Signing out…" : "Sign out and delete"}
              </button>
              <button type="button" className="btn" disabled={busy !== null} onClick={() => setConfirming(null)}>
                Keep them
              </button>
            </div>
          </div>
        ) : confirming === "delete" ? (
          <div className="um-confirm" role="group" aria-label="Confirm deleting your data">
            <p>
              Delete every profile, import and conversation {guest ? "in this browser" : "on this account"}? This can’t
              be undone.
            </p>
            <div className="um-actions">
              <button
                type="button"
                className="btn danger"
                disabled={busy !== null}
                onClick={() => leave(deleteMyData, "/?auth=deleted")}
              >
                {busy === "data" ? "Deleting…" : "Delete my data"}
              </button>
              <button type="button" className="btn" disabled={busy !== null} onClick={() => setConfirming(null)}>
                Keep it
              </button>
            </div>
          </div>
        ) : (
          <div className="btns">
            <Button
              disabled={busy !== null}
              onClick={() => (guest ? setConfirming("signout") : void leave(signOut, "/?auth=signedout"))}
            >
              Sign out
            </Button>
            <button
              type="button"
              className="btn danger"
              disabled={busy !== null}
              onClick={() => setConfirming("delete")}
            >
              Delete my data
            </button>
          </div>
        )}
        {problem?.on === "data" ? (
          <p className="form-error" role="alert">
            {problem.text}
          </p>
        ) : null}
      </section>
    </div>
  );
}

"use client";

import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { applyTheme, readTheme, saveTheme, THEME_CHOICES, type ThemeChoice } from "@/lib/theme";

const LABELS: Record<ThemeChoice, string> = { light: "Light", dark: "Dark", system: "System" };

/** Light / Dark / System as an ARIA radio group (arrow keys move and select). */
export function ThemeControl({ labelledBy }: { labelledBy?: string }) {
  const [choice, setChoice] = useState<ThemeChoice>("system");
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  useEffect(() => {
    setChoice(readTheme());
  }, []);

  const set = (next: ThemeChoice, focus = false) => {
    setChoice(next);
    saveTheme(next);
    applyTheme(next);
    if (focus) refs.current[next]?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"];
    if (!keys.includes(e.key)) return;
    e.preventDefault();
    const step = e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 1;
    const i = THEME_CHOICES.indexOf(choice);
    set(THEME_CHOICES[(i + step + THEME_CHOICES.length) % THEME_CHOICES.length], true);
  };

  return (
    <div
      className="theme-group"
      role="radiogroup"
      aria-label={labelledBy ? undefined : "Theme"}
      aria-labelledby={labelledBy}
      onKeyDown={onKeyDown}
    >
      {THEME_CHOICES.map((c) => (
        <button
          key={c}
          ref={(el) => {
            refs.current[c] = el;
          }}
          type="button"
          role="radio"
          className="theme-opt"
          aria-checked={choice === c}
          tabIndex={choice === c ? 0 : -1}
          onClick={() => set(c)}
        >
          {LABELS[c]}
        </button>
      ))}
    </div>
  );
}

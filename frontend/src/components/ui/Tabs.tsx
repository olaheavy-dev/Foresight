"use client";

import { type KeyboardEvent, type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";

export type TabItem = { id: string; label: string; content: ReactNode };

/**
 * ARIA tabs (WAI-ARIA Authoring Practices, automatic activation): arrow keys move between tabs,
 * Home/End jump to the ends, and the selected tab is mirrored in the URL hash (`#details`), so
 * the answer canvas tabs are linkable (IA: Answer skeleton).
 */
export function Tabs({
  items,
  label,
  syncHash = true,
  initial,
}: {
  items: TabItem[];
  label: string;
  syncHash?: boolean;
  initial?: string;
}) {
  const base = useId();
  const ids = items.map((t) => t.id);
  const [selected, setSelected] = useState<string>(
    initial && ids.includes(initial) ? initial : (ids[0] ?? ""),
  );
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  useEffect(() => {
    if (!syncHash) return;
    const fromHash = () => {
      const h = window.location.hash.slice(1);
      if (ids.includes(h)) setSelected(h);
    };
    fromHash();
    window.addEventListener("hashchange", fromHash);
    return () => window.removeEventListener("hashchange", fromHash);
    // ids is derived from items: re-subscribe only when the set of tabs changes.
  }, [syncHash, ids.join("|")]);

  const select = useCallback(
    (id: string, focus = false) => {
      setSelected(id);
      if (syncHash) window.history.replaceState(null, "", `#${id}`);
      if (focus) tabRefs.current[id]?.focus();
    },
    [syncHash],
  );

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const i = ids.indexOf(selected);
    const target =
      event.key === "ArrowRight"
        ? ids[(i + 1) % ids.length]
        : event.key === "ArrowLeft"
          ? ids[(i - 1 + ids.length) % ids.length]
          : event.key === "Home"
            ? ids[0]
            : event.key === "End"
              ? ids[ids.length - 1]
              : undefined;
    if (target === undefined) return;
    event.preventDefault();
    select(target, true);
  };

  return (
    <div className="tabs-wrap">
      <div className="tabs" role="tablist" aria-label={label}>
        {items.map((t) => {
          const on = t.id === selected;
          return (
            <button
              key={t.id}
              ref={(el) => {
                tabRefs.current[t.id] = el;
              }}
              type="button"
              role="tab"
              id={`${base}-tab-${t.id}`}
              aria-selected={on}
              aria-controls={`${base}-panel-${t.id}`}
              tabIndex={on ? 0 : -1}
              className="tab"
              onClick={() => select(t.id)}
              onKeyDown={onKeyDown}
            >
              {t.label}
            </button>
          );
        })}
      </div>
      {items.map((t) => (
        <div
          key={t.id}
          role="tabpanel"
          id={`${base}-panel-${t.id}`}
          aria-labelledby={`${base}-tab-${t.id}`}
          hidden={t.id !== selected}
          tabIndex={0}
          className="tab-panel"
        >
          {t.content}
        </div>
      ))}
    </div>
  );
}

import Link from "next/link";

/** Brand mark + wordmark. The three strokes take their colours from tokens (globals.css). */
export function Logo({ href = "/", label = "Foresight" }: { href?: string; label?: string }) {
  return (
    <Link className="logo" href={href} aria-label={label}>
      <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <path d="M7 11.5 27 5.5l-2.4 6.2L4.6 17.7Z" />
        <path d="M5.6 19.4 21.8 14.6l-2.2 5.6L3.4 25Z" />
        <path d="M4.4 26.6 13.8 23.8l-1.6 4L2.8 30.6Z" />
      </svg>
      <span className="wordmark">Foresight</span>
    </Link>
  );
}

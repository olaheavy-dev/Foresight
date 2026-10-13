"use client";

/**
 * Hydrated values and narrative segments. Every number on screen is the server's `display`
 * string for a value it computed (docs/08 §3.2); the client never formats or invents one, it
 * only adds the citation marker.
 */
import type { Segment, Value } from "@/ui-contracts/types";
import { Cite, useCitations } from "./citations";

export function ValueText({ value, cite = true }: { value: Value; cite?: boolean }) {
  return (
    <>
      <span className="num">{value.display}</span>
      {cite ? <Cite refId={value.ref} /> : null}
    </>
  );
}

export function Segments({ segments, strongValues = true }: { segments: Segment[]; strongValues?: boolean }) {
  const { number, open } = useCitations();
  return (
    <>
      {segments.map((s, i) => {
        if (s.kind === "text") return <span key={i}>{s.text}</span>;
        if (s.kind === "value") {
          const Tag = strongValues ? "strong" : "span";
          return (
            <Tag key={i}>
              <ValueText value={s.value} />
            </Tag>
          );
        }
        // An entity mention (finding, recommendation, check): a chip that opens its evidence.
        return number(s.ref) !== null ? (
          <button key={i} type="button" className="entity" onClick={() => open(s.ref)}>
            {s.label}
          </button>
        ) : (
          <span key={i} className="entity static">
            {s.label}
          </span>
        );
      })}
    </>
  );
}

/** Plain text of a segment list (thread bubbles, page titles). */
export function segmentsText(segments: Segment[]): string {
  return segments.map((s) => (s.kind === "text" ? s.text : s.kind === "value" ? s.value.display : s.label)).join("");
}

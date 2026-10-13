"use client";

/**
 * Numbered citations [n] (docs/05 §4.2 stage 5): every figure that names its source gets a
 * marker that opens the Evidence drawer for that calculation, finding or transaction set.
 * Numbers are assigned once per answer, in reading order (Overview slots, then the tabs), and
 * keyed by the base reference (`calc_…#path` → `calc_…`), so one calculation is one number.
 */
import { createContext, type ReactNode, useContext } from "react";
import type { Block, Segment, Value } from "@/ui-contracts/types";

export const baseRef = (ref: string) => ref.split("#")[0];

type CitationApi = {
  /** The marker number for a reference, or null when citations are off or it isn't numbered. */
  number: (ref: string) => number | null;
  open: (ref: string) => void;
};

const Ctx = createContext<CitationApi>({ number: () => null, open: () => {} });

export function CitationProvider({
  order,
  open,
  enabled,
  children,
}: {
  order: string[];
  open: (ref: string) => void;
  enabled: boolean;
  children: ReactNode;
}) {
  const api: CitationApi = enabled
    ? {
        number: (ref) => {
          const i = order.indexOf(baseRef(ref));
          return i === -1 ? null : i + 1;
        },
        open,
      }
    : { number: () => null, open: () => {} };
  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export const useCitations = () => useContext(Ctx);

/** A numbered marker. Renders nothing when the reference has no number (or citations are off). */
export function Cite({ refId }: { refId: string | null | undefined }) {
  const { number, open } = useCitations();
  if (!refId) return null;
  const n = number(refId);
  if (n === null) return null;
  return (
    <button type="button" className="cite" onClick={() => open(baseRef(refId))} aria-label={`Source ${n}: open the evidence`}>
      [{n}]
    </button>
  );
}

/** Sources line under a block: its evidence references as markers. */
export function Sources({ refs }: { refs: readonly string[] | undefined }) {
  const { number } = useCitations();
  const unique = [...new Set((refs ?? []).map(baseRef))].filter((r) => number(r) !== null);
  if (unique.length === 0) return null;
  return (
    <p className="sources">
      <span>Sources</span>
      {unique.map((r) => (
        <Cite key={r} refId={r} />
      ))}
    </p>
  );
}

function valueRefs(v: Value | null | undefined): string[] {
  return v?.ref ? [v.ref] : [];
}

function segmentRefs(segments: Segment[] | undefined): string[] {
  return (segments ?? []).flatMap((s) => (s.kind === "value" ? valueRefs(s.value) : s.kind === "entity" ? [s.ref] : []));
}

/** Every reference a block shows, in the order it shows them. */
export function blockRefs(block: Block): string[] {
  const own: string[] = [];
  switch (block.type) {
    case "Narrative":
      own.push(...segmentRefs(block.segments));
      break;
    case "FinancialMetricGroup":
      for (const m of block.metrics) own.push(...valueRefs(m.value), ...valueRefs(m.compare?.value));
      break;
    case "InterventionCard":
      own.push(...segmentRefs(block.rationale_segments));
      break;
    case "RiskAssessment":
      for (const r of block.risks) own.push(...(r.drivers ?? []).map((d) => d.ref));
      break;
    case "EvidencePanel":
      own.push(...block.items.map((i) => i.ref));
      break;
    default:
      break;
  }
  return [...own, ...(block.evidence ?? [])];
}

/** Assigns citation numbers in reading order. */
export function citationOrder(blocksInReadingOrder: Block[]): string[] {
  const out: string[] = [];
  for (const b of blocksInReadingOrder) {
    for (const r of blockRefs(b)) {
      const base = baseRef(r);
      if (!out.includes(base)) out.push(base);
    }
  }
  return out;
}

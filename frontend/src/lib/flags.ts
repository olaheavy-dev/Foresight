import type { Feature } from "@/ui-contracts/types";

/** A feature is shown only when its flag is on (docs/01 FR-86). Unknown or unreachable → off. */
export function isShipped(features: Feature[] | null, key: string): boolean {
  return features?.some((f) => f.key === key && f.enabled) ?? false;
}

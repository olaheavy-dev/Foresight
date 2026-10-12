export type Feature = {
  key: string;
  stage: number;
  title: string;
  enabled: boolean;
};

const apiBaseUrl = process.env.API_BASE_URL ?? "http://backend:8000";
const TIMEOUT_MS = 3000;

function isFeature(value: unknown): value is Feature {
  if (typeof value !== "object" || value === null) return false;
  const f = value as Record<string, unknown>;
  return (
    typeof f.key === "string" &&
    typeof f.stage === "number" &&
    typeof f.title === "string" &&
    typeof f.enabled === "boolean"
  );
}

/** Validates the /api/features payload. Anything malformed is treated as unavailable, so the UI
 * never shows a feature as shipped on the strength of a bad response. */
export function parseFeatures(body: unknown): Feature[] | null {
  if (typeof body !== "object" || body === null) return null;
  const features = (body as { features?: unknown }).features;
  if (!Array.isArray(features) || !features.every(isFeature)) return null;
  return features;
}

/** Reads feature flags from the backend, giving up after a short timeout. */
export async function fetchFeatures(
  fetchImpl: typeof fetch = fetch,
  timeoutMs: number = TIMEOUT_MS,
): Promise<Feature[] | null> {
  try {
    const response = await fetchImpl(`${apiBaseUrl}/api/features`, {
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) return null;
    return parseFeatures(await response.json());
  } catch {
    return null;
  }
}

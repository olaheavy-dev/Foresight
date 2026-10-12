export type Feature = {
  key: string;
  stage: number;
  title: string;
  enabled: boolean;
};

const apiBaseUrl = process.env.API_BASE_URL ?? "http://backend:8000";

/** Reads feature flags from the backend. Disabled features are never shown as working. */
export async function fetchFeatures(): Promise<Feature[] | null> {
  try {
    const response = await fetch(`${apiBaseUrl}/api/features`, { cache: "no-store" });
    if (!response.ok) return null;
    const body = (await response.json()) as { features: Feature[] };
    return body.features;
  } catch {
    return null;
  }
}

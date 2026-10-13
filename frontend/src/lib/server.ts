import { headers } from "next/headers";
import { fetchFeatures, fetchProfile, type ApiOptions } from "@/lib/api";

/** Server calls go straight to the backend and must forward the browser's session cookie. */
export async function apiOptions(): Promise<ApiOptions> {
  const cookie = (await headers()).get("cookie") ?? undefined;
  return { cookie };
}

/** What every app page needs: the active profile (or null) and the feature flags (or null). */
export async function loadShell() {
  const options = await apiOptions();
  const [profile, features] = await Promise.all([fetchProfile(options), fetchFeatures(options)]);
  return { profile, features, options };
}

const API = process.env.API_BASE_URL ?? "http://backend:8000";

/**
 * The demo profile's forecast for the public Landing preview. The server opens its own demo
 * session (the demo profile is read-only and shared), so the visitor's browser gets no cookie
 * until they choose "Explore the live demo".
 */
export async function demoForecast() {
  try {
    const res = await fetch(`${API}/api/session/demo?persona=P1`, {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return null;
    const cookie = res.headers
      .getSetCookie()
      .map((c) => c.split(";")[0])
      .join("; ");
    if (!cookie) return null;
    const { fetchForecast } = await import("@/lib/api");
    return await fetchForecast("mine", { cookie });
  } catch {
    return null;
  }
}

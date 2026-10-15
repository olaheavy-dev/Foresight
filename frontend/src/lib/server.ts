import { headers } from "next/headers";
import { fetchDemoForecast, fetchFeatures, fetchProfile, type ApiOptions } from "@/lib/api";

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

/**
 * The fictional demo's forecast for the public Landing preview. A public read-only endpoint:
 * the visitor's browser gets no cookie until they choose to continue as a guest.
 */
export async function demoForecast() {
  return fetchDemoForecast();
}

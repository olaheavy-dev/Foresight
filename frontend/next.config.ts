import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api and /healthz are proxied to the private
// backend container, so there is no CORS and the backend has no public port (docs/05 §12).
const apiBaseUrl = process.env.API_BASE_URL ?? "http://backend:8000";

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  devIndicators: false,
  // `fallback`: app route handlers win first (app/api/runs/[runId]/events streams the answer
  // events itself, unbuffered); every other /api path goes straight to the backend.
  async rewrites() {
    return {
      beforeFiles: [],
      afterFiles: [{ source: "/healthz", destination: `${apiBaseUrl}/healthz` }],
      fallback: [{ source: "/api/:path*", destination: `${apiBaseUrl}/api/:path*` }],
    };
  },
};

export default config;

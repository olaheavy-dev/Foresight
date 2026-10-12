import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api and /healthz are proxied to the private
// backend container, so there is no CORS and the backend has no public port (docs/05 §12).
const apiBaseUrl = process.env.API_BASE_URL ?? "http://backend:8000";

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiBaseUrl}/api/:path*` },
      { source: "/healthz", destination: `${apiBaseUrl}/healthz` },
    ];
  },
};

export default config;

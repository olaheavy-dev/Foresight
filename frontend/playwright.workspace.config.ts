import { defineConfig, devices } from "@playwright/test";

// AI Workspace journeys against the scripted mock API (e2e/mock-api.mjs), so the run stream,
// clarifying questions and failures are deterministic. The default config runs the smoke
// journeys against a real stack; this one starts its own mock API and Next dev server.
const API_PORT = 8787;
const WEB_PORT = 3100;

export default defineConfig({
  testDir: "./e2e",
  testMatch: /workspace(\.screenshots)?\.spec\.ts$/,
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  use: { baseURL: `http://localhost:${WEB_PORT}`, trace: "retain-on-failure" },
  webServer: [
    {
      command: `node e2e/mock-api.mjs`,
      env: { MOCK_API_PORT: String(API_PORT), MOCK_SPEED: "0.5" },
      port: API_PORT,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: `npx next dev --port ${WEB_PORT}`,
      env: { API_BASE_URL: `http://127.0.0.1:${API_PORT}`, NEXT_TELEMETRY_DISABLED: "1" },
      port: WEB_PORT,
      timeout: 180_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
    { name: "desktop-dark", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 }, colorScheme: "dark" } },
  ],
});

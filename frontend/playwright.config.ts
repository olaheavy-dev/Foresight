import { defineConfig, devices } from "@playwright/test";

// Journeys run against a real stack: `docker compose up` locally and in CI, or the live URL
// for post-deploy smoke tests (BASE_URL=https://foresight.olaheavy.dev).
export default defineConfig({
  testDir: "./e2e",
  // Workspace journeys need the scripted mock API: playwright.workspace.config.ts.
  testIgnore: /workspace(\.screenshots)?\.spec\.ts$/,
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: process.env.BASE_URL ?? "http://localhost:3000", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
    // Same journeys and axe checks with the OS in dark mode, so dark tokens are tested too.
    { name: "desktop-dark", use: { ...devices["Desktop Chrome"], colorScheme: "dark" } },
  ],
});

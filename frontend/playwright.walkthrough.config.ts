import { defineConfig } from "@playwright/test";

// The portfolio walkthrough (e2e/walkthrough.spec.ts): one scripted tour recorded as video on the
// live site. It asks real questions, so it spends a little OpenAI credit: run it only on purpose,
// `WALKTHROUGH=1 npx playwright test -c playwright.walkthrough.config.ts`.
export default defineConfig({
  testDir: "./e2e",
  testMatch: /walkthrough\.spec\.ts$/,
  timeout: 6 * 60_000,
  expect: { timeout: 90_000 },
  retries: 0,
  workers: 1,
  outputDir: "test-results/walkthrough",
  use: {
    baseURL: process.env.BASE_URL ?? "https://foresight.olaheavy.dev",
    viewport: { width: 1280, height: 800 },
    video: { mode: "on", size: { width: 1280, height: 800 } },
    colorScheme: "light",
  },
});

// Design-review screenshots of the AI Workspace on the scripted mock API.
//   SCREENSHOTS=1 npx playwright test -c playwright.workspace.config.ts workspace.screenshots --project=desktop
// Files: .design/foresight/screenshots/app-workspace-<state>-<device>-<width>[-dark-mode].png
import { expect, type Page, test } from "@playwright/test";

test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture design-review screenshots");
test.describe.configure({ mode: "serial" });
test.setTimeout(120_000);

const OUT = "../.design/foresight/screenshots";
const SIZES = [
  { device: "mobile", width: 375, height: 812 },
  { device: "tablet", width: 768, height: 1024 },
  { device: "desktop", width: 1280, height: 800 },
  { device: "desktop", width: 1440, height: 900 },
] as const;
const THEMES = ["light", "dark"] as const;
const MOCK = "http://localhost:8787";

const file = (state: string, s: (typeof SIZES)[number], theme: string) =>
  `${OUT}/app-workspace-${state}-${s.device}-${s.width}${theme === "dark" ? "-dark-mode" : ""}.png`;

async function open(page: Page, s: (typeof SIZES)[number], theme: string) {
  await page.setViewportSize({ width: s.width, height: s.height });
  await page.emulateMedia({ colorScheme: theme === "dark" ? "dark" : "light", reducedMotion: "reduce" });
  await page.goto(`/workspace?theme=${theme}`);
  await page.evaluate(() => sessionStorage.clear());
  await page.goto(`/workspace?theme=${theme}`);
  await page.evaluate(() => document.fonts.ready);
}

async function ask(page: Page, text: string) {
  await page.getByLabel("Ask a question").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

const shot = async (page: Page, path: string) => {
  await page.mouse.move(0, 0);
  await page.screenshot({ path, animations: "disabled" });
};

test.beforeEach(async ({ page }) => {
  await page.request.post(`${MOCK}/__mock/ai-status`, { data: { status: "ok" } });
});

for (const theme of THEMES) {
  for (const s of SIZES) {
    test(`welcome, answers · ${s.width} ${theme}`, async ({ page }) => {
      await open(page, s, theme);
      await expect(page.getByRole("heading", { name: "Ask anything about your money." })).toBeVisible();
      await shot(page, file("welcome", s, theme));

      await ask(page, "Can I afford a trip in December?");
      await expect(page.getByRole("heading", { level: 1, name: /27 November payday/ })).toBeVisible({
        timeout: 20_000,
      });
      await page.waitForTimeout(300);
      await shot(page, file("answer", s, theme));

      await open(page, s, theme);
      await ask(page, "Why is my spending up?");
      await expect(page.getByRole("heading", { level: 1, name: "Eating out is up on a usual month." })).toBeVisible({
        timeout: 20_000,
      });
      await page.waitForTimeout(300);
      await shot(page, file("spending", s, theme));
    });
  }
}

for (const theme of THEMES) {
  for (const s of [SIZES[0], SIZES[3]]) {
    test(`AI paused · ${s.width} ${theme}`, async ({ page }) => {
      await page.request.post(`${MOCK}/__mock/ai-status`, { data: { status: "unavailable" } });
      await open(page, s, theme);
      await expect(page.locator(".dock .ai-notice")).toBeVisible();
      await shot(page, file("ai-paused", s, theme));
    });
  }
}

test("states at 1440 · light", async ({ page }) => {
  const s = SIZES[3];
  await open(page, s, "light");
  await ask(page, "Can I afford a trip in December?");
  await expect(page.locator(".loading-view").getByText("Verifier rejected a draft")).toBeVisible({ timeout: 20_000 });
  await shot(page, file("loading", s, "light"));

  await expect(page.getByRole("heading", { level: 1, name: /27 November payday/ })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: /Checked by 6 agents/ }).click();
  await page.locator(".canvas").evaluate((el) => el.scrollTo(0, el.scrollHeight));
  await shot(page, file("evidence-line-open", s, "light"));

  await page.getByRole("tab", { name: "How it was checked" }).click();
  await page.locator(".canvas").evaluate((el) => el.scrollTo(0, 0));
  await shot(page, file("checked", s, "light"));

  await page.getByRole("tab", { name: "Recommendation" }).click();
  await shot(page, file("recommendation", s, "light"));

  await page.getByRole("tab", { name: "Overview" }).click();
  await page
    .getByRole("button", { name: /^Source 1:/ })
    .first()
    .click();
  await expect(page.getByRole("dialog", { name: "Calculation" }).getByText("fc-test")).toBeVisible();
  await shot(page, file("evidence-drawer", s, "light"));
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "New question" }).click();
  await ask(page, "Can I afford a trip?");
  await expect(page.getByRole("heading", { name: "Which trip did you mean?" })).toBeVisible({ timeout: 20_000 });
  await shot(page, file("clarify", s, "light"));

  await page.getByRole("button", { name: "New question" }).click();
  await ask(page, "How does next month look?");
  await expect(page.getByRole("region", { name: "Analysis" }).getByRole("alert")).toBeVisible({ timeout: 20_000 });
  await shot(page, file("error", s, "light"));
});

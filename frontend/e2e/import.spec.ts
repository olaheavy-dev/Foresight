// Import / onboarding on a real stack (docker compose): landing → /start → upload → check → Home.
// SCREENSHOTS=1 also writes design-review captures to .design/foresight/screenshots/.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const CSV = "../evals/datasets/P1-base/exports/monzo.csv";
const OUT = "../.design/foresight/screenshots";

async function shot(page: Page, name: string, project: string) {
  if (!process.env.SCREENSHOTS) return;
  await page.mouse.move(0, 0);
  await page.screenshot({
    path: `${OUT}/review-import-${name}-${project}.png`,
    fullPage: true,
    animations: "disabled",
  });
}

async function noSeriousA11yIssues(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
}

test("a Monzo CSV imports, asks for today's balance, then forecasts", async ({ page }, info) => {
  await page.context().clearCookies();
  await page.goto("/");
  await page.getByRole("link", { name: /Import a CSV statement/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Drop your statements" })).toBeVisible();
  await shot(page, "files-empty", info.project.name);

  await page.getByLabel("Choose statement files").setInputFiles(CSV);
  const result = page.getByRole("list", { name: "Your files" }).getByRole("listitem").first();
  await expect(result).toContainText("Imported", { timeout: 30_000 });
  await expect(result).toContainText("Monzo");
  await expect(result).toContainText("No balance column");
  await noSeriousA11yIssues(page);
  await shot(page, "files-done", info.project.name);

  await page.getByRole("button", { name: "Check what we found" }).click();
  await page.waitForURL("**/start?step=check");
  await expect(page.getByRole("heading", { level: 1, name: "Check what we found" })).toBeVisible();
  await expect(page.getByText("Balance needed")).toBeVisible();
  await expect(page.locator("#inc-h")).toBeVisible();
  await noSeriousA11yIssues(page);
  await shot(page, "check-balance-needed", info.project.name);

  await page.getByLabel("Balance").fill("abc");
  await page.getByRole("button", { name: "Save balance" }).click();
  await expect(page.locator(".balance-form [role=alert]")).toContainText("Enter an amount like");
  await page.getByLabel("Balance").fill("1,234.56");
  await page.getByRole("button", { name: "Save balance" }).click();
  await expect(page.getByText("you told us")).toBeVisible();
  await expect(page.getByText("Balance needed")).toHaveCount(0);
  await shot(page, "check-done", info.project.name);

  await page.getByRole("link", { name: "See your forecast" }).click();
  await page.waitForURL("**/home");
  // The first forecast after an import is computed on demand.
  await expect(page.getByText("£1,234.56")).toBeVisible({ timeout: 15_000 });
  // R2: the import queued a proactive check, which Home reports while it waits to run.
  await expect(page.getByRole("region", { name: "Proactive insights" })).toContainText("Checking your latest changes");
});

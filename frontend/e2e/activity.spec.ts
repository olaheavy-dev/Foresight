// Activity on the real stack: the audit log in words, with the chain check, after the person's own changes.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const CSV = "../evals/datasets/P1-base/exports/monzo.csv";

async function noSeriousA11yIssues(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
}

test("Activity asks for a profile before there is one", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/activity");
  await expect(page.getByRole("heading", { level: 1, name: "Activity" })).toBeVisible();
  await expect(page.getByText("Choose the demo profile or import a statement first.")).toBeVisible();
});

test("Activity lists an import and a payee-wide correction in words, with the audit chain intact", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/start");
  await page.getByLabel("Choose statement files").setInputFiles(CSV);
  await expect(page.getByRole("list", { name: "Your files" })).toContainText("Imported", { timeout: 30_000 });
  await page.goto("/transactions");
  await page.getByPlaceholder("Search payee or description").fill("deliveroo");
  await page.locator(".lr-category").first().click();
  await page.locator(".lr-edit select").selectOption("food.eating_out");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".lr-category").first()).toContainText("Eating out");

  await page.goto("/activity");
  await expect(page.getByRole("heading", { name: "Agent runs" })).toBeVisible();
  const changes = page.getByRole("region", { name: "Changes" });
  await expect(changes).toContainText("Audit chain intact");
  // One correction applied to every payment from the payee is one line, not one per row.
  await expect(changes.getByText(/Changed the category of \d+ transactions/)).toHaveCount(1);
  await expect(changes).toContainText(/Imported (a table|\d+ tables) of transactions/);
  await expect(changes).toContainText("You ·");
  await expect(page.getByText("Traces stay on Foresight’s own servers")).toBeVisible();
  await noSeriousA11yIssues(page);
});

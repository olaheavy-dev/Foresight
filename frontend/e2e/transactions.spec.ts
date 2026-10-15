// Transactions on a real stack (docker compose). SCREENSHOTS=1 writes design-review captures.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const CSV = "../evals/datasets/P1-base/exports/monzo.csv";
const OUT = "../.design/foresight/screenshots";

async function shot(page: Page, name: string, project: string) {
  if (!process.env.SCREENSHOTS) return;
  await page.mouse.move(0, 0);
  await page.screenshot({
    path: `${OUT}/review-transactions-${name}-${project}.png`,
    fullPage: true,
    animations: "disabled",
  });
}

async function noSeriousA11yIssues(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
}

test("the demo ledger: search, review queue, recurring, imports, read-only corrections", async ({ page }, info) => {
  await page.context().clearCookies();
  await page.goto("/");
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  await page.waitForURL("**/home");
  await page.goto("/transactions");
  await expect(page.getByRole("heading", { level: 1, name: "Transactions" })).toBeVisible();
  await expect(page.getByText(/^Showing \d+ of \d+$/)).toBeVisible();
  await noSeriousA11yIssues(page);
  await shot(page, "all", info.project.name);

  await page.getByPlaceholder("Search payee or description").fill("deliveroo");
  await expect(page.locator(".lr-payee").first()).toContainText(/deliveroo/i);
  await page.locator(".lr-category").first().click();
  await expect(page.getByText("The demo profile is read-only.")).toBeVisible();
  await shot(page, "search-edit", info.project.name);

  await page.getByRole("link", { name: /To review/ }).click();
  await expect(page.getByRole("heading", { name: "To review" })).toBeVisible();
  await shot(page, "review", info.project.name);

  await page.getByRole("link", { name: "Recurring and income" }).click();
  await expect(page.getByRole("heading", { name: "Regular payments" })).toBeVisible();
  await expect(page.locator(".flow-list").first().locator("li").first()).toBeVisible();
  await noSeriousA11yIssues(page);
  await shot(page, "recurring", info.project.name);

  await page.getByRole("link", { name: "Imports", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Imports" })).toBeVisible();
  await expect(page.getByText("Imported").first()).toBeVisible();
  await shot(page, "imports", info.project.name);
});

test("an own profile corrects a category for every row from the payee", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/start");
  await page.getByLabel("Choose statement files").setInputFiles(CSV);
  await expect(page.getByRole("list", { name: "Your files" })).toContainText("Imported", { timeout: 30_000 });
  await page.goto("/transactions");
  await page.getByPlaceholder("Search payee or description").fill("deliveroo");
  await expect(page.locator(".lr-payee").first()).toContainText(/deliveroo/i);
  await page.locator(".lr-category").first().click();
  await page.locator(".lr-edit select").selectOption("food.eating_out");
  await expect(page.getByLabel(/Apply to all from/)).toBeChecked();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".lr-category").first()).toContainText("Eating out");
  await expect(page.locator(".lr-category").first()).toContainText("You");
  await expect(page.locator(".lr-category").nth(1)).toContainText("You");
});

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

test("the demo ledger: search, a correction on your own copy, review queue, recurring, imports", async ({
  page,
}, info) => {
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
  await expect(page.getByText("Changes here only affect your copy of the demo.")).toBeVisible();
  await page.locator(".lr-category").first().click();
  await page.locator(".lr-edit select").selectOption("food.eating_out");
  await shot(page, "search-edit", info.project.name);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.locator(".lr-category").first()).toContainText("Eating out");
  await expect(page.locator(".lr-category").first()).toContainText("You");

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

test("Reset demo swaps a corrected demo for a fresh copy", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/");
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  await page.waitForURL("**/home");
  await page.goto("/transactions");
  await page.getByPlaceholder("Search payee or description").fill("deliveroo");
  const first = page.locator(".lr-category").first();
  await expect(first).not.toContainText("You");
  await first.click();
  await page.locator(".lr-edit select").selectOption("food.eating_out");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(first).toContainText("You");

  await page.getByRole("button", { name: /account menu/i }).click();
  await page.getByRole("button", { name: "Reset demo" }).click();
  const confirm = page.getByRole("group", { name: "Confirm resetting the demo" });
  await expect(confirm).toBeVisible();
  await noSeriousA11yIssues(page);
  await confirm.getByRole("button", { name: "Reset demo" }).click();
  await page.waitForURL("**/home");
  await page.goto("/transactions");
  await page.getByPlaceholder("Search payee or description").fill("deliveroo");
  await expect(page.locator(".lr-payee").first()).toContainText(/deliveroo/i);
  await expect(page.locator(".lr-category").first()).not.toContainText("You");
});

test("an own profile confirms its income or says it isn't income (R4)", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/start");
  await page.getByLabel("Choose statement files").setInputFiles(CSV);
  await expect(page.getByRole("list", { name: "Your files" })).toContainText("Imported", { timeout: 30_000 });
  await page.goto("/transactions?tab=recurring");
  const income = page.getByRole("region", { name: "Income" });
  const first = income.getByRole("group", { name: /your income\?/ }).first();
  await expect(first).toContainText("Detected");
  // A failed save says so and leaves the controls usable (#44 review: the error path).
  await page.route("**/api/income/**", (route) => route.fulfill({ status: 500, body: "{}" }));
  await first.getByRole("button", { name: "Yes, it’s my income" }).click();
  await expect(first.getByRole("alert")).toContainText("That didn’t save");
  await expect(first.getByRole("button", { name: "Yes, it’s my income" })).toBeEnabled();
  await expect(first).toContainText("Detected");
  await page.unroute("**/api/income/**");
  await first.getByRole("button", { name: "Yes, it’s my income" }).click();
  await expect(first).toContainText("Confirmed by you");
  await noSeriousA11yIssues(page);
  await first.getByRole("button", { name: "Undo" }).click();
  await expect(first).toContainText("Detected");
  await first.getByRole("button", { name: "Not income" }).click();
  await expect(first).toContainText("Not counted as income");
  // The decision survives a reload: it's stored, not just shown.
  await page.reload();
  await expect(page.getByRole("region", { name: "Income" }).getByRole("group").first()).toContainText(
    "Not counted as income",
  );
});

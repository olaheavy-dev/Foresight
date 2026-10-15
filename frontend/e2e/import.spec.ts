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

// R5: a bank we don't recognise is a question the person can answer, not a dead end.
const ODD_BANK = [
  "Posted On,Payee Text,Value (GBP),Running Total,Ref",
  "01/10/2026,SALARY ACME LTD,2100.00,2600.00,A1",
  "02/10/2026,TESCO STORES,-42.10,2557.90,A2",
  "03/10/2026,RENT OCTOBER,-950.00,1607.90,A3",
  "15/10/2026,DELIVEROO,-18.40,1589.50,A4",
].join("\n");

test("an unrecognised bank's CSV is mapped column by column, then imports", async ({ page }, info) => {
  await page.context().clearCookies();
  await page.goto("/start");
  await page
    .getByLabel("Choose statement files")
    .setInputFiles({ name: "odd-bank.csv", mimeType: "text/csv", buffer: Buffer.from(ODD_BANK) });
  const result = page.getByRole("list", { name: "Your files" }).getByRole("listitem").first();
  await expect(result).toContainText("Needs an answer", { timeout: 30_000 });
  const form = page.getByRole("form", { name: "Columns in odd-bank.csv" });
  await expect(form).toContainText("We didn’t recognise this file’s columns");
  // Recognised columns are pre-filled; each choice shows an example from the file.
  await expect(form.getByLabel("Amount", { exact: true })).toHaveValue("c2"); // options are opaque column ids, labelled with the heading
  await expect(form.getByLabel("Amount", { exact: true }).locator("option:checked")).toHaveText(
    "value (gbp) (e.g. 2100.00)",
  );
  await expect(
    form.getByLabel("Description", { exact: true }).locator("option", { hasText: "SALARY ACME LTD" }),
  ).toHaveCount(1);
  await noSeriousA11yIssues(page);
  await shot(page, "columns", info.project.name);

  await form.getByRole("button", { name: "Import with these columns" }).click();
  await expect(form.getByRole("alert")).toContainText("Choose a column for date, description, amount");

  await form.getByLabel("Date", { exact: true }).selectOption({ label: "posted on (e.g. 01/10/2026)" });
  await form.getByLabel("Description", { exact: true }).selectOption({ label: "payee text (e.g. SALARY ACME LTD)" });
  await form.getByLabel("Balance after each row (optional)").selectOption({ label: "running total (e.g. 2600.00)" });
  await form.getByRole("button", { name: "Import with these columns" }).click();
  await expect(result).toContainText("Imported", { timeout: 30_000 });
  await expect(result).toContainText("Every row adds up to the running balance");
  await expect(result).toContainText("4 imported of 4 read");
});

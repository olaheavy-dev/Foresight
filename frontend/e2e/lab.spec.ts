// Decision Lab (R8) on the real stack: build a what-if from the demo's own data and compare it.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

async function noSeriousA11yIssues(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
}

test("Decision Lab compares a spread purchase with the current path, and explains a refusal", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/");
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  await page.waitForURL("**/home");
  await page.goto("/lab");
  await expect(page.getByRole("heading", { level: 1, name: "Decision Lab" })).toBeVisible();

  await page.getByRole("radio", { name: /Spread a purchase/ }).check();
  const form = page.getByRole("form", { name: "Scenario details" });
  await form.getByRole("button", { name: "Test it" }).click();
  await expect(form.getByRole("alert")).toContainText("Enter the total amount");

  await form.getByLabel("Total amount").fill("900");
  await form.getByLabel("Payments").selectOption("3");
  await form.getByRole("button", { name: "Test it" }).click();
  const result = page.getByRole("region", { name: "Result" });
  await expect(result).toContainText("Spread over 3 payments", { timeout: 15_000 });
  await expect(result.getByRole("img").first()).toBeVisible();
  await expect(result).toContainText("No AI was used");
  await noSeriousA11yIssues(page);

  // Income from /api/detected, sent as the documented income_stream_id.
  await page.getByRole("radio", { name: /My income changes/ }).check();
  await form.getByLabel("Change").selectOption("-10");
  await form.getByRole("button", { name: "Test it" }).click();
  await expect(result).toContainText("Income -10%", { timeout: 15_000 });

  // The engine refuses a date beyond the forecast; the reason reaches the person.
  await page.getByRole("radio", { name: /A one-off purchase/ }).check();
  await form.getByLabel("Amount", { exact: true }).fill("100");
  await form.getByLabel("Date").fill("2031-01-01");
  await form.getByRole("button", { name: "Test it" }).click();
  await expect(form.getByRole("alert")).toContainText("outside the forecast horizon");
  await expect(result).toHaveCount(0); // the income result isn't left beside the refusal
});

test("a spread isn't checked against today when the forecast's date can't load (#48 review)", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/");
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  await page.waitForURL("**/home");
  await page.route("**/api/forecast*", (route) => route.fulfill({ status: 500, body: "{}" }));
  await page.goto("/lab");
  await page.getByRole("radio", { name: /Spread a purchase/ }).check();
  const form = page.getByRole("form", { name: "Scenario details" });
  await form.getByLabel("Total amount").fill("900");
  await form.getByRole("button", { name: "Test it" }).click();
  await expect(form.getByRole("alert")).toContainText("Your forecast couldn’t load");
  await expect(page.getByRole("region", { name: "Result" })).toHaveCount(0);
});

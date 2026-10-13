import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

async function noSeriousA11yIssues(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious).toEqual([]);
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

async function openDemo(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  await page.waitForURL("**/home");
}

test("landing offers the demo and CSV import, with sign-in disabled", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Start with your own statements" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Explore the live demo" })).toBeEnabled();
  await expect(page.getByRole("link", { name: "Import a CSV statement" })).toHaveAttribute("href", "/start");
  await expect(page.getByRole("button", { name: /sign in/i })).toBeDisabled();
  await noHorizontalScroll(page);
  await noSeriousA11yIssues(page);
});

test("the demo opens Home, where each section is drawn from the engine or says it isn't shipped", async ({ page }) => {
  await openDemo(page);
  await expect(page.getByRole("heading", { level: 1, name: "Your money, a few steps ahead." })).toBeVisible();
  await expect(page.getByText("Demo data")).toBeVisible();
  const chart = page.getByRole("img", { name: /lowest balance forecast before each payday/i });
  const notShipped = page.getByText("Not shipped yet");
  await expect(chart.or(notShipped).first()).toBeVisible();
  await noHorizontalScroll(page);
  await noSeriousA11yIssues(page);
});

test("navigation reaches the other sections, which say honestly that they aren't shipped", async ({ page }) => {
  await openDemo(page);
  for (const name of ["Activity", "Transactions"]) {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name }).click();
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
    await expect(page.getByText("Not shipped yet").first()).toBeVisible();
  }
});

test("health endpoint is proxied to the backend and reports a deploy SHA", async ({ request }) => {
  const response = await request.get("/healthz");
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(typeof body.sha).toBe("string");
  if (process.env.EXPECTED_SHA) expect(body.sha).toBe(process.env.EXPECTED_SHA);
});

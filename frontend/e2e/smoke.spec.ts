import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("home loads, shows honest shipping status and passes accessibility checks", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Foresight" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Not shipped yet" })).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious).toEqual([]);
});

test("health endpoint is proxied to the backend and reports a deploy SHA", async ({ request }) => {
  const response = await request.get("/healthz");
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(typeof body.sha).toBe("string");
  if (process.env.EXPECTED_SHA) expect(body.sha).toBe(process.env.EXPECTED_SHA);
});

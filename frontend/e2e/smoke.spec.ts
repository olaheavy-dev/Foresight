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

test("landing offers the demo and CSV import as a guest; Google appears only when configured", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Start with your own statements" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Explore the live demo" })).toBeEnabled();
  await expect(page.getByRole("link", { name: "Import a CSV statement" })).toHaveAttribute("href", "/start");
  // Google shows only when the API has a client configured.
  const providers = await (await page.request.get("/api/auth/providers")).json();
  const google = page.getByRole("link", { name: "Continue with Google" });
  if (providers.google) await expect(google).toHaveAttribute("href", "/api/auth/google/start?next=%2Fhome");
  else await expect(google).toHaveCount(0);
  await noHorizontalScroll(page);
  await noSeriousA11yIssues(page);

  await page.goto("/?auth=failed");
  await expect(page.getByRole("alert").filter({ hasText: "Google sign-in didn’t finish" })).toBeVisible();
});

test("the privacy page is public and says how to delete your data", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: /^Privacy/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "How Foresight handles your data" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Deleting your data" })).toBeVisible();
  // The guest allowance is counted with a one-way code, in memory only (backend/app/network_cap.py).
  await expect(page.getByText(/Guests share a daily allowance of AI questions and checks per network/)).toBeVisible();
  await noHorizontalScroll(page);
  await noSeriousA11yIssues(page);
});

test("the account menu signs a guest out and asks before deleting their data", async ({ page }) => {
  await openDemo(page);
  await page.getByRole("button", { name: /account menu/i }).click();
  await expect(page.getByText(/Guest: private to this browser/)).toBeVisible();
  await expect(page.getByRole("link", { name: /sign in with google/i })).toHaveAttribute(
    "href",
    "/api/auth/google/start?next=%2Fhome",
  );
  await page.getByRole("button", { name: "Delete my data" }).click();
  const confirm = page.getByRole("group", { name: "Confirm deleting your data" });
  await expect(confirm).toContainText("can’t be undone");
  await noSeriousA11yIssues(page);
  await confirm.getByRole("button", { name: "Keep it" }).click();
  await expect(confirm).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out" }).click();
  const leaving = page.getByRole("group", { name: "Confirm signing out as a guest" });
  await expect(leaving).toContainText("deletes your guest profiles");
  await leaving.getByRole("button", { name: "Sign out and delete" }).click();
  await page.waitForURL("**/?auth=signedout");
  await expect(page.getByRole("status").filter({ hasText: "You’re signed out." })).toBeVisible();
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

test("Home shows the demo's findings, and each links to its transactions (R2)", async ({ page }) => {
  await openDemo(page);
  const insights = page.getByRole("region", { name: "Proactive insights" });
  await expect(insights).toBeVisible();
  // The local and CI stacks have no Mesh key: findings show, advice says why it isn't there.
  await expect(insights).toContainText("come straight from the demo’s data");
  const findings = insights.getByRole("list", { name: "Findings" }).getByRole("listitem");
  await expect(findings.first()).toBeVisible();
  await expect(insights).not.toContainText("{{"); // every figure filled from its calculation
  await noSeriousA11yIssues(page);
  const link = insights.getByRole("link", { name: /See the transactions/ }).first();
  const href = await link.getAttribute("href");
  await link.click();
  await page.waitForURL(`**${href}`);
  await expect(page.getByRole("heading", { level: 1, name: "Transactions" })).toBeVisible();
  // Exactly the finding's rows (the evidence chain's last step), with a way back to all of them.
  expect(href).toMatch(/^\/transactions\?finding=fnd_/);
  await expect(page.getByRole("status").filter({ hasText: "transactions behind a finding" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Show all transactions" })).toBeVisible();
});

test("navigation reaches each section; unshipped ones say so honestly", async ({ page }) => {
  await openDemo(page);
  const nav = page.getByRole("navigation", { name: "Main" });
  await nav.getByRole("link", { name: "Activity" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Activity" })).toBeVisible();
  // Activity ships: agent runs as traces and the audit log, chain intact.
  await expect(page.getByRole("region", { name: "Changes" })).toContainText("Audit chain intact");
  await expect(page.getByRole("region", { name: "Changes" })).toContainText(
    /Imported (a table|\d+ tables) of transactions/,
  );
  await noSeriousA11yIssues(page);
  // Transactions ships with the ledger flag: real rows, no placeholder.
  await nav.getByRole("link", { name: "Transactions" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Transactions" })).toBeVisible();
  await expect(page.getByText(/^Showing \d+ of \d+$/)).toBeVisible();
});

test("health endpoint is proxied to the backend and reports a deploy SHA", async ({ request }) => {
  const response = await request.get("/healthz");
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(typeof body.sha).toBe("string");
  if (process.env.EXPECTED_SHA) expect(body.sha).toBe(process.env.EXPECTED_SHA);
});

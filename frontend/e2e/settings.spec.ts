// Settings on the real stack: rename, set and clear the buffer, refuse a bad amount, and the data actions.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const CSV = "../evals/datasets/P1-base/exports/monzo.csv";

async function noSeriousA11yIssues(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
}

test("an own profile renames itself and sets, keeps and clears its buffer", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/start");
  await page.getByLabel("Choose statement files").setInputFiles(CSV);
  await expect(page.getByRole("list", { name: "Your files" })).toContainText("Imported", { timeout: 30_000 });
  await page.goto("/settings");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();

  const profile = page.getByRole("form", { name: "Profile name" });
  await profile.getByLabel("Name").fill("Household");
  await profile.getByRole("button", { name: "Save name" }).click();
  await expect(profile.getByRole("status")).toHaveText("Saved.");
  await expect(page.getByRole("button", { name: "Account menu for Household" })).toBeVisible(); // the shell too

  const buffer = page.getByRole("form", { name: "Buffer amount" });
  await buffer.getByLabel(/Amount/).fill("abc");
  await buffer.getByRole("button", { name: "Save buffer" }).click();
  await expect(buffer.getByRole("alert")).toContainText("Enter an amount of zero or more");
  await buffer.getByLabel(/Amount/).fill("500");
  await buffer.getByRole("button", { name: "Save buffer" }).click();
  await expect(buffer.getByRole("status")).toHaveText("Saved.");
  await expect(page.getByText("Currently £500.00.")).toBeVisible();
  await noSeriousA11yIssues(page);

  await page.reload(); // saved on the server, not only on screen
  await expect(page.getByRole("form", { name: "Profile name" }).getByLabel("Name")).toHaveValue("Household");
  await expect(page.getByRole("form", { name: "Buffer amount" }).getByLabel(/Amount/)).toHaveValue("500.00");

  const again = page.getByRole("form", { name: "Buffer amount" });
  await again.getByLabel(/Amount/).fill("");
  await again.getByRole("button", { name: "Clear buffer" }).click();
  await expect(page.getByText("No buffer set.")).toBeVisible();
});

test("the data actions ask before deleting, and a guest is told signing out deletes", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/");
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  await page.waitForURL("**/home");
  await page.goto("/settings");
  await expect(page.getByText("Fictional demo data.")).toBeVisible();

  await page.getByRole("button", { name: "Delete my data" }).click();
  const confirm = page.getByRole("group", { name: "Confirm deleting your data" });
  await expect(confirm).toContainText("This can’t be undone.");
  await confirm.getByRole("button", { name: "Keep it" }).click();
  await expect(confirm).toHaveCount(0);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("group", { name: "Confirm signing out as a guest" })).toContainText(
    "deletes your guest profiles",
  );
  await page.getByRole("button", { name: "Keep them" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible(); // still here
});

test("a failed save says so and keeps what was typed", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/");
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  await page.waitForURL("**/home");
  await page.route("**/api/session", (route) =>
    route.request().method() === "PATCH" ? route.fulfill({ status: 500, body: "{}" }) : route.continue(),
  );
  await page.goto("/settings");
  const buffer = page.getByRole("form", { name: "Buffer amount" });
  await buffer.getByLabel(/Amount/).fill("250");
  await buffer.getByRole("button", { name: "Save buffer" }).click();
  await expect(buffer.getByRole("alert")).toContainText("couldn’t be saved");
  await expect(buffer.getByLabel(/Amount/)).toHaveValue("250");
});

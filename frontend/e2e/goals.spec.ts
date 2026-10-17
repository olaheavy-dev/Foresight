// Goals in the Decision Lab on the real stack: add, project, edit, mark achieved, archive, refusals.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const CSV = "../evals/datasets/P1-base/exports/monzo.csv";

async function noSeriousA11yIssues(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
}

async function openDemoLab(page: Page) {
  await page.context().clearCookies();
  await page.goto("/");
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  await page.waitForURL("**/home");
  await page.goto("/lab");
}

test("a goal is projected on the forecast, then edited, achieved and archived", async ({ page }) => {
  await openDemoLab(page);
  const add = page.getByRole("form", { name: "Add goal" });
  await add.getByRole("button", { name: "Add goal" }).click();
  await expect(add.getByRole("alert")).toContainText("Give the goal a name");

  await add.getByLabel("Goal").fill("Trip home");
  await add.getByLabel(/Amount/).fill("1500");
  await add.getByRole("button", { name: "Add goal" }).click();
  const goal = page.getByRole("region", { name: "Trip home" });
  await expect(goal).toContainText("Chance of reaching it", { timeout: 20_000 });
  await expect(goal).toContainText("Spare now");
  await expect(goal).toContainText("More than 90 days out");
  await expect(goal.getByRole("img").first()).toBeVisible();
  await noSeriousA11yIssues(page);

  await goal.getByRole("button", { name: "Edit" }).click();
  const edit = goal.getByRole("form", { name: "Save changes" });
  await edit.getByLabel(/Amount/).fill("900");
  await edit.getByRole("button", { name: "Save changes" }).click();
  await expect(goal).toContainText("£900.00", { timeout: 20_000 });

  await page.reload(); // stored, and read back
  await expect(page.getByRole("region", { name: "Trip home" })).toContainText("£900.00", { timeout: 20_000 });
  await page.getByRole("region", { name: "Trip home" }).getByRole("button", { name: "Mark achieved" }).click();
  await expect(page.getByText("Trip home: £900.00")).toBeVisible();
  // Its only goal achieved: not "No goals yet" beside the Achieved list (#54 review).
  await expect(page.getByText("No goals in progress.")).toBeVisible();
  await expect(page.getByText("No goals yet.")).toHaveCount(0);

  await add.getByLabel("Goal").fill("Laptop");
  await add.getByLabel(/Amount/).fill("800");
  await add.getByRole("button", { name: "Add goal" }).click();
  const laptop = page.getByRole("region", { name: "Laptop" });
  await expect(laptop).toContainText("Chance of reaching it", { timeout: 20_000 });
  await laptop.getByRole("button", { name: "Archive" }).click();
  await expect(laptop).toHaveCount(0);
});

test("a goal in the past is refused with the reason, and a goal without a known balance says so", async ({ page }) => {
  await openDemoLab(page);
  const add = page.getByRole("form", { name: "Add goal" });
  await add.getByLabel("Goal").fill("Yesterday");
  await add.getByLabel(/Amount/).fill("100");
  await add.getByLabel("By").fill("2020-01-01");
  await add.getByRole("button", { name: "Add goal" }).click();
  await expect(add.getByRole("alert")).toContainText("has to be in the future");

  await page.context().clearCookies();
  await page.goto("/start");
  await page.getByLabel("Choose statement files").setInputFiles(CSV);
  await expect(page.getByRole("list", { name: "Your files" })).toContainText("Imported", { timeout: 30_000 });
  await page.goto("/lab");
  const own = page.getByRole("form", { name: "Add goal" });
  await own.getByLabel("Goal").fill("Rainy day");
  await own.getByLabel(/Amount/).fill("500");
  await own.getByRole("button", { name: "Add goal" }).click();
  await expect(page.getByRole("region", { name: "Rainy day" })).toContainText("known balance", { timeout: 20_000 });
});

test("goals that can't load say so", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/");
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  await page.waitForURL("**/home");
  await page.route("**/api/goals", (route) =>
    route.request().method() === "GET" ? route.fulfill({ status: 500, body: "{}" }) : route.continue(),
  );
  await page.goto("/lab");
  await expect(page.getByRole("alert").filter({ hasText: "Your goals couldn’t load" })).toBeVisible();
});

test("two goals share what's spare: the later one counts what the earlier leaves (#54 review)", async ({ page }) => {
  await openDemoLab(page);
  const add = page.getByRole("form", { name: "Add goal" });
  for (const [name, amount] of [
    ["Trip home", "1500"],
    ["Laptop", "800"],
  ]) {
    await add.getByLabel("Goal").fill(name);
    await add.getByLabel(/Amount/).fill(amount);
    await add.getByRole("button", { name: "Add goal" }).click();
    await expect(page.getByRole("region", { name })).toContainText("Chance of reaching it", { timeout: 20_000 });
  }
  // Same date: the one made first is funded first, and the other says so.
  const laptop = page.getByRole("region", { name: "Laptop" });
  await expect(laptop).toContainText("After £1,500.00 set aside for goals due earlier", { timeout: 20_000 });
  await expect(page.getByRole("region", { name: "Trip home" })).not.toContainText("set aside for goals");
  await noSeriousA11yIssues(page);

  // Archiving the earlier goal frees its cash: the other goal is read again.
  await page.getByRole("region", { name: "Trip home" }).getByRole("button", { name: "Archive" }).click();
  await expect(laptop).not.toContainText("set aside for goals", { timeout: 20_000 });
});

test("when other goals can't be read again after a change, the Lab says so (#54 review)", async ({ page }) => {
  await openDemoLab(page);
  const add = page.getByRole("form", { name: "Add goal" });
  await add.getByLabel("Goal").fill("Trip home");
  await add.getByLabel(/Amount/).fill("1500");
  await add.getByRole("button", { name: "Add goal" }).click();
  const goal = page.getByRole("region", { name: "Trip home" });
  await expect(goal).toContainText("Chance of reaching it", { timeout: 20_000 });

  await page.route("**/api/goals", (route) =>
    route.request().method() === "GET" ? route.fulfill({ status: 500, body: "{}" }) : route.continue(),
  );
  await goal.getByRole("button", { name: "Mark achieved" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "couldn’t be updated just now" })).toBeVisible({
    timeout: 20_000,
  });
});

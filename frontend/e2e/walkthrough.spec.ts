// The portfolio walkthrough: a scripted tour of the live app, recorded as video
// (playwright.walkthrough.config.ts). It asks one question and runs one proactive check on a fresh
// demo copy (about $0.10 of OpenAI credit), so it runs only with WALKTHROUGH=1.
import { expect, type Page, test } from "@playwright/test";

test.skip(!process.env.WALKTHROUGH, "set WALKTHROUGH=1 to record the walkthrough (spends a little OpenAI credit)");

const beat = (page: Page, ms = 1_800) => page.waitForTimeout(ms);

// Seconds since the video started, printed for editing: waits are sped up in post, never faked.
const started = Date.now();
const mark = (what: string) => console.log(`MARK ${((Date.now() - started) / 1000).toFixed(1)} ${what}`);

async function glide(page: Page, y: number) {
  await page.mouse.wheel(0, y);
  await beat(page, 1_200);
}

test("Foresight in three minutes", async ({ page }) => {
  // Landing, then the demo: a private copy of a fictional profile.
  await page.context().clearCookies();
  await page.goto("/");
  await beat(page, 2_500);
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  await page.waitForURL("**/home");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("region", { name: "Proactive insights" })).toBeVisible();
  await beat(page, 2_500);

  // Home: the forecast with its pay-cycle lows, then the findings.
  await glide(page, 500);
  await glide(page, 500);

  // A proactive check: findings in, checked advice out, and how it was checked.
  const check = page.getByRole("button", { name: "Run the proactive check" });
  if (await check.isVisible()) {
    await check.scrollIntoViewIfNeeded();
    await beat(page, 1_000);
    await check.click();
    mark("wait-start proactive");
    await expect(page.getByText("Checked advice")).toBeVisible({ timeout: 180_000 });
    mark("wait-end proactive");
    await beat(page, 2_000);
    const how = page.locator("details.insight-trace > summary");
    if (await how.isVisible()) {
      await how.scrollIntoViewIfNeeded();
      await how.click();
      await beat(page, 3_000);
      await glide(page, 400);
    }
  }

  // The AI Workspace: one question, its checks as they happen, then the answer.
  await page.goto("/workspace");
  await beat(page, 1_500);
  await page.getByLabel("Ask a question").fill("Can I afford a £1,200 holiday in December?");
  await beat(page, 1_000);
  await page.getByRole("button", { name: "Send" }).click();
  await beat(page, 4_000); // the checks starting, at normal speed
  mark("wait-start answer");
  await expect(page.getByRole("region", { name: "Analysis" }).getByRole("heading", { level: 1 })).toBeVisible({
    timeout: 120_000,
  });
  mark("wait-end answer");
  await beat(page, 3_000);
  await glide(page, 500);
  await glide(page, -500);

  // How it was checked: the Verifier's rules and the evidence behind every figure.
  const checked = page.getByRole("tab", { name: "How it was checked" });
  if (await checked.isVisible()) {
    await checked.click();
    await beat(page, 3_000);
    await glide(page, 500);
  }

  // The Decision Lab: spread a purchase, on the same simulated paths.
  await page.goto("/lab");
  await beat(page, 1_500);
  await page.getByRole("radio", { name: /Spread a purchase/ }).check();
  await page.getByLabel("Total amount").fill("900");
  await beat(page, 800);
  await page.getByRole("button", { name: "Test it" }).click();
  await expect(page.getByRole("region", { name: "Result" })).toBeVisible({ timeout: 30_000 });
  await beat(page, 3_000);

  // Goals: save by a date, from what's spare above the buffer.
  const add = page.getByRole("form", { name: "Add goal" });
  await add.scrollIntoViewIfNeeded();
  await add.getByLabel("Goal").fill("Trip home");
  await add.getByLabel(/Amount/).fill("1500");
  await beat(page, 800);
  await add.getByRole("button", { name: "Add goal" }).click();
  await expect(page.getByRole("region", { name: "Trip home" })).toContainText("Chance of reaching it", {
    timeout: 30_000,
  });
  await page.getByRole("region", { name: "Trip home" }).scrollIntoViewIfNeeded();
  await beat(page, 3_000);

  // A finding's exact transactions, then Activity: every agent run as a trace.
  await page.goto("/home");
  await beat(page, 1_000);
  const rows = page.getByRole("link", { name: /See the transactions/ }).first();
  if (await rows.isVisible()) {
    await rows.scrollIntoViewIfNeeded();
    await rows.click();
    await page.waitForURL("**/transactions**");
    await beat(page, 3_000);
  }
  await page.goto("/activity");
  await beat(page, 2_000);
  await glide(page, 500);
  await beat(page, 1_500);
});

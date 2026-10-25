// The portfolio walkthrough: a scripted tour of the live app, recorded as video
// (playwright.walkthrough.config.ts). It asks one question and runs one proactive check on a fresh
// demo copy (about $0.10 of OpenAI credit), so it runs only with WALKTHROUGH=1. Each scene's pauses
// roughly match its narration (tools/demo/script.md), so the edit rarely slows a scene down.
import { readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";

test.skip(!process.env.WALKTHROUGH, "set WALKTHROUGH=1 to record the walkthrough (spends a little OpenAI credit)");

const beat = (page: Page, ms = 1_800) => page.waitForTimeout(ms);

// Seconds since the video started, printed for editing: waits are sped up in post, never faked.
const started = Date.now();
const mark = (what: string) => console.log(`MARK ${((Date.now() - started) / 1000).toFixed(1)} ${what}`);

async function glide(page: Page, y: number, ms = 1_200) {
  await page.mouse.wheel(0, y);
  await beat(page, ms);
}

// The stack card (tools/demo/stack.html), in the app's own fonts.
function stackCard(): string {
  const font = (file: string) => `data:font/woff2;base64,${readFileSync(`app/fonts/${file}`).toString("base64")}`;
  return readFileSync("../tools/demo/stack.html", "utf8")
    .replace("FONT_INTER", font("inter-latin-wght-normal.woff2"))
    .replace("FONT_SERIF", font("source-serif-4-latin-wght-normal.woff2"));
}

test("Foresight in three minutes", async ({ page }) => {
  // Straight into the app: the demo is a private copy of a fictional profile.
  mark("scene 01-open"); // scene names match tools/demo/script.md
  await page.context().clearCookies();
  await page.goto("/");
  await beat(page, 2_500);
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  await page.waitForURL("**/home");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("region", { name: "Proactive insights" })).toBeVisible();
  await beat(page, 5_000);

  // How it's built: a still card, then back to the same demo copy.
  mark("scene 02-stack");
  await page.setContent(stackCard());
  await page.evaluate(() => document.fonts.ready);
  await beat(page, 3_000); // the edit holds the card for the rest of the narration

  // Home: the forecast with its pay-cycle lows, then the findings.
  mark("scene 03-forecast");
  await page.goto("/home");
  await page.waitForLoadState("networkidle");
  await beat(page, 4_000);
  await glide(page, 450, 3_000);
  await glide(page, 450, 3_000);

  // The process: a proactive check, the agents working, checked advice out.
  mark("scene 04-proactive");
  const check = page.getByRole("button", { name: "Run the proactive check" });
  await check.scrollIntoViewIfNeeded();
  await beat(page, 1_500);
  await check.click();
  mark("wait-start proactive");
  await expect(page.getByText("Checked advice")).toBeVisible({ timeout: 180_000 });
  mark("wait-end proactive");

  // The result, and how it was checked.
  mark("scene 05-checked");
  await beat(page, 3_500);
  const how = page.locator("details.insight-trace > summary");
  if (await how.isVisible()) {
    await how.scrollIntoViewIfNeeded();
    await how.click();
    await beat(page, 3_500);
    await glide(page, 400, 3_500);
  }

  // The AI Workspace: one question, its steps as they happen.
  mark("scene 06-ask");
  await page.goto("/workspace");
  await beat(page, 1_500);
  await page.getByLabel("Ask a question").fill("Can I afford a £1,200 holiday in December?");
  await beat(page, 1_500);
  await page.getByRole("button", { name: "Send" }).click();
  mark("wait-start answer");
  await expect(page.getByRole("region", { name: "Analysis" }).getByRole("heading", { level: 1 })).toBeVisible({
    timeout: 120_000,
  });
  mark("wait-end answer");

  // The answer, then How it was checked.
  mark("scene 07-answer");
  await beat(page, 3_000);
  await glide(page, 500, 2_500);
  await glide(page, 500, 2_500);
  await glide(page, -1_000, 1_000);
  const checked = page.getByRole("tab", { name: "How it was checked" });
  if (await checked.isVisible()) {
    await checked.click();
    await beat(page, 3_000);
    await glide(page, 500, 2_000);
  }

  // The Decision Lab: spread a purchase, on the same simulated paths.
  mark("scene 08-lab");
  await page.goto("/lab");
  await beat(page, 1_500);
  await page.getByRole("radio", { name: /Spread a purchase/ }).check();
  await page.getByLabel("Total amount").fill("900");
  await beat(page, 1_000);
  await page.getByRole("button", { name: "Test it" }).click();
  await expect(page.getByRole("region", { name: "Result" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("region", { name: "Result" }).scrollIntoViewIfNeeded();
  await beat(page, 4_000);

  // Goals: save by a date, from what's spare above the buffer.
  mark("scene 09-goals");
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
  await beat(page, 3_500);

  // A finding's exact transactions.
  mark("scene 10-evidence");
  await page.goto("/home");
  await beat(page, 1_000);
  const rows = page.getByRole("link", { name: /See the transactions/ }).first();
  if (await rows.isVisible()) {
    await rows.scrollIntoViewIfNeeded();
    await beat(page, 1_000);
    await rows.click();
    await page.waitForURL("**/transactions**");
    await beat(page, 4_000);
  }

  // Activity: the latest agent run opened as a trace.
  mark("scene 11-activity");
  await page.goto("/activity");
  await beat(page, 1_500);
  const run = page.getByRole("region", { name: "Agent runs" }).locator("details > summary").first();
  if (await run.isVisible()) {
    await run.click();
    await beat(page, 3_000);
    await glide(page, 400, 3_000);
  }

  // Quality: the evaluation results, misses included.
  mark("scene 12-quality");
  await page.goto("/quality");
  await beat(page, 3_000);
  await glide(page, 500, 3_000);
  await glide(page, 500, 3_000);
  await beat(page, 2_000);
});

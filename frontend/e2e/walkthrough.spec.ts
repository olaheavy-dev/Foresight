// The portfolio walkthrough: a scripted tour of the live app, recorded as video
// (playwright.walkthrough.config.ts). It asks one question and runs one proactive check on a fresh
// demo copy (about $0.10 of OpenAI credit), so it runs only with WALKTHROUGH=1.
//
// The video is recorded to the narration: render it first (tools/demo/narrate.py writes each
// scene's length to out/audio/durations.json), and every scene is held until its line has been
// said, so the voice and the screen stay in step.
import { existsSync, readFileSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";

test.skip(!process.env.WALKTHROUGH, "set WALKTHROUGH=1 to record the walkthrough (spends a little OpenAI credit)");

const LENGTHS = "../tools/demo/out/audio/durations.json";
const PAD_MS = 1_000; // build.py's silence before and after each line (LEAD + TAIL)

const beat = (page: Page, ms = 1_800) => page.waitForTimeout(ms);

// Seconds since the video started, printed for editing: waits are sped up in post, never faked.
const started = Date.now();
const mark = (what: string) => console.log(`MARK ${((Date.now() - started) / 1000).toFixed(1)} ${what}`);

let lengths: Record<string, number> = {};
let current: { name: string; at: number } | null = null;

// Start a scene (named as in tools/demo/script.md) once the previous scene's line has finished.
async function scene(page: Page, name: string) {
  await settle(page);
  mark(`scene ${name}`);
  current = { name, at: Date.now() };
}

async function settle(page: Page) {
  if (!current) return;
  const left = lengths[current.name] * 1_000 + PAD_MS - (Date.now() - current.at);
  if (left > 0) await page.waitForTimeout(left);
}

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

test("Foresight walkthrough", async ({ page }) => {
  expect(existsSync(LENGTHS), "render the narration first (tools/demo/narrate.py)").toBe(true);
  lengths = JSON.parse(readFileSync(LENGTHS, "utf8")) as Record<string, number>;

  await page.context().clearCookies();
  await page.goto("/");
  await scene(page, "01-open");

  // Straight into the app: the demo is a private copy of a fictional profile.
  await scene(page, "02-home");
  await page.getByRole("button", { name: "Explore the live demo" }).click();
  await page.waitForURL("**/home");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("region", { name: "Proactive insights" })).toBeVisible();

  await scene(page, "03-stack");
  await page.setContent(stackCard());
  await page.evaluate(() => document.fonts.ready);

  await scene(page, "04-forecast");
  await page.goto("/home");
  await page.waitForLoadState("networkidle");
  await beat(page, 1_500);
  await glide(page, 420);

  await scene(page, "05-findings");
  await page.getByRole("region", { name: "Proactive insights" }).scrollIntoViewIfNeeded();
  await glide(page, 250);

  // The agents: a proactive check, in real time, with checked advice out.
  await scene(page, "06-proactive");
  const check = page.getByRole("button", { name: "Run the proactive check" });
  await check.scrollIntoViewIfNeeded();
  await beat(page, 1_500);
  await check.click();
  mark("wait-start proactive");
  await expect(page.getByText("Checked advice")).toBeVisible({ timeout: 180_000 });
  mark("wait-end proactive");

  await scene(page, "07-checked");
  await page.getByText("Checked advice").scrollIntoViewIfNeeded();
  await glide(page, 250);

  await scene(page, "08-how");
  const how = page.locator("details.insight-trace > summary").first();
  await how.scrollIntoViewIfNeeded();
  await how.click();
  await beat(page, 2_500);
  await glide(page, 350);

  // The AI Workspace: one question, its steps as they happen, then the answer.
  await scene(page, "09-ask");
  await page.goto("/workspace");
  await beat(page, 1_500);
  await page
    .getByLabel("Ask a question")
    .pressSequentially("Can I afford a £1,200 holiday in December?", { delay: 45 });

  await scene(page, "10-thinking");
  await page.getByRole("button", { name: "Send" }).click();
  mark("wait-start answer");
  await expect(page.getByRole("region", { name: "Analysis" }).getByRole("heading", { level: 1 })).toBeVisible({
    timeout: 120_000,
  });
  mark("wait-end answer");

  await scene(page, "11-answer");
  await beat(page, 1_000);

  await scene(page, "12-chart");
  await glide(page, 450, 2_500);
  await glide(page, 450, 2_500);

  await scene(page, "13-trace");
  await page.mouse.wheel(0, -2_000);
  await page.getByRole("tab", { name: "How it was checked" }).click();
  await beat(page, 3_000);
  await glide(page, 400);

  // The Decision Lab: spread a purchase, on the same simulated paths.
  await scene(page, "14-lab");
  await page.goto("/lab");
  await beat(page, 1_500);
  await page.getByRole("radio", { name: /Spread a purchase/ }).check();
  await beat(page, 800);
  await page.getByLabel("Total amount").fill("900");

  await scene(page, "15-lab-result");
  await page.getByRole("button", { name: "Test it" }).click();
  await expect(page.getByRole("region", { name: "Result" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("region", { name: "Result" }).scrollIntoViewIfNeeded();

  // Goals: save by a date, from what's spare above the buffer.
  await scene(page, "16-goals");
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

  // A finding's exact transactions.
  await scene(page, "17-evidence");
  await page.goto("/home");
  const rows = page.getByRole("link", { name: /See the transactions/ }).first();
  await rows.scrollIntoViewIfNeeded();
  await beat(page, 800);
  await rows.click();
  await page.waitForURL("**/transactions**");

  // Activity: the latest agent run opened as a trace, then the hash-chained change log.
  await scene(page, "18-activity");
  await page.goto("/activity");
  await beat(page, 1_200);
  await page.getByRole("region", { name: "Agent runs" }).locator("details > summary").first().click();
  await beat(page, 1_500);
  await glide(page, 300);

  await scene(page, "19-audit");
  await page.getByRole("region", { name: "Changes" }).scrollIntoViewIfNeeded();

  // Quality: the evaluation results, misses included.
  await scene(page, "20-quality");
  await page.goto("/quality");

  await scene(page, "21-close");
  await glide(page, 450, 2_500);
  await glide(page, 450, 2_500);
  await settle(page);
});

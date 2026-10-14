// AI Workspace journeys (playwright.workspace.config.ts, scripted mock API).
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

async function noSeriousA11yIssues(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

/** The question box is pinned: fully inside the viewport, not covered by the tab bar. */
async function inputVisible(page: Page) {
  const box = page.getByLabel("Ask a question");
  await expect(box).toBeVisible();
  const rect = await box.boundingBox();
  const vp = page.viewportSize()!;
  expect(rect).not.toBeNull();
  expect(rect!.y).toBeGreaterThanOrEqual(0);
  expect(rect!.y + rect!.height).toBeLessThanOrEqual(vp.height);
  const covered = await box.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return !(top === el || el.contains(top));
  });
  expect(covered).toBe(false);
}

async function ask(page: Page, text: string) {
  await page.getByLabel("Ask a question").fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

const MOCK = "http://localhost:8787";
const setAiStatus = (page: Page, status: "ok" | "degraded" | "unavailable") =>
  page.request.post(`${MOCK}/__mock/ai-status`, { data: { status } });

test.beforeEach(async ({ page }) => {
  await setAiStatus(page, "ok");
  await page.goto("/workspace");
});

test("welcome state: one serif line, four starters, the pinned question box", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Ask anything about your money." })).toBeVisible();
  await expect(page.getByRole("list", { name: "Start with a question" }).getByRole("button")).toHaveCount(4);
  await inputVisible(page);
  await noHorizontalScroll(page);
  await noSeriousA11yIssues(page);
});

test("an affordability answer streams its checks, then shows the answer skeleton", async ({ page }) => {
  await ask(page, "Can I afford a trip in December?");
  await expect(page.getByRole("heading", { name: "Checking before you see it" })).toBeVisible();
  await expect(page.locator(".loading-view").getByText("Verifier rejected a draft")).toBeVisible();
  await inputVisible(page);

  const verdict = page.getByRole("heading", { level: 1, name: /pay for it after your 27 November payday/ });
  await expect(verdict).toBeVisible({ timeout: 15_000 });
  const tabs = page.getByRole("tablist", { name: "Analysis sections" }).getByRole("tab");
  await expect(tabs).toHaveText(["Overview", "Details", "Recommendation", "Transactions", "How it was checked"]);

  // The evidence line opens the checklist in place; cost appears only under How it was checked.
  await page.getByRole("button", { name: /Checked by 6 agents · 1 draft rejected/ }).click();
  await expect(page.getByRole("list", { name: "Steps behind this answer" })).toBeVisible();
  await expect(page.getByText(/model calls/)).toBeHidden();
  await page.getByRole("tab", { name: "How it was checked" }).click();
  await expect(page.getByText(/7 model calls · 18,240 tokens · about \$0\.05/)).toBeVisible();
  await expect(page).toHaveURL(/#checked$/);

  await inputVisible(page);
  await noHorizontalScroll(page);
  await noSeriousA11yIssues(page);
});

test("a citation opens the Evidence drawer with the stored calculation", async ({ page }) => {
  await ask(page, "Can I afford a trip in December?");
  await expect(page.getByRole("heading", { level: 1, name: /27 November payday/ })).toBeVisible({ timeout: 15_000 });
  await page
    .getByRole("button", { name: /^Source 1:/ })
    .first()
    .click();
  const drawer = page.getByRole("dialog", { name: "Calculation" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("Stored calculation")).toBeVisible();
  await expect(drawer.getByText("fc-test")).toBeVisible();
  await expect(page).toHaveURL(/evidence=calc_/);
  await noSeriousA11yIssues(page);
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(page).not.toHaveURL(/evidence=/);
});

test("a spending answer uses the same frame and hides the empty Recommendation tab", async ({ page }) => {
  await ask(page, "Why is my spending up?");
  await expect(page.getByRole("heading", { level: 1, name: "Eating out is up on a usual month." })).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByRole("tablist", { name: "Analysis sections" }).getByRole("tab")).toHaveText([
    "Overview",
    "Details",
    "Transactions",
    "How it was checked",
  ]);
  await page.getByRole("tab", { name: "How it was checked" }).click();
  await expect(page.getByText(/0 model calls · reused your earlier answer/)).toBeVisible();
  await noSeriousA11yIssues(page);
});

test("a vague question gets a clarifying question whose options ask again", async ({ page }) => {
  await ask(page, "Can I afford a trip?");
  await expect(page.getByRole("heading", { name: "Which trip did you mean?" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "A one-off trip" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /27 November payday/ })).toBeVisible({ timeout: 15_000 });
  // Both questions are in the same thread.
  await expect(page.locator(".msg-user")).toHaveCount(2);
});

test("an engine failure is said plainly, with no figures and a retry", async ({ page }) => {
  await ask(page, "How does next month look?");
  const alert = page.getByRole("region", { name: "Analysis" }).getByRole("alert");
  await expect(alert).toContainText("The forecast engine didn’t respond.", { timeout: 15_000 });
  await expect(alert).toContainText("No figures were shown");
  await expect(page.getByRole("button", { name: "Try again" })).toBeEnabled();
  await noSeriousA11yIssues(page);
});

test("out-of-scope requests get a polite scope statement", async ({ page }) => {
  await ask(page, "Which shares should I invest in?");
  await expect(page.getByRole("heading", { level: 1, name: "I can’t recommend investments." })).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByRole("tablist")).toHaveCount(0);
});

test("the top-bar ask box opens the Workspace with the question already asked", async ({ page, isMobile }) => {
  test.skip(isMobile, "the top-bar ask box is a desktop control (hidden below 1024px, as in the hi-fi)");
  await page.goto("/home");
  await page.getByRole("searchbox", { name: "Ask Foresight about your finances" }).fill("Why is my spending up?");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1, name: "Eating out is up on a usual month." })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page).not.toHaveURL(/[?&]q=/);
});

test("reloading reopens the thread from its stored snapshot", async ({ page }) => {
  await ask(page, "Can I afford a trip in December?");
  await expect(page.getByRole("heading", { level: 1, name: /27 November payday/ })).toBeVisible({ timeout: 15_000 });
  const streams: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/events")) streams.push(r.url());
  });
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: /27 November payday/ })).toBeVisible();
  expect(streams).toEqual([]);
});

test("when AI answers are paused, the Workspace says so calmly and points to what still works", async ({ page }) => {
  await setAiStatus(page, "unavailable");
  await page.reload();
  const notice = page.locator(".dock .ai-notice");
  await expect(notice).toContainText("AI answers are paused right now. Your forecast and numbers still work.");
  await expect(page.getByRole("list", { name: "What still works" }).getByRole("link")).toHaveCount(3);
  await expect(page.getByLabel("Ask a question")).toBeEnabled();
  await inputVisible(page);
  await expect(page.locator("body")).not.toContainText(/credit|billing|mesh/i);
  await noSeriousA11yIssues(page);
  await ask(page, "Can I afford a trip in December?");
  const alert = page.getByRole("region", { name: "Analysis" }).getByRole("alert");
  await expect(alert).toContainText("AI answers are paused right now.");
  await expect(alert).toContainText("Your forecast and numbers still work.");
});

test("a degraded AI status is a quiet note only", async ({ page }) => {
  await setAiStatus(page, "degraded");
  await page.reload();
  await expect(page.getByText("AI answers may be slower than usual. Numbers are unaffected.")).toBeVisible();
  await expect(page.getByRole("list", { name: "Start with a question" })).toBeVisible();
});

test("conversations from an earlier session are listed from the server and reopen from their snapshots", async ({
  page,
  context,
}) => {
  await ask(page, "Can I afford a trip in December?");
  await expect(page.getByRole("heading", { level: 1, name: /27 November payday/ })).toBeVisible({ timeout: 15_000 });
  // A new session: nothing in this browser's storage, only what the server stored.
  await page.evaluate(() => sessionStorage.clear());
  await page.goto("/workspace");
  const convo = page.getByRole("region", { name: "Conversation" });
  if (await convo.getByRole("button", { name: /Conversation/ }).isVisible())
    await convo.getByRole("button", { name: /Conversation/ }).click();
  await convo
    .getByRole("button", { name: /Can I afford a trip in December\?/ })
    .first()
    .click();
  await expect(page.getByRole("heading", { level: 1, name: /27 November payday/ })).toBeVisible({ timeout: 15_000 });
  void context;
});

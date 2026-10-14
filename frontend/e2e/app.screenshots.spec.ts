// Design-review screenshots of every page on a real local stack (docker compose, demo profile).
//   SCREENSHOTS=1 npx playwright test app.screenshots --project=desktop
// Files: .design/foresight/screenshots/review-<page>-<device>-<width>[-dark-mode].png
// Full-page captures; axe and horizontal-overflow results are written next to them as JSON.
import AxeBuilder from "@axe-core/playwright";
import { writeFileSync } from "node:fs";
import { type Page, test } from "@playwright/test";

test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture design-review screenshots");
test.describe.configure({ mode: "serial" });
test.setTimeout(180_000);

const OUT = "../.design/foresight/screenshots";
const SIZES = [
  { device: "mobile", width: 375, height: 812 },
  { device: "tablet", width: 768, height: 1024 },
  { device: "desktop", width: 1280, height: 800 },
] as const;
const THEMES = ["light", "dark"] as const;
const PAGES = ["home", "workspace", "lab", "transactions", "activity", "quality", "settings"] as const;
const PUBLIC = [
  { name: "landing", path: "/" },
  { name: "start", path: "/start" },
] as const;

const file = (name: string, s: (typeof SIZES)[number], theme: string, ext = "png") =>
  `${OUT}/review-${name}-${s.device}-${s.width}${theme === "dark" ? "-dark-mode" : ""}.${ext}`;

async function capture(page: Page, name: string, s: (typeof SIZES)[number], theme: string) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(400);
  await page.mouse.move(0, 0);
  await page.screenshot({ path: file(name, s, theme), fullPage: true, animations: "disabled" });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  const axe = await new AxeBuilder({ page }).analyze();
  const issues = axe.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help }));
  writeFileSync(file(name, s, theme, "json"), JSON.stringify({ overflow, issues }, null, 1));
}

for (const theme of THEMES) {
  for (const s of SIZES) {
    test(`pages · ${s.width} ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width: s.width, height: s.height });
      await page.emulateMedia({ colorScheme: theme === "dark" ? "dark" : "light", reducedMotion: "reduce" });
      await page.context().clearCookies();
      for (const p of PUBLIC) {
        await page.goto(`${p.path}?theme=${theme}`);
        await capture(page, p.name, s, theme);
      }
      await page.goto(`/?theme=${theme}`);
      await page.getByRole("button", { name: "Explore the live demo" }).click();
      await page.waitForURL("**/home**");
      for (const p of PAGES) {
        await page.goto(`/${p}?theme=${theme}`);
        await page.waitForLoadState("networkidle");
        await capture(page, p, s, theme);
      }
    });
  }
}

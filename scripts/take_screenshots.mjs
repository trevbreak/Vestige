/**
 * Takes screenshots of Vestige pages for the README.
 * Usage: node take_screenshots.mjs   (from the scripts/ directory)
 */

import { chromium } from "playwright";
import path from "path";
import { fileURLToPath } from "url";
import fs from "fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.join(__dirname, "..", "docs", "screenshots");
const BASE = "http://localhost:5173";
const API = "http://localhost:8000/api";

fs.mkdirSync(OUT_DIR, { recursive: true });

// Routes: / = Avatars, /sessions = Sessions, /table = Table,
//         /sessions/:id/memory = Memory Review, /settings = Settings

const sessRes = await fetch(`${API}/sessions`);
const sessions = await sessRes.json();
const activeSession = sessions.find((s) => s.is_active);
console.log(`Active session: ${activeSession?.name} (id=${activeSession?.id})`);

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1.5,
});
const page = await ctx.newPage();

async function shot(filename, delayMs = 2500) {
  await page.waitForTimeout(delayMs);
  await page.screenshot({ path: path.join(OUT_DIR, filename), fullPage: false });
  console.log(`  ✓ ${filename}`);
}

async function shotFull(filename, delayMs = 2500) {
  await page.waitForTimeout(delayMs);
  await page.screenshot({ path: path.join(OUT_DIR, filename), fullPage: true });
  console.log(`  ✓ ${filename} (full page)`);
}

// ── 1. Avatars list (route: /) ─────────────────────────────────────────────
console.log("\nAvatars list...");
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await shot("01-avatars-list.png", 3000);

// ── 2. Avatar detail modal ─────────────────────────────────────────────────
console.log("Avatar detail...");
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
let opened = false;
// Try clicking an "Edit" button on any avatar card
const allBtns = await page.locator("button").all();
for (const btn of allBtns) {
  const txt = (await btn.textContent() || "").trim().toLowerCase();
  if (txt === "edit" || txt.includes("edit")) {
    await btn.click();
    await page.waitForTimeout(1200);
    opened = true;
    break;
  }
}
if (!opened) {
  // Try clicking first avatar card
  const cards = await page.locator("article, [class*='card'], [class*='Card'], li[class]").all();
  if (cards.length > 0) {
    await cards[0].click();
    await page.waitForTimeout(1000);
    opened = true;
  }
}
await shot("02-avatar-detail.png", 800);

// ── 3. Sessions list ───────────────────────────────────────────────────────
console.log("Sessions list...");
await page.goto(`${BASE}/sessions`, { waitUntil: "networkidle" });
await shot("03-sessions-list.png", 2500);

// ── 4. Table with session selected ────────────────────────────────────────
if (activeSession) {
  console.log("Table view...");
  await page.goto(`${BASE}/table`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.selectOption("select", String(activeSession.id));
  await shot("04-table-view.png", 2500);
}

// ── 5. Settings (full page) ───────────────────────────────────────────────
console.log("Settings...");
await page.goto(`${BASE}/settings`, { waitUntil: "networkidle" });
await shotFull("05-settings.png", 3000);

// ── 6. Memory review ─────────────────────────────────────────────────────
if (activeSession) {
  console.log("Memory review...");
  await page.goto(`${BASE}/sessions/${activeSession.id}/memory`, { waitUntil: "networkidle" });
  await shot("06-memory-review.png", 3000);
}

await browser.close();
console.log(`\nDone. Saved to: ${OUT_DIR}`);

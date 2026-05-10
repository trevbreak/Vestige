import { chromium } from "playwright";
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();

const errors = [];
page.on("console", msg => { if (msg.type() === "error") errors.push(msg.text()); });
page.on("pageerror", e => errors.push(e.message));

await page.goto("http://localhost:5173/avatars", { waitUntil: "networkidle" });
await page.waitForTimeout(4000);

const html = await page.content();
// Print a chunk of the body
const bodyMatch = html.match(/<body[^>]*>([\s\S]{0,3000})/);
console.log("=== BODY SNIPPET ===");
console.log(bodyMatch?.[1] || "(no body found)");
console.log("\n=== CONSOLE ERRORS ===");
errors.forEach(e => console.log(e));

// Check visible text
const text = await page.innerText("body");
console.log("\n=== VISIBLE TEXT (first 500 chars) ===");
console.log(text.slice(0, 500));

await browser.close();

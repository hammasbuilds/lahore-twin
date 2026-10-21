// Watch "Watch the demo" from start to finish through the real server, as a person would:
// record every caption it shows, fail on any page error, a "Demo stopped" or a module that never opens.
// usage: NODE_PATH=<dir with playwright> node tools/ui_check_demo.js <outdir> [base-url]
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

const out = process.argv[2] || "ui-shots";
const BASE = process.argv[3] || "http://127.0.0.1:8861/";
fs.mkdirSync(out, { recursive: true });
const fail = (m) => { console.error("DEMO CHECK FAILED:", m); process.exit(1); };

(async () => {
  const exe = process.env.CHROMIUM || path.join(process.env.LOCALAPPDATA || "", "ms-playwright", "chromium-1243", "chrome-win64", "chrome.exe");
  const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
  page.on("frameattached", (f) => f.page().on("pageerror", () => {}));
  await page.goto(BASE + "#demo");
  const seen = [];
  const t0 = Date.now();
  let shots = 0;
  while (Date.now() - t0 < 25 * 60 * 1000) {
    const title = await page.textContent("#demo-title").catch(() => "");
    const text = await page.textContent("#demo-text").catch(() => "");
    const cap = `${title} | ${text.replace(/… \d+ s$/, "…")}`;
    if (title && (!seen.length || seen[seen.length - 1] !== cap)) {
      seen.push(cap);
      console.log(`${((Date.now() - t0) / 1000).toFixed(0).padStart(4)} s  ${cap}`);
      if (!/Simulating/.test(text)) { await page.screenshot({ path: path.join(out, `demo-${String(++shots).padStart(2, "0")}.png`) }); }
    }
    if (/Demo stopped/.test(title)) fail(text);
    if (/That was Lahore Twin/.test(title)) break;
    await page.waitForTimeout(700);
  }
  if (!seen.some((c) => /That was Lahore Twin/.test(c))) fail("the demo never finished");
  for (const k of ["Office tower", "Hospital", "Lahore traffic", "Junction planner", "Home"]) {
    if (!seen.some((c) => c.includes(k))) fail(`the demo never showed ${k}`);
  }
  await browser.close();
  console.log(`${seen.length} captions; ERRORS:`, errors.length ? "\n" + errors.join("\n") : "none");
  if (errors.length) process.exit(1);
})();

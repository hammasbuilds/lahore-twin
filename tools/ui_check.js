// Drive the viewer in headless Chromium like a user and save screenshots.
// usage: NODE_PATH=<dir with playwright> node tools/ui_check.js <outdir> [page.html]
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

const out = process.argv[2] || "ui-shots";
const page_ = process.argv[3] || path.join(__dirname, "..", "viewer", "index.html");
fs.mkdirSync(out, { recursive: true });

(async () => {
  // the full Chromium build; the headless-shell build is often not downloaded
  const exe = process.env.CHROMIUM || path.join(process.env.LOCALAPPDATA || "", "ms-playwright", "chromium-1243", "chrome-win64", "chrome.exe");
  const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(m.type() + ": " + m.text()); });
  await page.goto("file://" + path.resolve(page_));
  await page.waitForTimeout(500);
  const shot = async (name) => { await page.screenshot({ path: path.join(out, name + ".png") }); console.log("shot", name); };
  const setT = async (hhmm) => {
    const [h, m] = hhmm.split(":").map(Number);
    await page.evaluate((t) => { window.__twin.state.t = t; window.__twin.frame(true); }, h * 3600 + m * 60);
    await page.waitForTimeout(150);
  };

  await setT("09:30"); await shot("01-0930-devices");
  await page.click("#layers button[data-layer=temp]"); await setT("10:15"); await shot("02-1015-temp");
  await page.click("#layers button[data-layer=co2]"); await setT("11:00"); await shot("03-1100-co2");
  await page.click("#layers button[data-layer=occ]"); await setT("13:20"); await shot("04-1320-occ-lunch");
  await page.click("#layers button[data-layer=state]");
  await setT("14:50");
  await page.evaluate(() => { window.__twin.state.sel = { type: "room", id: "meet_l" }; window.__twin.showTab("inspect"); window.__twin.frame(true); });
  await page.waitForTimeout(200); await shot("05-1450-inspect-meetl");
  await page.click(".tabs button[data-tab=attendance]"); await setT("09:20"); await shot("06-0920-attendance");
  await page.click(".tabs button[data-tab=energy]"); await setT("16:00"); await shot("07-1600-compare");
  await page.click(".tabs button[data-tab=events]"); await page.check("#only-alerts"); await setT("18:00"); await shot("08-1800-alerts");
  // click first log entry -> why chain
  await page.uncheck("#only-alerts");
  await page.click("#log li[data-msg] >> nth=0"); await page.waitForTimeout(200); await shot("09-why");
  await page.click("#modes button[data-mode=schedule]"); await setT("12:00"); await page.click(".tabs button[data-tab=events]"); await shot("10-schedule-1200");
  await page.click("#theme"); await page.waitForTimeout(200); await shot("11-light-theme");
  await page.click("#play"); await page.waitForTimeout(1500); await page.click("#play"); await shot("12-after-play");
  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(300); await shot("13-phone");
  console.log("ERRORS:", errors.length ? "\n" + errors.join("\n") : "none");
  await browser.close();
})();

// Drive the Home Twin viewer in headless Chromium like a user; save screenshots.
// usage: NODE_PATH=<dir with playwright> node tools/ui_check_home.js <outdir>
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

const out = process.argv[2] || "ui-shots";
fs.mkdirSync(out, { recursive: true });
process.on("unhandledRejection", (e) => { console.error("UI CHECK FAILED:", e && e.message ? e.message : e); process.exit(1); });

(async () => {
  const exe = process.env.CHROMIUM || path.join(process.env.LOCALAPPDATA || "", "ms-playwright", "chromium-1243", "chrome-win64", "chrome.exe");
  const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(m.type() + ": " + m.text()); });
  for (let attempt = 1; ; attempt++) {
    await page.goto("file://" + path.resolve(__dirname, "..", "viewer", "home.html"));
    if (await page.waitForFunction(() => window.__home, null, { timeout: 5000 }).then(() => true, () => false)) break;
    if (attempt === 3) throw new Error("home viewer never initialised: " + errors.join(" | "));
    errors.length = 0; await page.waitForTimeout(1000);
  }
  const shot = async (n) => { await page.screenshot({ path: path.join(out, "home-" + n + ".png") }); console.log("shot", n); };
  const setT = async (hhmm) => { const [h, m] = hhmm.split(":").map(Number); await page.evaluate((t) => { window.__home.state.t = t; window.__home.frame(true); }, h * 3600 + m * 60); await page.waitForTimeout(150); };

  await setT("02:00"); await shot("01-0200-night");
  await setT("10:30"); await shot("02-1030-outage");
  await page.click('#modes button[data-mode="default"]'); await setT("23:30"); await shot("03-2330-default-night-outage");
  await page.click('#modes button[data-mode="ups"]'); await setT("23:30"); await shot("04-2330-ups-night-outage");
  await page.click('#modes button[data-mode="gridsense"]'); await setT("21:40"); await shot("05-2140-gridsense-precool");
  await page.click("#layers button[data-layer=temp]"); await setT("15:00"); await shot("06-1500-temp");
  await page.click("#layers button[data-layer=state]");
  await page.click(".tabs button[data-tab=day]"); await page.waitForTimeout(200); await shot("07-day");
  await page.click(".tabs button[data-tab=compare]"); await page.waitForTimeout(200); await shot("08-compare");
  await page.click(".tabs button[data-tab=events]");
  if (!(await page.isChecked("#only-key"))) throw new Error("the log should open on decisions and alerts");
  await setT("23:59"); await shot("09-decisions");
  await page.uncheck("#only-key"); await page.waitForTimeout(150); await shot("09b-full-log"); await page.check("#only-key");
  const first = page.locator("#log li[data-msg]").first(); await first.waitFor({ state: "visible" });
  await first.click(); await page.waitForTimeout(200); await shot("10-why");
  // a real click on a person
  await setT("20:45");
  const dot = await page.evaluate(() => { const r = document.getElementById("plan").getBoundingClientRect(); const h = window.__home.hits()[0]; return h ? { x: r.left + h.x, y: r.top + h.y, name: h.p.name } : null; });
  if (!dot) throw new Error("nobody on the plan at 20:45");
  await page.mouse.click(dot.x, dot.y); await page.waitForTimeout(200);
  const title = await page.textContent("#inspect-body h3");
  if (!title.includes(dot.name)) throw new Error(`clicked ${dot.name}, inspector shows ${title}`);
  await shot("11-person");
  await page.focus("#find"); await page.selectOption("#find", "app:pump"); await page.waitForTimeout(200); await shot("12-pump");
  const t0 = await page.evaluate(() => window.__home.state.t);
  await page.keyboard.press("ArrowRight"); await page.waitForTimeout(100);
  if ((await page.evaluate(() => window.__home.state.t)) !== t0) throw new Error("ArrowRight in the picker moved the clock");
  // season switch: October must be a different day, with its own outages and bills
  const juneOut = await page.evaluate(() => JSON.stringify(window.HOME_SCENARIOS.june.outages));
  await page.click('#seasons button[data-season="october"]'); await page.waitForTimeout(250);
  if ((await page.evaluate(() => window.__home.season())) !== "october") throw new Error("season switch did not take");
  await page.click(".tabs button[data-tab=compare]"); await page.waitForTimeout(200);
  const octBill = await page.textContent("#pane-compare");
  if (!/Bill/.test(octBill)) throw new Error("October compare table missing");
  await setT("15:00"); await shot("12b-october-compare");
  await page.click('#seasons button[data-season="june"]'); await page.waitForTimeout(200);
  void juneOut;
  await page.click("#theme"); await page.waitForTimeout(200); await shot("13-light");
  await page.click("#play"); await page.waitForTimeout(1200); await page.click("#play"); await shot("14-after-play");
  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(300); await shot("15-phone");
  console.log("ERRORS:", errors.length ? "\n" + errors.join("\n") : "none");
  await browser.close();
})();

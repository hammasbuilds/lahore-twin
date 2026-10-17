// Drive the viewer in headless Chromium like a user and save screenshots.
// usage: NODE_PATH=<dir with playwright> node tools/ui_check.js <outdir> [page.html]
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

const out = process.argv[2] || "ui-shots";
const page_ = process.argv[3] || path.join(__dirname, "..", "viewer", "index.html");
fs.mkdirSync(out, { recursive: true });

process.on("unhandledRejection", (e) => { console.error("UI CHECK FAILED:", e && e.message ? e.message : e); process.exit(1); });

(async () => {
  // the full Chromium build; the headless-shell build is often not downloaded
  const exe = process.env.CHROMIUM || path.join(process.env.LOCALAPPDATA || "", "ms-playwright", "chromium-1243", "chrome-win64", "chrome.exe");
  const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(m.type() + ": " + m.text()); });
  // a replay.js written a moment ago can still be locked (antivirus scan): retry the load
  for (let attempt = 1; ; attempt++) {
    await page.goto("file://" + path.resolve(page_));
    const ok = await page.waitForFunction(() => window.__twin, null, { timeout: 5000 }).then(() => true, () => false);
    if (ok) break;
    if (attempt === 3) throw new Error("viewer never initialised: " + errors.join(" | "));
    errors.length = 0;
    await page.waitForTimeout(1000);
  }
  await page.waitForTimeout(300);
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
  // the log re-renders on a timer; wait for an entry, then click it by locator (re-resolved on retry)
  const first = page.locator("#log li[data-msg]").first();
  await first.waitFor({ state: "visible" });
  await first.click({ timeout: 5000 }); await page.waitForTimeout(200); await shot("09-why");
  await page.click("#modes button[data-mode=schedule]"); await setT("12:00"); await page.click(".tabs button[data-tab=events]"); await shot("10-schedule-1200");
  await page.click("#theme"); await page.waitForTimeout(200); await shot("11-light-theme");
  await page.click("#play"); await page.waitForTimeout(1500); await page.click("#play"); await shot("12-after-play");
  await page.setViewportSize({ width: 1440, height: 900 }); await page.waitForTimeout(200);
  // a person, picked the way a user would: click their dot on the plan
  await setT("10:40");
  // a real mouse click on the office boy's dot, then check the inspector names him
  const dot = await page.evaluate(() => {
    const r = document.getElementById("plan").getBoundingClientRect();
    const h = window.__twin.hits().find((x) => x.p.role === "office_boy");
    return h ? { x: r.left + h.x, y: r.top + h.y, name: h.p.name } : null;
  });
  if (!dot) throw new Error("office boy not on the plan at 10:40");
  await page.mouse.click(dot.x, dot.y); await page.waitForTimeout(250);
  const title = await page.textContent("#pane-inspect h3");
  if (!title.includes(dot.name)) throw new Error(`clicked ${dot.name}, inspector shows ${title}`);
  await shot("14-person-officeboy-1040");
  await page.click('#modes button[data-mode="pir+co2"]');
  await setT("07:35"); await page.click(".tabs button[data-tab=events]"); await shot("15-0735-morning");
  await setT("19:45"); await shot("16-1945-evening");
  await page.click(".tabs button[data-tab=energy]"); await page.waitForTimeout(200); await shot("17-light-compare");
  // the Find picker: keyboard users cannot click the canvas
  await page.click(".tabs button[data-tab=inspect]");
  await setT("13:32");
  await page.focus("#find"); await page.selectOption("#find", "room:prayer"); await page.waitForTimeout(250);
  const ph = await page.textContent("#inspect-body h3");
  if (!/Prayer room/.test(ph)) throw new Error("picker chose the prayer room, inspector shows " + ph);
  await shot("18-find-prayer-1332");
  // keys belong to the focused control: arrows in the picker must not move the clock
  const t0 = await page.evaluate(() => window.__twin.state.t);
  await page.focus("#find"); await page.keyboard.press("ArrowRight"); await page.waitForTimeout(150);
  const t1 = await page.evaluate(() => window.__twin.state.t);
  if (t1 !== t0) throw new Error(`ArrowRight in the Find picker moved the clock ${t0} -> ${t1}`);
  // space on a focused mode button selects that mode and does not start playback
  await page.focus('#modes button[data-mode="pir"]'); await page.keyboard.press("Space"); await page.waitForTimeout(150);
  const st = await page.evaluate(() => ({ mode: window.__twin.state.mode, playing: window.__twin.state.playing }));
  if (st.mode !== "pir" || st.playing) throw new Error("Space on the Motion button: " + JSON.stringify(st));
  // the end-of-day alerts are reachable on the timeline
  await page.click(".tabs button[data-tab=events]"); await page.check("#only-alerts");
  await page.evaluate(() => { const tw = window.__twin; tw.state.t = 21 * 3600 - 1; tw.frame(true); });
  await page.waitForTimeout(200);
  const logText = await page.textContent("#log");
  if (!/never badged out/.test(logText)) throw new Error("no badge-out alerts visible at the end of the timeline");
  await shot("19-end-of-day-alerts");
  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(300); await shot("13-phone");
  console.log("ERRORS:", errors.length ? "\n" + errors.join("\n") : "none");
  await browser.close();
})();

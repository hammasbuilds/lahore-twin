// Drive the Hospital Twin viewer in headless Chromium like a user; save screenshots.
// usage: NODE_PATH=<dir with playwright> node tools/ui_check_hospital.js <outdir>
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
  await page.goto("file://" + path.resolve(__dirname, "..", "viewer", "hospital.html"));
  await page.waitForFunction(() => window.__hosp, null, { timeout: 15000 });
  const shot = async (n) => { await page.screenshot({ path: path.join(out, "hosp-" + n + ".png") }); console.log("shot", n); };
  const setT = async (hhmm) => { const [h, m] = hhmm.split(":").map(Number); await page.evaluate((t) => { window.__hosp.state.t = t; window.__hosp.frame(true); }, h * 3600 + m * 60); await page.waitForTimeout(120); };
  const fail = (msg) => { throw new Error(msg); };

  await setT("11:00"); await shot("01-ed-1100");
  const board = await page.locator("#pane-board tr[data-agent]").count();
  if (board < 3) fail(`the ED board at 11:00 lists ${board} patients`);
  await page.click('#views button[data-view="ward"]'); await setT("10:30"); await shot("02-ward-1030");
  await page.click('#views button[data-view="site"]'); await setT("12:00"); await shot("03-site");
  // someone should be crossing the campus at some point in the day
  const crossing = await page.evaluate(() => {
    const H = window.__hosp, M = H.modes[H.state.mode];
    for (let t = 6 * 3600; t < 86400; t += 120) for (const a of Object.values(M.agents)) { const at = H.agentAt(a, t); if (at && at.b === "campus") return t; }
    return null;
  });
  if (crossing == null) fail("nobody ever crosses the campus between the ED and the ward");
  await page.evaluate((t) => { window.__hosp.state.t = t; window.__hosp.frame(true); }, crossing + 60); await page.waitForTimeout(120); await shot("04-site-crossing");
  await page.click('#views button[data-view="ed"]');
  await page.click('#modes button[data-mode="today"]'); await setT("14:00"); await shot("05-ed-today-1400");
  for (const tab of ["beds", "kit", "events", "compare"]) {
    await page.click(`.tabs button[data-tab=${tab}]`); await page.waitForTimeout(150); await shot("06-tab-" + tab);
  }
  const cmp = await page.locator("#pane-compare tr").count();
  if (cmp < 20) fail(`compare table has ${cmp} rows`);
  // an event opens its why chain
  await page.click(".tabs button[data-tab=events]");
  const ev = page.locator("#log li[data-msg]").first(); await ev.waitFor({ state: "visible" }); await ev.click(); await page.waitForTimeout(150);
  if (!(await page.locator("#inspect-body .why").count())) fail("clicking an event did not show its why chain");
  await shot("07-why");
  // a real click on a person on the plan
  await page.click('#views button[data-view="ed"]'); await setT("11:30");
  const dot = await page.evaluate(() => { const r = document.getElementById("plan").getBoundingClientRect(); const h = window.__hosp.hits().find((x) => x.type === "agent"); return h ? { x: r.left + h.x, y: r.top + h.y, id: h.id } : null; });
  if (!dot) fail("nobody on the ED plan at 11:30");
  await page.mouse.click(dot.x, dot.y); await page.waitForTimeout(150);
  const title = await page.textContent("#inspect-body h3");
  const name = await page.evaluate((id) => window.__hosp.modes[window.__hosp.state.mode].agents[id].name, dot.id);
  if (!title.includes(name)) fail(`clicked ${name}, inspector shows ${title}`);
  await shot("08-person");
  // ward alarms pulse; switching rule set changes the counts
  await page.click('#views button[data-view="ward"]');
  const sounded = await page.evaluate(() => ({ today: window.__hosp.modes.today.metrics.alarms_sounded, connected: window.__hosp.modes.connected.metrics.alarms_sounded }));
  if (!(sounded.connected < sounded.today)) fail(`the alarm delay should sound fewer alarms: ${JSON.stringify(sounded)}`);
  const alarmT = await page.evaluate(() => { const a = window.__hosp.modes.today.alarms.find((x) => x.annunciated && x.arrived && x.arrived - x.annunciated > 20); return a ? a.annunciated + 5 : null; });
  if (alarmT) { await page.evaluate((t) => { window.__hosp.state.t = t; window.__hosp.frame(true); }, alarmT); await page.waitForTimeout(150); await shot("09-ward-alarm"); }
  // floors: the ED basement holds the spare pumps; the main block's ward is on floor 2
  await page.click('#views button[data-view="ed"]'); await page.click('#floors button[data-floor="B1"]'); await setT("06:00");
  const b1 = await page.evaluate(() => window.__hosp.hits().filter((h) => h.type === "asset").length);
  if (b1 < 1) fail("no equipment drawn in the ED basement at 06:00 (four spare pumps live there)");
  await shot("09b-ed-basement");
  await page.click('#views button[data-view="ward"]');
  if ((await page.evaluate(() => window.__hosp.state.floor.ward)) !== "2") fail("the main block should open on the ward floor");
  // follow a porter across the campus: the view must change on its own
  const trip = await page.evaluate(() => {
    const H = window.__hosp, M = H.modes[H.state.mode];
    for (let t = 8 * 3600; t < 86400; t += 60) for (const a of Object.values(M.agents)) { if (a.role !== "porter") continue; const at = H.agentAt(a, t); if (at && at.b === "campus") return { id: a.id, t: t - 300 }; }
    return null;
  });
  if (!trip) fail("no porter crosses the campus");
  await page.evaluate((x) => { const H = window.__hosp; H.state.t = x.t; H.state.sel = { type: "agent", id: x.id }; H.showTab("inspect"); }, trip);
  await page.click("#follow-btn");
  const seen = new Set();
  for (let k = 0; k < 12; k++) { await page.evaluate(() => { window.__hosp.state.t += 60; window.__hosp.frame(true); }); seen.add(await page.evaluate(() => window.__hosp.state.view)); }
  if (!seen.has("site") || !seen.has("ed")) fail(`following a porter should move the camera between the ED and the site: ${[...seen]}`);
  await page.click("#follow-btn");
  await page.click("#theme"); await page.waitForTimeout(150); await shot("10-light");
  await page.keyboard.press("1"); await page.waitForTimeout(150);
  if ((await page.evaluate(() => window.__hosp.state.view)) !== "site") fail("key 1 should open the site view");
  await page.click("#play"); await page.waitForTimeout(800); await page.click("#play"); await shot("11-after-play");
  await page.setViewportSize({ width: 390, height: 844 }); await page.keyboard.press("2"); await page.waitForTimeout(300); await shot("12-phone");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (overflow > 2) fail(`page scrolls sideways by ${overflow}px at phone width`);
  await browser.close();
  console.log("ERRORS:", errors.length ? errors.join("\n") : "none");
  if (errors.length) process.exit(1);
})();

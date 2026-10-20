// Use the whole Lahore Twin app like a person would, through the real server:
// open every module from the overview, read every About, press the buttons, type values
// into "Run with your values" and check the result reflects them. Needs serve.py running.
// usage: NODE_PATH=<dir with playwright> node tools/ui_check_app.js <outdir> [base-url]
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

const out = process.argv[2] || "ui-shots";
const BASE = process.argv[3] || "http://127.0.0.1:8861/";
fs.mkdirSync(out, { recursive: true });
process.on("unhandledRejection", (e) => { console.error("APP CHECK FAILED:", e && e.message ? e.message : e); process.exit(1); });
const fail = (m) => { throw new Error(m); };
const log = (...a) => console.log(...a);

(async () => {
  const exe = process.env.CHROMIUM || path.join(process.env.LOCALAPPDATA || "", "ms-playwright", "chromium-1243", "chrome-win64", "chrome.exe");
  const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  // the one expected error is the deliberately out-of-range request near the end
  page.on("console", (m) => { if (m.type() === "error" && !/status of 400/.test(m.text())) errors.push("console: " + m.text()); });
  const shot = async (n) => { await page.screenshot({ path: path.join(out, "app-" + n + ".png") }); log("shot", n); };
  const frame = () => page.frames().find((f) => f !== page.mainFrame());
  async function waitModule(global) {
    for (let i = 0; i < 100; i++) {
      const f = frame();
      if (f && await f.evaluate((g) => !!window[g], global).catch(() => false)) return f;
      await page.waitForTimeout(150);
    }
    fail(`module never initialised (${global})`);
  }

  // ---- overview ----
  await page.goto(BASE);
  await page.waitForFunction(() => window.__shell);
  const cards = await page.locator(".card").count();
  const ready = await page.locator(".card [data-open]").count();
  log("overview cards", cards, "ready", ready);
  if (cards !== 6) fail(`overview shows ${cards} modules, not 6`);
  if (ready < 4) fail(`only ${ready} modules can be opened`);
  const stats = await page.locator(".card .stats b").allTextContents();
  if (stats.length < 12 || stats.some((s) => !s.trim() || /undefined|NaN/.test(s))) fail("overview numbers missing: " + stats.join(" | "));
  await shot("01-overview");

  // ---- every About ----
  for (const key of ["office", "home", "hospital", "traffic", "junctions", "city"]) {
    await page.click(`.card[data-card="${key}"] [data-about]`);
    await page.waitForSelector("#dlg[open]");
    const text = await page.textContent("#dlg-body");
    if (text.length < 120) fail(`About ${key} is nearly empty`);
    if (["office", "home", "hospital", "traffic"].includes(key) && !/What you can put in/.test(text)) fail(`About ${key} does not say what input it takes`);
    if (key === "hospital") await shot("02-about-hospital");
    await page.click("#dlg [data-close]");
  }
  await page.click("#about-all"); await page.waitForSelector("#dlg[open]"); await page.click("#dlg [data-close]");
  log("about panels ok");

  // ---- open each module, press its buttons ----
  const modules = [
    ["office", "__twin", async (f) => {
      for (const fl of ["B1", "1", "G"]) { await f.click(`#floors button[data-floor="${fl}"]`); }
      await f.click('#modes button[data-mode="schedule"]'); await f.click('#modes button[data-mode="pir+co2"]');
      await f.click(".tabs button[data-tab=attendance]");
      await f.click(".tabs button[data-tab=energy]");
      if ((await f.locator("#pane-energy tr, #pane-energy .row").count()) < 3) fail("office compare is empty");
    }],
    ["home", "__home", async (f) => {
      for (const fl of ["R", "1", "G"]) await f.click(`#floors button[data-floor="${fl}"]`);
      await f.click('#seasons button[data-season="october"]'); await f.click('#seasons button[data-season="june"]');
      await f.click('#modes button[data-mode="default"]'); await f.click('#modes button[data-mode="gridsense"]');
      await f.click(".tabs button[data-tab=day]"); await f.click(".tabs button[data-tab=compare]");
    }],
    ["hospital", "__hosp", async (f) => {
      await f.click('#views button[data-view="site"]'); await f.click('#views button[data-view="ed"]');
      await f.click('#floors button[data-floor="B1"]'); await f.click('#floors button[data-floor="G"]');
      await f.click('#views button[data-view="ward"]');
      for (const tab of ["beds", "kit", "events", "compare", "board"]) await f.click(`.tabs button[data-tab=${tab}]`);
      await f.click('#modes button[data-mode="today"]');
    }],
    ["traffic", "__traffic", async (f) => {
      await f.click("#zin"); await f.click("#zout"); await f.click("#zfit");
      await f.click('#modes button[data-mode="fixed"]'); await f.click('#modes button[data-mode="adaptive"]');
      await f.click("#follow-random"); await page.waitForTimeout(300);
      const following = await f.evaluate(() => window.__traffic.state.follow);
      if (following == null) fail("Follow a vehicle did nothing");
      await f.click(".tabs button[data-tab=hot]");
      await f.click("#pane-hot li[data-sig]");
      if (!(await f.textContent("#pane-junction")).includes("Phase")) fail("clicking a hotspot did not open its junction");
      await f.click(".tabs button[data-tab=compare]");
    }],
  ];
  for (const [key, global, poke] of modules) {
    await page.click(`#nav button[data-go="${key}"]`);
    const f = await waitModule(global);
    if (!(await page.evaluate(() => location.hash)).startsWith("#" + key)) fail(`URL did not follow the module (${key})`);
    // inside the shell the module's own navigation is hidden
    const xl = await f.evaluate(() => [...document.querySelectorAll("header .xlink")].filter((e) => getComputedStyle(e).display !== "none").length);
    if (xl) fail(`${key}: cross-links still visible inside the shell`);
    await poke(f);
    // the module's About opens the shell's dialog
    await f.click("#about-btn"); await page.waitForSelector("#dlg[open]");
    if (!(await page.textContent("#dlg-body")).length) fail(`${key}: About inside the module is empty`);
    await page.click("#dlg [data-close]");
    await page.waitForTimeout(400);
    await shot("03-" + key);
    log("module ok", key);
  }

  // theme follows into the open module
  await page.click("#theme"); await page.waitForTimeout(400);      // the frame hears it by message
  const themes = await Promise.all([page.evaluate(() => document.documentElement.dataset.theme), frame().evaluate(() => document.documentElement.dataset.theme)]);
  if (themes[0] !== themes[1]) fail(`theme did not reach the module: ${themes}`);
  await shot("04-light"); await page.click("#theme");

  // ---- run with your own values ----
  async function runWith(key, values, global) {
    await page.click('#nav button[data-go="overview"]');
    await page.click(`.card[data-card="${key}"] [data-run]`);
    await page.waitForSelector("#runform");
    for (const [name, v] of Object.entries(values)) {
      const sel = `#runform [name="${name}"]`;
      if (await page.locator(`#runform select[name="${name}"]`).count()) await page.selectOption(sel, String(v));
      else { await page.fill(sel, ""); await page.type(sel, String(v)); }
    }
    const t0 = Date.now();
    await page.click("#run-go");
    await page.waitForFunction(() => !document.querySelector("#dlg[open]") || /Could not/.test(document.querySelector("#runmsg").textContent), null, { timeout: 600000 });
    const msg = await page.locator("#runmsg").count() ? await page.textContent("#runmsg").catch(() => "") : "";
    if (/Could not/.test(msg)) fail(`${key} run failed: ${msg}`);
    const f = await waitModule(global);
    const pill = await f.textContent("#your-run").catch(() => null);
    if (!pill) fail(`${key}: the run does not say it is yours`);
    log(`run ${key} in ${((Date.now() - t0) / 1000).toFixed(0)} s:`, pill);
    return f;
  }
  let f = await runWith("hospital", { arrivals_pct: 150, ward_nurses: 4, alarm_delay: 0 }, "__hosp");
  const h = await f.evaluate(() => ({ meta: window.HOSPITAL.meta, c: window.HOSPITAL.modes.connected.metrics }));
  if (h.meta.arrivals_pct !== 150 || h.meta.alarm_delay !== 0) fail("hospital run ignored the inputs: " + JSON.stringify(h.meta));
  if (h.c.brief_true_events_not_sounded !== 0) fail("with no alarm delay every brief real event should sound");
  if (h.c.ed_arrivals < 200) fail(`150% arrivals gave only ${h.c.ed_arrivals}`);
  await shot("05-run-hospital");
  f = await runWith("home", { season: "october", category: "V", pv_kwp: 3, battery_kwh: 5 }, "__home");
  const hm = await f.evaluate(() => window.HOME.meta);
  if (hm.pv_kwp !== 3 || hm.battery_kwh !== 5 || hm.category !== "V") fail("home run ignored the inputs: " + JSON.stringify(hm));
  await shot("06-run-home");
  f = await runWith("traffic", { period: "morning", per_hour: 4000 }, "__traffic");
  const tm = await f.evaluate(() => window.TRAFFIC.meta);
  if (tm.per_hour !== 4000 || tm.trips > 4500 || tm.period !== "morning") fail("traffic run ignored the inputs: " + JSON.stringify(tm));
  const tp = await f.textContent("#your-run");
  if (!/morning · 4,000 trips\/h/.test(tp) || /undefined/.test(tp)) fail("traffic run label is wrong: " + tp);
  if (await f.textContent("#clock") < "07:30") fail("a morning run should start at 07:30");
  const purposes = await f.evaluate(() => window.TRAFFIC.purposes);
  if (!purposes.includes("school run") || purposes.includes("shopping")) fail("a morning run has the wrong trips: " + purposes);
  await shot("07-run-traffic");
  f = await runWith("office", { staff: 20, visitors: 2 }, "__twin");
  const om = await f.evaluate(() => window.REPLAY.meta);
  if (om.staff !== 20) fail("office run ignored the staff count: " + JSON.stringify(om));
  await shot("08-run-office");

  // a value outside the allowed range is refused by the server with a reason
  const bad = await page.evaluate(async () => { const r = await fetch("/api/run/office", { method: "POST", body: JSON.stringify({ staff: 99 }) }); return [r.status, await r.json()]; });
  if (bad[0] !== 400 || !/staff/.test(bad[1].error)) fail("an out-of-range input was not refused: " + JSON.stringify(bad));
  log("bad input refused:", bad[1].error);

  // ---- phone ----
  await page.setViewportSize({ width: 390, height: 844 });
  await page.click('#nav button[data-go="overview"]'); await page.waitForTimeout(300);
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (over > 2) fail(`the app scrolls sideways by ${over}px on a phone`);
  await shot("09-phone");
  await browser.close();
  log("ERRORS:", errors.length ? errors.join("\n") : "none");
  if (errors.length) process.exit(1);
})();

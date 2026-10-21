// Use City Systems like a person would: every view, both rule sets, both smog layers, play,
// keyboard, hovering, theme, phone width. Screenshots per view.
// usage: NODE_PATH=<dir with playwright> node tools/ui_check_city.js <outdir>
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

const out = process.argv[2] || "ui-shots";
fs.mkdirSync(out, { recursive: true });
const fail = (m) => { console.error("UI CHECK FAILED:", m); process.exit(1); };

(async () => {
  const exe = process.env.CHROMIUM || path.join(process.env.LOCALAPPDATA || "", "ms-playwright", "chromium-1243", "chrome-win64", "chrome.exe");
  const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(m.type() + ": " + m.text()); });
  await page.goto("file://" + path.resolve(__dirname, "..", "viewer", "city.html"));
  await page.waitForFunction(() => window.__city, null, { timeout: 30000 });
  const shot = async (n) => { await page.screenshot({ path: path.join(out, "city-" + n + ".png") }); console.log("shot", n); };
  const k = async (id) => (await page.textContent(id)).trim();

  // smog: the two rule sets and the two layers differ; a sensor has a tooltip
  await page.click('#views button[data-view="smog"]');
  await page.click('#modes button[data-mode="today"]'); await page.waitForTimeout(150);
  const e0 = await k("#k3"); await shot("01-smog-today");
  await page.click('#modes button[data-mode="connected"]'); await page.waitForTimeout(150);
  const e1 = await k("#k3");
  if (e0 === e1) fail("map error is the same for one monitor and 25 sensors");
  await shot("02-smog-connected");
  await page.click('#layers button[data-layer="truth"]'); await page.waitForTimeout(150); await shot("03-smog-truth");
  await page.click('#layers button[data-layer="seen"]');
  const sensor = await page.evaluate(() => { const h = window.__city.hits().find((x) => /µg/.test(x.text) && !/Official/.test(x.text)); const r = document.getElementById("plan").getBoundingClientRect(); return h ? { x: r.left + h.x, y: r.top + h.y } : null; });
  if (!sensor) fail("no sensors drawn");
  await page.mouse.move(sensor.x, sensor.y); await page.waitForTimeout(150);
  if (!/µg\/m³/.test(await page.textContent("#tip"))) fail("hovering a sensor shows no reading");
  if (!(await page.isVisible("#layers"))) fail("the smog layer switch is hidden in the smog view");

  // rain: time moves the water; gates and stalls show in the right rule set
  await page.click('#views button[data-view="rain"]'); await page.waitForTimeout(150);
  if (await page.isVisible("#layers")) fail("the smog layer switch still shows in the rain view");
  await page.click('#modes button[data-mode="today"]');
  await page.evaluate(() => { window.__city.state.t.rain = 55; window.__city.frame(true); });
  const deepToday = parseFloat(await k("#k1")), stalled = +(await k("#k2"));
  if (!(deepToday > 0.3) || !(stalled > 0)) fail(`today at 18:55 the water should be deep and drivers stalled (${deepToday} m, ${stalled})`);
  await shot("04-rain-today");
  await page.click('#modes button[data-mode="connected"]'); await page.waitForTimeout(150);
  if (parseFloat(await k("#k1")) >= deepToday || +(await k("#k2")) !== 0) fail("connected should keep the water lower and strand nobody");
  await shot("05-rain-connected");
  await page.evaluate(() => { window.__city.state.t.rain = 0; window.__city.frame(true); });
  await page.click("#play"); await page.waitForTimeout(1500); await page.click("#play");
  if (!((await page.evaluate(() => window.__city.state.t.rain)) > 0)) fail("play did not move the storm on");

  // night: outside the load-shedding hour dimming saves power (inside it, Connected keeps main
  // roads lit on a battery while Today's east is simply dark, so it draws more - that is the point)
  await page.click('#views button[data-view="night"]');
  await page.evaluate(() => { window.__city.state.t.night = 60; window.__city.frame(true); });
  await page.click('#modes button[data-mode="today"]'); await page.waitForTimeout(150);
  const kwT = parseInt((await k("#k1")).replace(/,/g, ""));
  await page.click('#modes button[data-mode="connected"]'); await page.waitForTimeout(150);
  const kwC = parseInt((await k("#k1")).replace(/,/g, ""));
  if (!(kwC < kwT)) fail(`connected streetlights should draw less (${kwC} vs ${kwT} kW)`);
  await shot("06-night-connected");
  await page.evaluate(() => { window.__city.state.t.night = 130; window.__city.frame(true); }); await shot("07-night-outage");
  const dark = await page.evaluate(() => { const L = window.CITY.lights.modes; return [L.today.busy_road_minutes_dark, L.connected.busy_road_minutes_dark]; });
  if (!(dark[1] < dark[0])) fail(`connected should leave fewer busy roads dark (${dark})`);
  // keyboard
  const t0 = await page.evaluate(() => window.__city.state.t.night);
  await page.locator("body").click({ position: { x: 5, y: 880 } }); await page.keyboard.press("ArrowRight");
  if (!((await page.evaluate(() => window.__city.state.t.night)) > t0)) fail("ArrowRight did not step time");
  // theme and phone
  await page.click("#theme"); await page.waitForTimeout(250); await shot("08-light");
  await page.click('#views button[data-view="smog"]'); await page.waitForTimeout(200); await shot("09-light-smog");
  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(400); await shot("10-phone");
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (over > 2) fail(`page scrolls sideways by ${over}px at phone width`);
  await browser.close();
  console.log("ERRORS:", errors.length ? errors.join("\n") : "none");
  if (errors.length) process.exit(1);
})();

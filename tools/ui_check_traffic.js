// Drive the Traffic Twin viewer in headless Chromium like a user; save screenshots.
// usage: NODE_PATH=<dir with playwright> node tools/ui_check_traffic.js <outdir>
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

const out = process.argv[2] || "ui-shots";
fs.mkdirSync(out, { recursive: true });
process.on("unhandledRejection", (e) => { console.error("UI CHECK FAILED:", e && e.message ? e.message : e); process.exit(1); });
const fail = (m) => { throw new Error(m); };

(async () => {
  const exe = process.env.CHROMIUM || path.join(process.env.LOCALAPPDATA || "", "ms-playwright", "chromium-1243", "chrome-win64", "chrome.exe");
  const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
  await page.goto("file://" + path.resolve(__dirname, "..", "viewer", "traffic.html"));
  await page.waitForFunction(() => window.__traffic, null, { timeout: 30000 });
  const shot = async (n) => { await page.screenshot({ path: path.join(out, "traffic-" + n + ".png") }); console.log("shot", n); };
  const T = (fn, arg) => page.evaluate(fn, arg);

  await T(() => { window.__traffic.state.t = 1500; window.__traffic.frame(true); }); await page.waitForTimeout(600);
  await shot("01-whole");
  // the map streams: panning far away brings new tiles in
  await page.click("#zin"); await page.click("#zin"); await page.click("#zin");
  await page.waitForTimeout(2300); await T(() => window.__traffic.frame(true));      // tiles left behind are released
  const before = await T(() => Object.keys(window.__traffic.loadedAt));
  if (before.length >= 197) fail("zoomed in, the map still holds every tile");
  const cv = await page.locator("#plan").boundingBox();
  await page.mouse.move(cv.x + cv.width / 2, cv.y + cv.height / 2); await page.mouse.down();
  await page.mouse.move(cv.x + cv.width / 2 - 500, cv.y + cv.height / 2 - 300, { steps: 8 }); await page.mouse.up();
  await page.waitForTimeout(600);
  const after = await T(() => Object.keys(window.__traffic.loadedAt));
  const fresh = after.filter((k) => !before.includes(k));
  if (!fresh.length) fail(`panning did not stream new tiles (${before.length} -> ${after.length})`);
  console.log(`zoomed in: ${before.length} tiles held; panning streamed ${fresh.length} new ones`);
  if (await T(() => window.__traffic.state.follow) != null) fail("a drag should not start following");
  await shot("02-panned");
  // follow, and the hop when the vehicle arrives
  await page.click("#follow-random");
  const v = await T(() => { const X = window.__traffic, v = X.vehiclesOf(X.state.mode)[X.state.follow]; X.state.t = v.done - 4; X.frame(true); return v.i; });
  if (v == null) fail("Follow a vehicle did nothing");
  await page.selectOption("#speed", "15"); await page.click("#play"); await page.waitForTimeout(2500); await page.click("#play");
  const now = await T(() => window.__traffic.state.follow);
  if (now == null || now === v) fail("following did not hop to another vehicle when the first arrived");
  const note = await page.textContent("#pane-follow");
  if (!/arrived/.test(note)) fail("the hop is not explained in the Follow panel");
  await shot("03-follow-hop");
  // keyboard only: Tab to a hotspot, Enter opens its junction; Shift+arrow pans
  await page.click(".tabs button[data-tab=hot]");
  await page.focus("#pane-hot li[data-sig]"); await page.keyboard.press("Enter"); await page.waitForTimeout(300);
  if (!(await page.textContent("#pane-junction")).includes("Phase")) fail("Enter on a hotspot did not open its junction");
  const cx = await T(() => window.__traffic.state.cam.x);
  await page.locator("body").click({ position: { x: 5, y: 880 } }); await page.keyboard.press("Shift+ArrowRight");
  if (!((await T(() => window.__traffic.state.cam.x)) > cx)) fail("Shift+Right did not pan the map");
  // a hotspot flies to its junction and the junction panel stays live
  await page.click(".tabs button[data-tab=hot]"); await page.click("#pane-hot li[data-sig]");
  if (!(await page.textContent("#pane-junction")).includes("Phase")) fail("hotspot did not open its junction");
  const j1 = await page.textContent("#pane-junction");
  await page.click("#play"); await page.waitForTimeout(3000); await page.click("#play");
  if (j1 === await page.textContent("#pane-junction")) fail("junction panel did not update while playing");
  await shot("04-junction");
  // both rule sets compare; a signal on the map opens its phases
  await page.click('#modes button[data-mode="fixed"]'); await page.click(".tabs button[data-tab=compare]");
  if ((await page.locator("#pane-compare tr").count()) < 10) fail("comparison table too short");
  // drawing stays quick enough to play smoothly
  const ms = await T(() => { const X = window.__traffic; X.flyTo(0, 0, 0.15); const t0 = performance.now(); for (let i = 0; i < 10; i++) { X.state.t += 5; X.frame(true); } return (performance.now() - t0) / 10; });
  console.log(`whole-map frame ${ms.toFixed(1)} ms`);
  if (ms > 60) fail(`drawing the whole map takes ${ms.toFixed(0)} ms a frame`);
  await page.click("#theme"); await page.waitForTimeout(300); await shot("05-light");
  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(400); await shot("06-phone");
  const over = await T(() => document.documentElement.scrollWidth - window.innerWidth);
  if (over > 2) fail(`page scrolls sideways by ${over}px at phone width`);
  await browser.close();
  console.log("ERRORS:", errors.length ? errors.join("\n") : "none");
  if (errors.length) process.exit(1);
})();

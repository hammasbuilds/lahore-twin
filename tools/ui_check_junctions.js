// Use the Junction Planner like a person would: pick junctions, click every fix, switch to the
// ambulance, pick calls and ways, play, use the keyboard, change theme, phone width.
// usage: NODE_PATH=<dir with playwright> node tools/ui_check_junctions.js <outdir>
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

const out = process.argv[2] || "ui-shots";
fs.mkdirSync(out, { recursive: true });
const fail = (m) => { throw new Error(m); };
process.on("unhandledRejection", (e) => { console.error("UI CHECK FAILED:", e && e.message ? e.message : e); process.exit(1); });

(async () => {
  const exe = process.env.CHROMIUM || path.join(process.env.LOCALAPPDATA || "", "ms-playwright", "chromium-1243", "chrome-win64", "chrome.exe");
  const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") errors.push(m.type() + ": " + m.text()); });
  await page.goto("file://" + path.resolve(__dirname, "..", "viewer", "junctions.html"));
  await page.waitForFunction(() => window.__junctions, null, { timeout: 30000 });
  const shot = async (n) => { await page.screenshot({ path: path.join(out, "junctions-" + n + ".png") }); console.log("shot", n); };

  // every fix, on every junction: the numbers and the drawing change
  const nj = await page.locator("#pick option").count();
  if (nj < 3) fail(`only ${nj} junctions to pick`);
  for (let j = 0; j < nj; j++) {
    await page.selectOption("#pick", String(j)); await page.waitForTimeout(150);
    const seen = new Set();
    for (const fix of ["baseline", "retime", "adaptive", "uturn", "underpass"]) {
      await page.click(`tr[data-fix="${fix}"]`); await page.waitForTimeout(120);
      if ((await page.getAttribute(`tr[data-fix="${fix}"]`, "aria-pressed")) !== "true") fail(`${fix} row not selected`);
      seen.add(await page.textContent("#k1") + "|" + await page.textContent("#k3"));
      if (j === 0) await shot(`0${["baseline", "retime", "adaptive", "uturn", "underpass"].indexOf(fix) + 1}-${fix}`);
    }
    if (seen.size < 3) fail(`junction ${j}: fixes show the same numbers`);
  }
  // a U-turn gap tooltip
  await page.selectOption("#pick", "0"); await page.click('tr[data-fix="uturn"]');
  const gap = await page.evaluate(() => { const h = window.__junctions.hits()[0]; const r = document.getElementById("plan").getBoundingClientRect(); return h ? { x: r.left + h.x, y: r.top + h.y } : null; });
  if (!gap) fail("no U-turn gap drawn");
  await page.mouse.move(gap.x, gap.y); await page.waitForTimeout(150);
  if (!/U-turn/.test(await page.textContent("#tip"))) fail("U-turn gap has no tooltip");
  // keyboard: Tab to a fix row, Enter picks it
  await page.focus('tr[data-fix="retime"]'); await page.keyboard.press("Enter"); await page.waitForTimeout(120);
  if ((await page.getAttribute('tr[data-fix="retime"]', "aria-pressed")) !== "true") fail("Enter on a fix row did nothing");

  // ambulance: calls, ways, playing moves it along its route
  await page.click('#views button[data-view="amb"]'); await page.waitForTimeout(300);
  if (!(await page.isDisabled("#pick"))) fail("the junction picker should be off in the ambulance view");
  await shot("06-ambulance");
  const calls = await page.locator("li[data-call]").count();
  if (calls < 4) fail(`only ${calls} ambulance calls`);
  await page.click("li[data-call] >> nth=2"); await page.waitForTimeout(200);
  for (const m of ["none", "siren", "greenwave"]) {
    await page.click(`#ambmodes button[data-mode="${m}"]`); await page.waitForTimeout(150);
    if ((await page.getAttribute(`#ambmodes button[data-mode="${m}"]`, "aria-pressed")) !== "true") fail(`${m} not chosen`);
  }
  const k1g = await page.textContent("#k1");
  await page.click('#ambmodes button[data-mode="none"]'); await page.waitForTimeout(150);
  if (k1g === await page.textContent("#k1")) fail("no priority and green wave show the same response time");
  await page.click('#ambmodes button[data-mode="greenwave"]');
  const t0 = await page.evaluate(() => window.__junctions.state.t);
  await page.click("#play"); await page.waitForTimeout(2000); await page.click("#play");
  const t1 = await page.evaluate(() => window.__junctions.state.t);
  if (!(t1 > t0 + 20)) fail(`playing did not move time (${t0} -> ${t1})`);
  await page.keyboard.press("ArrowRight");
  if ((await page.evaluate(() => window.__junctions.state.t)) <= t1) fail("ArrowRight did not step time");
  await shot("07-ambulance-playing");
  // theme and phone
  await page.click("#theme"); await page.waitForTimeout(300); await shot("08-light");
  await page.click('#views button[data-view="plan"]'); await page.waitForTimeout(200); await shot("09-light-plan");
  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(400); await shot("10-phone");
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (over > 2) fail(`page scrolls sideways by ${over}px at phone width`);
  await browser.close();
  console.log("ERRORS:", errors.length ? errors.join("\n") : "none");
  if (errors.length) process.exit(1);
})();

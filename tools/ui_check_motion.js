// Watch the traffic move, not just load: signals cycle 60 s green / 15 s red on the main road,
// nobody drives through a red, vehicles move between seconds, and the junction planner and the
// city systems have traffic in every view. Screenshots with the traffic on screen.
// usage: NODE_PATH=<dir with playwright> node tools/ui_check_motion.js <outdir> [base url]
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

const out = process.argv[2] || "ui-shots";
const BASE = process.argv[3] || "http://127.0.0.1:8860/";
fs.mkdirSync(out, { recursive: true });
const failures = [];
const fail = (m) => { failures.push(m); console.error("FAIL:", m); };
const log = (...a) => console.log(...a);

(async () => {
  const exe = process.env.CHROMIUM || path.join(process.env.LOCALAPPDATA || "", "ms-playwright", "chromium-1243", "chrome-win64", "chrome.exe");
  const browser = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
  const shot = async (n) => { await page.screenshot({ path: path.join(out, "motion-" + n + ".png") }); log("shot", n); };

  // ---------------------------------------------------------------- Lahore traffic
  await page.goto(BASE + "traffic.html");
  await page.waitForFunction(() => window.__traffic, null, { timeout: 60000 });
  const sig = await page.evaluate(() => {
    const R = window.TRAFFIC, out = { mains: [], reds: [], sides: [], plans: {} };
    for (const s of R.signal_sites) out.plans[(s.greens || []).join("/")] = (out.plans[(s.greens || []).join("/")] || 0) + 1;
    for (const s of R.signal_sites) {
      if (!s.greens) continue;
      const main = s.greens[0] >= s.greens[1] ? 0 : 1, lg = R.modes.fixed.signals[String(s.id)] || [];
      const starts = lg.filter((e) => e[1] === main && e[2] === "green").map((e) => e[0]);
      for (let i = 0; i + 1 < starts.length; i++) {
        const amb = lg.find((e) => e[0] > starts[i] && e[1] === main && e[2] === "amber");
        if (!amb) continue;
        out.mains.push(amb[0] - starts[i]);                       // main green
        out.reds.push(starts[i + 1] - (amb[0] + 3));              // main red: from the end of amber to the next green
      }
    }
    const med = (a) => a.slice().sort((x, y) => x - y)[Math.floor(a.length / 2)];
    return { plans: out.plans, mainGreen: med(out.mains), mainRed: med(out.reds), cycles: out.mains.length };
  });
  log("traffic signal plans", JSON.stringify(sig.plans), "| main green median", sig.mainGreen, "s, main red median", sig.mainRed, "s over", sig.cycles, "cycles");
  if (sig.mainGreen !== 60) fail(`main road green is ${sig.mainGreen} s, not 60`);
  if (sig.mainRed !== 15) fail(`main road red is ${sig.mainRed} s, not 15`);

  // nobody crosses a stop line while their light is red (fixed signals, the whole evening)
  const obey = await page.evaluate(() => {
    const T = window.__traffic, R = window.TRAFFIC, approach = {};
    for (const s of R.signal_sites) s.phases.forEach((ids, ph) => ids.forEach((lid) => { approach[lid] = [s.id, ph]; }));
    const lg = R.modes.fixed.signals;
    const state = (sid, ph, t) => {                       // the light this phase shows at t
      const L = lg[String(sid)] || []; let i = -1;
      for (let a = 0, b = L.length; a < b;) { const m = (a + b) >> 1; if (L[m][0] <= t) { i = m; a = m + 1; } else b = m; }
      if (i < 0) return "green"; const [, p, st] = L[i];
      return p !== ph || st === "allred" ? "red" : st;
    };
    T.state.mode = "fixed";
    const vs = T.vehiclesOf("fixed"); let crossings = 0, onRed = 0; const examples = [];
    for (const v of vs) {
      if (!v.cum.length) continue;
      for (let t = v.ts; t + 4 <= v.ts + (v.cum.length - 1) * R.meta.sample; t += 4) {
        const a = T.vehAt(v, t), b = T.vehAt(v, t + 4);
        if (!a || !b || a.link === b.link || !(a.link in approach)) continue;
        crossings++;
        const [sid, ph] = approach[a.link];
        if (state(sid, ph, t) === "red" && state(sid, ph, t + 4) === "red") { onRed++; if (examples.length < 3) examples.push([v.i, t, sid]); }
      }
    }
    // moving now: at 18:00
    let moving = 0, on = 0; for (const v of vs) { const p = T.vehAt(v, 1800); if (p && !p.parked) { on++; if (p.speed > 1) moving++; } }
    return { crossings, onRed, examples, on, moving };
  });
  log("traffic: stop-line crossings", obey.crossings, "| through a red", obey.onRed, obey.examples.length ? JSON.stringify(obey.examples) : "", "| at 18:00", obey.on, "on the road,", obey.moving, "moving");
  if (obey.crossings < 1000) fail(`only ${obey.crossings} stop-line crossings found: the check saw too little`);
  if (obey.onRed > obey.crossings * 0.002) fail(`${obey.onRed} vehicles drove through a red`);
  if (obey.moving < obey.on * 0.15) fail(`only ${obey.moving} of ${obey.on} vehicles moving at 18:00`);
  await page.evaluate(() => { const T = window.__traffic; T.state.t = 1800; T.frame(true); });
  await page.waitForTimeout(300); await shot("01-traffic");

  // ---------------------------------------------------------------- junction planner
  await page.goto(BASE + "junctions.html");
  await page.waitForFunction(() => window.__junctions, null, { timeout: 60000 });
  for (let j = 0; j < 3; j++) {
    for (const fix of ["baseline", "retime", "adaptive", "uturn", "underpass"]) {
      await page.evaluate(([j, fix]) => { const X = window.__junctions; X.state.j = j; X.state.fix = fix; X.state.t = 600; X.render(); }, [j, fix]);
      await page.waitForFunction(([j, fix]) => window.__junctions.traffic(j, fix), [j, fix], { timeout: 30000 }).catch(() => {});
      const r = await page.evaluate(([j, fix]) => {
        const X = window.__junctions; X.frame();
        const n0 = X.vehicles(), tr = X.traffic(j, fix);
        if (!tr) return { n0, moved: 0, lights: [] };
        const at = (t) => new Map(TwinTracks.live(tr, t).map(([v, p]) => [v, p]));
        const a = at(600), b = at(610); let moved = 0, both = 0;
        for (const [v, p] of a) { const q = b.get(v); if (q) { both++; if (Math.hypot(q.x - p.x, q.y - p.y) > 2) moved++; } }
        const lg = window.JUNCTIONS.junctions[j].fixes[fix].signal_log, lights = new Set();
        // an adaptive light rests on green while nobody waits on the other road: give it ten minutes
        const span = fix === "adaptive" ? 600 : 100;
        for (let t = 600; t < 600 + span; t += 5) { const s = X.signalAt(lg, t); if (s) lights.add(s.join(":")); }
        return { n0, moved, both, lights: [...lights] };
      }, [j, fix]);
      log(`junction ${j} ${fix}: ${r.n0} vehicles, ${r.moved}/${r.both} moved in 10 s, signal states seen ${r.lights.join(" ")}`);
      if (!(r.n0 > 5)) fail(`junction ${j} ${fix}: ${r.n0} vehicles drawn`);
      if (!(r.moved > 0)) fail(`junction ${j} ${fix}: nothing moved in 10 s`);
      if (fix !== "uturn" && r.lights.filter((s) => s.endsWith("green")).length < 2) fail(`junction ${j} ${fix}: the signal never changed phase (${r.lights})`);
    }
    if (j === 0) { await page.evaluate(() => { const X = window.__junctions; X.state.fix = "baseline"; X.render(); }); await page.waitForTimeout(300); await shot("02-junction-today"); }
  }
  await page.evaluate(() => { const X = window.__junctions; X.state.j = 0; X.state.fix = "uturn"; X.render(); }); await page.waitForTimeout(300); await shot("03-junction-uturn");
  // the ambulance view: the traffic it drives through, under each way of running the signals
  for (const mode of ["none", "siren", "greenwave"]) {
    await page.evaluate((mode) => { const X = window.__junctions; X.state.mode = mode; X.setView("amb"); }, mode);
    await page.waitForFunction(() => window.JUNCTION_AMB_TRAFFIC || window.JUNCTIONS.ambulance.tracks, null, { timeout: 30000 }).catch(() => {});
    const n = await page.evaluate(() => { const X = window.__junctions; X.frame(); return X.vehicles(); });
    log(`ambulance ${mode}: ${n} vehicles near the route`);
    if (!(n > 5)) fail(`ambulance ${mode}: ${n} vehicles drawn`);
  }
  await page.waitForTimeout(300); await shot("03b-ambulance");

  // ---------------------------------------------------------------- city systems
  await page.goto(BASE + "city.html");
  await page.waitForFunction(() => window.__city, null, { timeout: 60000 });
  for (const [view, t] of [["smog", 50], ["rain", 55], ["night", 60]]) {
    for (const mode of ["today", "connected"]) {
      await page.click(`#views button[data-view="${view}"]`); await page.click(`#modes button[data-mode="${mode}"]`);
      await page.evaluate(([view, t]) => { const X = window.__city; X.state.t[view] = t; X.frame(true); }, [view, t]);
      await page.waitForFunction(([v, m]) => window.__city.traffic(v, m), [view, mode], { timeout: 60000 }).catch(() => {});
      const r = await page.evaluate(([view, mode, t]) => {
        const X = window.__city; X.frame(true);
        const tr = X.traffic(view, mode); if (!tr) return { n: 0 };
        const L = TwinTracks.live(tr, t * 60), still = L.filter(([, p]) => p.still).length;
        const a = new Map(L), b = new Map(TwinTracks.live(tr, t * 60 + 16)); let moved = 0;
        for (const [v, p] of a) { const q = b.get(v); if (q && Math.hypot(q.x - p.x, q.y - p.y) > 5) moved++; }
        return { n: X.vehicles(), live: L.length, still, moved };
      }, [view, mode, t]);
      log(`city ${view} ${mode}: ${r.n} drawn, ${r.live} on the road, ${r.still} standing, ${r.moved} moved in 16 s`);
      if (!(r.n > 50)) fail(`city ${view} ${mode}: only ${r.n} vehicles drawn`);
      if (!(r.moved > r.live * 0.1)) fail(`city ${view} ${mode}: only ${r.moved} of ${r.live} moved`);
      await shot(`04-city-${view}-${mode}`);
    }
  }
  await browser.close();
  log("PAGE ERRORS:", errors.length ? errors.join("\n") : "none");
  log("RESULT:", failures.length || errors.length ? `${failures.length + errors.length} problem(s)` : "all motion checks passed");
  process.exit(failures.length || errors.length ? 1 : 0);
})();

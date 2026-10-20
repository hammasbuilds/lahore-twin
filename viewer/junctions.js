/* Junction Planner viewer: the evening's worst junctions with each fix drawn on the real
 * roads and measured on the same trips, and Rescue 1122 ambulances under three ways of
 * running the signals, with a time-distance (green-wave) diagram. Data: window.JUNCTIONS.
 */
"use strict";

(function () {
  const R = window.JUNCTIONS;
  const C = TwinCore;
  const T0 = R.meta.start;
  const FIXES = ["baseline", "retime", "adaptive", "uturn", "underpass"];
  const MODES = { none: "No priority", siren: "Siren", greenwave: "Green wave" };
  const RANK = { motorway: 7, trunk: 6, primary: 5, secondary: 4, tertiary: 3, unclassified: 2, residential: 1,
                 living_street: 0, service: 0, trunk_link: 5, primary_link: 4, secondary_link: 3, tertiary_link: 2, motorway_link: 6 };
  const LANE_W = 3.2;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  let palette = {};
  function readPalette() {
    for (const k of ["bg", "panel", "panel-2", "text", "muted", "line", "accent", "floor-out", "rescue", "sig-red", "sig-green",
      "road-major", "road-mid", "road-minor", "road-edge", "siren", "none", "warn"]) palette[k] = css("--" + k);
  }
  const MODE_COL = () => ({ none: palette.none, siren: palette.siren, greenwave: palette.rescue });

  const state = { view: "plan", j: 0, fix: "uturn", call: 0, mode: "greenwave", t: 0, playing: false };
  try {
    const saved = JSON.parse(localStorage.getItem("junction-planner") || "{}");
    if (saved.theme) document.documentElement.dataset.theme = saved.theme;
  } catch (e) { /* storage blocked */ }

  // junction roads, decoded
  const J = R.junctions.map((j) => ({ ...j, roads: j.roads.map(([ci, lanes, oneway, layer, name, flat]) => {
    const pts = []; for (let i = 0; i < flat.length; i += 2) pts.push([flat[i], flat[i + 1]]);
    const cls = R.classes[ci]; return { cls, rank: RANK[cls] || 0, lanes, oneway: !!oneway, layer, name, pts };
  }) }));
  const AREA = R.area.map(([layer, major, flat]) => { const pts = []; for (let i = 0; i < flat.length; i += 2) pts.push([flat[i], flat[i + 1]]); return { layer, major, pts }; });
  const CALLS = R.ambulance.calls.map((c) => {
    const pts = []; for (let i = 0; i < c.line.length; i += 2) pts.push([c.line[i], c.line[i + 1]]);
    const cum = [0]; for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
    return { ...c, pts, cum };
  });

  // ---- canvas ----
  const cv = $("plan"), ctx = cv.getContext("2d"), tl = $("tl"), tctx = tl.getContext("2d");
  let W = 0, H = 0, hits = [];
  function fit() {
    const dpr = window.devicePixelRatio || 1;
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    tl.width = Math.round(tl.clientWidth * dpr); tl.height = Math.round(tl.clientHeight * dpr); tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  let view = { s: 1, ox: 0, oy: 0 };
  const SX = (x) => view.ox + x * view.s, SY = (y) => view.oy + y * view.s;
  const line = (pts, c = ctx) => { c.beginPath(); pts.forEach(([x, y], k) => (k ? c.lineTo(SX(x), SY(y)) : c.moveTo(SX(x), SY(y)))); c.stroke(); };
  function roadCol(r) { return r.rank >= 4 ? palette["road-major"] : r.rank >= 2 ? palette["road-mid"] : palette["road-minor"]; }

  function drawPlan() {
    const j = J[state.j], R0 = 330;
    view.s = Math.min(W, H) / (2 * R0); view.ox = W / 2; view.oy = H / 2;
    ctx.fillStyle = palette["floor-out"]; ctx.fillRect(0, 0, W, H);
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    const roads = j.roads.slice().sort((a, b) => (a.layer - b.layer) || (a.rank - b.rank));
    const under = state.fix === "underpass";
    for (const pass of ["edge", "fill"]) {
      for (const r of roads) {
        const w = Math.max(r.rank >= 3 ? 3 : 1.5, (r.oneway ? r.lanes : 2 * r.lanes) * LANE_W * view.s);
        ctx.globalAlpha = r.layer < 0 ? 0.55 : 1;
        if (pass === "edge") {
          ctx.strokeStyle = r.layer > 0 ? palette.text : palette["road-edge"]; ctx.lineWidth = w + (r.layer > 0 ? 4 : 2);
          if (r.layer < 0) ctx.setLineDash([6, 5]);
          line(r.pts); ctx.setLineDash([]);
        } else { ctx.strokeStyle = roadCol(r); ctx.lineWidth = w; line(r.pts); }
      }
    }
    ctx.globalAlpha = 1;
    // the fix, drawn
    const ap = j.approaches;
    if (under) {
      // the main road dips under the crossing: a dashed tunnel through the centre
      const mainAp = ap.filter((a) => a[0] === j.main_phase);
      ctx.strokeStyle = palette.accent; ctx.lineWidth = 5; ctx.setLineDash([10, 7]);
      for (const [, x, y, px, py] of mainAp) {
        const dx = x - px, dy = y - py, L = Math.hypot(dx, dy) || 1;
        ctx.beginPath(); ctx.moveTo(SX(x - dx / L * 90), SY(y - dy / L * 90)); ctx.lineTo(SX(x + dx / L * 60), SY(y + dy / L * 60)); ctx.stroke();
      }
      ctx.setLineDash([]);
      label("Underpass: " + j.main.join(", ") + " straight on, signal-free", 0, -R0 * 0.85);
    }
    if (state.fix === "uturn") {
      // crossing closed: the side road may only turn left; U-turn gaps along the main road
      for (const [ph, x, y] of ap) if (ph !== j.main_phase) { ctx.strokeStyle = palette["sig-red"]; ctx.lineWidth = 3; const s = 7; ctx.beginPath(); ctx.moveTo(SX(x) - s, SY(y) - s); ctx.lineTo(SX(x) + s, SY(y) + s); ctx.moveTo(SX(x) + s, SY(y) - s); ctx.lineTo(SX(x) - s, SY(y) + s); ctx.stroke(); }
      for (const [x, y] of j.gaps) {
        ctx.strokeStyle = palette.accent; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(SX(x), SY(y), 11, Math.PI * 0.15, Math.PI * 1.85); ctx.stroke();
        ctx.fillStyle = palette.accent; ctx.font = "600 12px Segoe UI, system-ui"; ctx.textAlign = "left"; ctx.fillText("U-turn", SX(x) + 15, SY(y) + 4);
        hits.push({ x: SX(x), y: SY(y), r: 16, text: "U-turn gap in the main road: through and right-turning traffic turns left and comes back here" });
      }
      label("Crossing closed: no signal, side roads turn left only", 0, -R0 * 0.85);
    } else {
      // signal heads, coloured by phase; the long green bold
      const r = j.fixes[state.fix];
      for (const [ph, x, y] of ap) {
        ctx.fillStyle = ph === j.main_phase ? palette["sig-green"] : palette["sig-red"]; ctx.strokeStyle = palette.bg; ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.arc(SX(x), SY(y), 6, 0, 7); ctx.fill(); ctx.stroke();
      }
      if (state.fix === "adaptive") label("Adaptive: loop detectors 40 m back hold the green while traffic comes", 0, -R0 * 0.85);
      else if (r && r.greens) label(`${state.fix === "baseline" ? "Today" : "Retimed"}: ${j.main.join(", ")} ${r.greens[j.main_phase]} s · ${j.side.join(", ") || "side road"} ${r.greens[1 - j.main_phase]} s green`, 0, -R0 * 0.85);
    }
    // scale bar
    ctx.strokeStyle = palette.muted; ctx.lineWidth = 2; const bar = 100 * view.s;
    ctx.beginPath(); ctx.moveTo(14, H - 18); ctx.lineTo(14 + bar, H - 18); ctx.stroke();
    ctx.fillStyle = palette.muted; ctx.font = "11px Segoe UI, system-ui"; ctx.textAlign = "left"; ctx.fillText("100 m", 18 + bar, H - 14);
  }
  function label(text, x, y) {
    ctx.font = "600 13px Segoe UI, system-ui"; ctx.textAlign = "center";
    const w = ctx.measureText(text).width + 16;
    ctx.fillStyle = palette.panel; ctx.globalAlpha = 0.92; ctx.fillRect(SX(x) - w / 2, SY(y) - 14, w, 24); ctx.globalAlpha = 1;
    ctx.fillStyle = palette.text; ctx.fillText(text, SX(x), SY(y) + 3);
  }

  // ambulance: the whole area, the call's route, the ambulance now
  function ambAt(c, mode, t) {
    const m = c.modes[mode]; if (!m || !m.trace.length) return null;
    const tr = m.trace; if (t < tr[0][0]) return null;
    let i = C.bisectRight(tr, t, (e) => e[0]) - 1; if (i < 0) return null;
    if (i >= tr.length - 1) return { d: tr[tr.length - 1][1], done: true };
    const [t0, d0] = tr[i], [t1, d1] = tr[i + 1];
    return { d: d0 + (d1 - d0) * (t - t0) / (t1 - t0), done: false };
  }
  function pointAt(c, d) {
    let i = C.bisectRight(c.cum, d, (x) => x) - 1; i = Math.max(0, Math.min(c.pts.length - 2, i));
    const f = (d - c.cum[i]) / ((c.cum[i + 1] - c.cum[i]) || 1);
    return [c.pts[i][0] + (c.pts[i + 1][0] - c.pts[i][0]) * f, c.pts[i][1] + (c.pts[i + 1][1] - c.pts[i][1]) * f];
  }
  function drawAmb() {
    const c = CALLS[state.call];
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [x, y] of c.pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    const [sx, sy] = R.ambulance.station; x0 = Math.min(x0, sx); x1 = Math.max(x1, sx); y0 = Math.min(y0, sy); y1 = Math.max(y1, sy);
    const pad = 160; view.s = Math.min(W / (x1 - x0 + 2 * pad), H / (y1 - y0 + 2 * pad));
    view.ox = W / 2 - (x0 + x1) / 2 * view.s; view.oy = H / 2 - (y0 + y1) / 2 * view.s;
    ctx.fillStyle = palette["floor-out"]; ctx.fillRect(0, 0, W, H);
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    for (const r of AREA) { ctx.strokeStyle = r.major ? palette["road-major"] : palette["road-minor"]; ctx.globalAlpha = r.layer < 0 ? 0.4 : 0.7; ctx.lineWidth = r.major ? 2.4 : 0.8; line(r.pts); }
    ctx.globalAlpha = 1;
    ctx.strokeStyle = palette.rescue; ctx.lineWidth = 5; ctx.globalAlpha = 0.85; line(c.pts); ctx.globalAlpha = 1;
    // signals on the route, coloured as the chosen mode had them at this moment
    const m = c.modes[state.mode];
    c.signals.forEach(([d, , , name], k) => {
      const [x, y] = pointAt(c, d), on = m && m.greens[k].some(([a, b]) => a <= state.t && state.t < b);
      ctx.fillStyle = on ? palette["sig-green"] : palette["sig-red"]; ctx.strokeStyle = palette.bg; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(SX(x), SY(y), 6, 0, 7); ctx.fill(); ctx.stroke();
      hits.push({ x: SX(x), y: SY(y), r: 10, text: `${name} · ${on ? "green" : "red"} for the ambulance now` });
    });
    marker(sx, sy, "1122", palette.rescue, "Rescue 1122 station (OpenStreetMap)");
    for (const [hx, hy, name] of R.ambulance.hospitals) marker(hx, hy, "H", palette.accent, name);
    const scene = m && m.scene_at ? ambAt(c, state.mode, m.scene_at[0]) : null;
    if (scene) { const [x, y] = pointAt(c, scene.d); marker(x, y, "!", palette.warn, "The call: ten minutes there"); }
    for (const mode of Object.keys(MODES)) {
      const p = ambAt(c, mode, state.t); if (!p || p.done) continue;
      const [x, y] = pointAt(c, p.d);
      ctx.fillStyle = MODE_COL()[mode]; ctx.strokeStyle = palette.bg; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(SX(x), SY(y), mode === state.mode ? 8 : 5, 0, 7); ctx.fill(); ctx.stroke();
    }
  }
  function marker(x, y, text, col, tip) {
    ctx.fillStyle = col; ctx.strokeStyle = palette.bg; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(SX(x), SY(y), 10, 0, 7); ctx.fill(); ctx.stroke();
    ctx.fillStyle = palette.bg; ctx.font = "700 10px Segoe UI, system-ui"; ctx.textAlign = "center"; ctx.fillText(text, SX(x), SY(y) + 3.5);
    hits.push({ x: SX(x), y: SY(y), r: 12, text: tip });
  }

  // ---- panels ----
  const fmt = (v, d = 1) => v == null ? "–" : Number.isInteger(v) ? v.toLocaleString("en") : v.toFixed(d);
  const mmss = (s) => s == null ? "–" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
  function renderPlan() {
    const j = J[state.j], b = j.fixes.baseline, f = j.fixes[state.fix];
    $("k1").textContent = fmt(f.junction_veh_h); $("k1l").textContent = `vehicle-hours lost here (today ${fmt(b.junction_veh_h)})`;
    $("k2").textContent = fmt(f.queue_peak, 0); $("k2l").textContent = `most standing within 350 m (today ${b.queue_peak})`;
    $("k3").textContent = (f.km_extra > 0 ? "+" : "") + fmt(f.km_extra); $("k3l").textContent = "km driven, against today";
    const best = Math.min(...FIXES.map((x) => j.fixes[x].junction_veh_h));
    let html = `<h3>${esc(j.name)}</h3><p class="note">Main road: ${esc(j.main.join(", "))}. Every fix meets exactly the same ${R.meta.trips.toLocaleString("en")} trips (30 minutes of the 17:30 peak, 8,000 trips an hour). Click a fix to draw it.</p>`;
    html += `<table class="cmp"><tr><th>Fix</th><th>Lost here, veh-h</th><th>Queue peak</th><th>Median delay, s</th><th>Extra km</th></tr>`;
    for (const x of FIXES) {
      const r = j.fixes[x];
      html += `<tr class="fixrow ${x === state.fix ? "sel" : ""}" data-fix="${x}" tabindex="0" role="button" aria-pressed="${x === state.fix}"><td>${esc(R.fix_names[x])}</td><td class="num ${r.junction_veh_h === best ? "best" : ""}">${fmt(r.junction_veh_h)}</td><td class="num">${r.queue_peak}</td><td class="num">${fmt(r.delay_median_s)}</td><td class="num">${x === "baseline" ? "–" : (r.km_extra > 0 ? "+" : "") + fmt(r.km_extra)}</td></tr>`;
    }
    html += `</table><div class="key"><span><i style="background:var(--muted)"></i>As today</span><span><i style="background:var(--accent)"></i>${esc(R.fix_names[state.fix])}</span></div><canvas class="chart" id="c-queue" style="height:130px" aria-label="Vehicles standing near the junction over time"></canvas>`;
    const notes = {
      baseline: `Today's fixed plan: ${f.greens ? f.greens[j.main_phase] + " s for the main road, " + f.greens[1 - j.main_phase] + " s for the side road" : ""}, plus 3 s amber and 2 s all-red each way.`,
      retime: `Webster's method on the demand each approach really carries (motorcycle 0.4, car 1, bus 3 PCU; 1,800 an hour per lane of green). It can turn the split around: here ${esc(j.main.join(", "))} gets ${f.greens ? f.greens[j.main_phase] : "?"} s and the side road ${f.greens ? f.greens[1 - j.main_phase] : "?"} s. Cheapest fix: a timing sheet.`,
      adaptive: "Loop detectors 40 m back on every approach at this junction only: the green is held while vehicles keep coming, 10 s minimum, ends on a 3 s gap.",
      uturn: `The crossing closes, Lahore's signal-free-corridor conversion. ${f.rerouted ? f.rerouted.toLocaleString("en") + " trips" : "Trips"} that went straight across or turned right now turn left and U-turn at a gap in the main road 150–400 m away. It costs extra driving, and pedestrians lose the signal-protected crossing.`,
      underpass: "The main road's straight-on traffic goes under the crossing; turning traffic and the side road keep a surface signal, retimed for what is left. Pedestrians keep the surface crossing. It costs years of digging, not modelled here.",
    };
    html += `<p class="note">${notes[state.fix]}</p><p class="note">Pedestrians: ${esc(f.pedestrian_crossing)}. "Lost here" counts vehicle-hours stopped within 350 m of the centre, which takes in the U-turn gaps. Simulated; demand split, PCU values and saturation flow are assumptions.</p>`;
    $("pane-plan").innerHTML = html;
    drawQueue();
  }
  function drawQueue() {
    const c = $("c-queue"); if (!c) return;
    const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
    c.width = w * dpr; c.height = h * dpr; const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const j = J[state.j], a = j.fixes.baseline.queue, b = j.fixes[state.fix].queue, n = Math.max(a.length, b.length);
    const max = Math.max(5, ...a, ...b), L = 26, B = 16;
    const xs = (i) => L + (w - L - 4) * i / (n - 1), ys = (v) => 4 + (h - B - 4) * (1 - v / max);
    g.strokeStyle = palette.line; g.fillStyle = palette.muted; g.font = "10.5px Segoe UI, system-ui"; g.textAlign = "right";
    for (const v of [0, Math.round(max / 2), max]) { g.beginPath(); g.moveTo(L, ys(v)); g.lineTo(w - 4, ys(v)); g.stroke(); g.fillText(String(v), L - 4, ys(v) + 3); }
    g.textAlign = "center";
    for (let m = 0; m * 2 < n; m += 15) g.fillText(C.clock(T0 + m * 60), xs(m * 2), h - 3);
    const plot = (arr, col, wd) => { g.strokeStyle = col; g.lineWidth = wd; g.beginPath(); arr.forEach((v, i) => (i ? g.lineTo(xs(i), ys(v)) : g.moveTo(xs(i), ys(v)))); g.stroke(); };
    plot(a, palette.muted, 1.3); if (state.fix !== "baseline") plot(b, palette.accent, 2);
    const ti = state.t / 30; g.strokeStyle = palette.text; g.globalAlpha = 0.5; g.beginPath(); g.moveTo(xs(ti), 4); g.lineTo(xs(ti), h - B); g.stroke(); g.globalAlpha = 1;
  }
  function renderAmb() {
    const S = R.ambulance.summary, c = CALLS[state.call], m = c.modes[state.mode];
    $("k1").textContent = mmss(S[state.mode].response_mean_s); $("k1l").textContent = `mean time to the call (${MODES[state.mode]})`;
    $("k2").textContent = mmss(S[state.mode].to_hospital_mean_s); $("k2l").textContent = "mean time on to hospital";
    $("k3").textContent = S[state.mode].reds; $("k3l").textContent = "red lights met, all calls";
    let html = `<div class="seg" id="ambmodes" role="group" aria-label="Signals for the ambulance" style="margin-bottom:8px">${Object.entries(MODES).map(([k, n]) => `<button data-mode="${k}" aria-pressed="${k === state.mode}">${n}</button>`).join("")}</div>`;
    html += `<table class="cmp"><tr><th></th>${Object.values(MODES).map((n) => `<th>${n}</th>`).join("")}</tr>`;
    const rows = [["To the call, mean", "response_mean_s", mmss], ["On to hospital, mean", "to_hospital_mean_s", mmss], ["Calls compared", "compared_hospital", (v) => v], ["Red lights met", "reds", (v) => v],
      ["Signals turned for it", "preemptions", (v) => v], ["Everyone else's median delay, s", "network_delay_median_s", (v) => fmt(v)]];
    for (const [label, key, f] of rows) html += `<tr><td>${label}</td>${Object.keys(MODES).map((k) => `<td class="num">${f(S[k][key])}</td>`).join("")}</tr>`;
    html += `</table><h3>Calls</h3><ul class="calls">` + CALLS.map((cc, i) => {
      const r = cc.modes[state.mode];
      return `<li data-call="${i}" tabindex="0" role="button" class="${i === state.call ? "sel" : ""}"><span class="num">${C.clock(T0 + cc.t0)}</span><span>${esc(cc.hospital || "")} <span class="muted">· ${(cc.length / 1000).toFixed(1)} km, ${cc.signals.length} signal${cc.signals.length === 1 ? "" : "s"}</span></span><span class="num">${r ? mmss(r.response_s) : "–"}</span></li>`;
    }).join("") + `</ul>`;
    html += `<h3>Time against distance, this call</h3><div class="key">${Object.entries(MODES).map(([k, n]) => `<span><i style="background:${MODE_COL()[k]}"></i>${n}</span>`).join("")}<span><i style="background:var(--sig-green)"></i>green for it (${MODES[state.mode]})</span></div><canvas class="chart" id="c-td" style="height:230px" aria-label="Time-distance diagram"></canvas>`;
    html += `<p class="note">Each horizontal band is a signal on the route, green when it showed green for the ambulance's direction under the chosen way. A steep line is fast; a flat step is waiting. Siren: cars ahead pull over where they can and it crosses a red slowly after stopping. Green wave: Safe City turns each signal green about 25 s ahead of it (≤300 m), keeping amber and all-red. Response is from dispatch at the Rescue 1122 station on OpenStreetMap; the call is ten minutes; the hospital is the nearest with an emergency department. Field studies of signal preemption report 14–23% shorter emergency trips.</p>`;
    $("pane-amb").innerHTML = html;
    drawTD();
  }
  function drawTD() {
    const cvs = $("c-td"); if (!cvs) return;
    const c = CALLS[state.call];
    const dpr = window.devicePixelRatio || 1, w = cvs.clientWidth, h = cvs.clientHeight;
    cvs.width = w * dpr; cvs.height = h * dpr; const g = cvs.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const traces = Object.keys(MODES).map((k) => c.modes[k]).filter(Boolean);
    const tA = c.t0, tB = Math.max(...traces.map((m) => m.trace.length ? m.trace[m.trace.length - 1][0] : c.t0 + 60));
    const L = 40, B = 18, xs = (t) => L + (w - L - 6) * (t - tA) / (tB - tA), ys = (d) => 6 + (h - B - 6) * (1 - d / c.length);
    const m = c.modes[state.mode];
    c.signals.forEach(([d], k) => {
      g.fillStyle = palette["sig-red"]; g.globalAlpha = 0.35; g.fillRect(L, ys(d) - 2, w - L - 6, 4);
      g.fillStyle = palette["sig-green"]; g.globalAlpha = 0.9;
      if (m) for (const [a, b] of m.greens[k]) if (b > tA && a < tB) g.fillRect(xs(Math.max(a, tA)), ys(d) - 2, xs(Math.min(b, tB)) - xs(Math.max(a, tA)), 4);
    });
    g.globalAlpha = 1;
    g.fillStyle = palette.muted; g.font = "10.5px Segoe UI, system-ui"; g.textAlign = "right";
    for (let km = 0; km <= c.length / 1000; km += 1) g.fillText(km + " km", L - 4, ys(km * 1000) + 3);
    g.textAlign = "center";
    for (let t = Math.ceil(tA / 120) * 120; t < tB; t += 120) g.fillText(C.clock(T0 + t), xs(t), h - 4);
    for (const [k] of Object.entries(MODES)) {
      const mm = c.modes[k]; if (!mm) continue;
      g.strokeStyle = MODE_COL()[k]; g.lineWidth = k === state.mode ? 2.4 : 1.3; g.beginPath();
      mm.trace.forEach(([t, d], i) => (i ? g.lineTo(xs(t), ys(d)) : g.moveTo(xs(t), ys(d)))); g.stroke();
    }
    if (state.t >= tA && state.t <= tB) { g.strokeStyle = palette.text; g.globalAlpha = 0.5; g.beginPath(); g.moveTo(xs(state.t), 6); g.lineTo(xs(state.t), h - B); g.stroke(); g.globalAlpha = 1; }
  }
  function renderTimeline() {
    const w = tl.clientWidth, h = tl.clientHeight;
    tctx.clearRect(0, 0, w, h);
    const T = R.meta.t1;
    // the calls as ticks, the selected one in red
    CALLS.forEach((c, i) => { tctx.fillStyle = i === state.call ? palette.rescue : palette.muted; tctx.fillRect(w * c.t0 / T - 1.5, 2, 3, h - 4); });
    tctx.fillStyle = palette.accent; tctx.fillRect(w * state.t / T - 1, 0, 2, h);
    const out = []; for (let m = 0; m <= T / 60; m += 5) out.push(`<span>${C.clock(T0 + m * 60)}</span>`); $("ticks").innerHTML = out.join("");
  }
  function renderLegend() {
    $("legend").innerHTML = state.view === "plan"
      ? `<span><i style="background:${palette["sig-green"]}"></i>Main road's signal</span><span><i style="background:${palette["sig-red"]}"></i>Side road's signal</span><span><i class="sq" style="background:${palette["road-major"]}"></i>Main road</span><span><i class="sq" style="border:1.5px dashed ${palette.accent};background:transparent"></i>Underpass</span><span>100 m bar bottom left</span>`
      : `<span><i style="background:${palette.rescue}"></i>Route · green wave</span><span><i style="background:${palette.siren}"></i>Siren</span><span><i style="background:${palette.none}"></i>No priority</span><span><i style="background:${palette.accent}"></i>Hospital</span><span><i style="background:${palette.warn}"></i>The call</span>`;
  }

  // ---- loop ----
  function frame() {
    hits = [];
    $("clock").textContent = C.clock(T0 + state.t); $("scrub").value = state.t;
    if (state.view === "plan") drawPlan(); else drawAmb();
    renderTimeline();
    if (state.view === "plan") drawQueue(); else drawTD();
  }
  function render() { if (state.view === "plan") renderPlan(); else renderAmb(); renderLegend(); frame(); }
  let prev = null;
  function loop(ts) {
    if (state.playing) {
      if (prev != null) state.t = Math.min(R.meta.t1 - 1, state.t + (ts - prev) / 1000 * 30);
      if (state.t >= R.meta.t1 - 1) setPlaying(false);
      frame();
    }
    prev = ts; requestAnimationFrame(loop);
  }
  function setPlaying(on) { state.playing = on; $("play").textContent = on ? "❚❚ Pause" : "▶ Play"; $("play").setAttribute("aria-label", on ? "Pause" : "Play"); }
  function setView(v) {
    state.view = v;
    for (const b of document.querySelectorAll("#views button")) b.setAttribute("aria-pressed", b.dataset.view === v);
    $("pane-plan").classList.toggle("on", v === "plan"); $("pane-amb").classList.toggle("on", v === "amb");
    $("pick").disabled = v !== "plan";
    if (v === "amb" && (state.t < CALLS[state.call].t0 || state.t > CALLS[state.call].t0 + 1500)) state.t = CALLS[state.call].t0 + 30;
    render();
  }
  function choose(sel, e, fn) { const el = e.target.closest(sel); if (!el) return; if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return; if (e.type === "keydown") e.preventDefault(); fn(el); }

  $("pick").innerHTML = J.map((j, i) => `<option value="${i}">${i + 1}. ${esc(j.name)}</option>`).join("");
  $("pick").onchange = (e) => { state.j = +e.target.value; render(); };
  $("views").onclick = (e) => { const b = e.target.closest("button[data-view]"); if (b) setView(b.dataset.view); };
  for (const ev of ["click", "keydown"]) {
    $("pane-plan").addEventListener(ev, (e) => choose("tr[data-fix]", e, (el) => { state.fix = el.dataset.fix; render(); }));
    $("pane-amb").addEventListener(ev, (e) => {
      choose("li[data-call]", e, (el) => { state.call = +el.dataset.call; state.t = CALLS[state.call].t0 + 30; render(); });
      choose("button[data-mode]", e, (el) => { state.mode = el.dataset.mode; render(); });
    });
  }
  $("play").onclick = () => { if (state.t >= R.meta.t1 - 1) state.t = 0; setPlaying(!state.playing); };
  $("scrub").max = R.meta.t1 - 1;
  $("scrub").oninput = () => { state.t = +$("scrub").value; frame(); };
  $("theme").onclick = () => { const d = document.documentElement.dataset.theme !== "light"; document.documentElement.dataset.theme = d ? "light" : "dark"; $("theme").textContent = d ? "Dark" : "Light"; readPalette(); try { localStorage.setItem("junction-planner", JSON.stringify({ theme: document.documentElement.dataset.theme })); } catch (e) { /* ignore */ } render(); };
  cv.addEventListener("mousemove", (e) => {
    const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, tip = $("tip");
    const h = hits.find((x) => Math.hypot(x.x - mx, x.y - my) < x.r);
    if (!h) { tip.style.display = "none"; return; }
    tip.innerHTML = esc(h.text); tip.style.display = "block"; tip.style.left = (mx + 14) + "px"; tip.style.top = (my + 14) + "px";
  });
  cv.addEventListener("mouseleave", () => { $("tip").style.display = "none"; });
  document.addEventListener("keydown", (e) => {
    if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
    if (e.code === "Space" && e.target.tagName !== "BUTTON" && !e.target.closest("[role=button]")) { e.preventDefault(); $("play").click(); }
    if (e.key === "ArrowRight") { state.t = Math.min(R.meta.t1 - 1, state.t + 30); frame(); }
    if (e.key === "ArrowLeft") { state.t = Math.max(0, state.t - 30); frame(); }
  });
  window.addEventListener("resize", () => { fit(); render(); });

  $("theme").textContent = document.documentElement.dataset.theme === "light" ? "Dark" : "Light";
  readPalette(); fit(); render(); requestAnimationFrame(loop);
  window.__junctions = { state, render, frame, setView, hits: () => hits, calls: CALLS };
})();

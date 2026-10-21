/* City Systems viewer: smog, underpass flooding and streetlights on Lahore's real roads,
 * Today against Connected, from window.CITY. Time runs in minutes; each view has its own clock
 * (smog from 17:30, the storm from 18:00, the night from 23:00).
 */
"use strict";

(function () {
  const R = window.CITY;
  const C = { ...TwinCore, clock: (t) => TwinCore.clock(((t % 86400) + 86400) % 86400) };      // the night runs past midnight
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  let P = {};
  function readPalette() {
    for (const k of ["bg", "panel", "panel-2", "text", "muted", "line", "accent", "floor-out", "water", "haze", "lamp", "lamp-dim", "road", "dark-road", "sig-red",
      "aqi1", "aqi2", "aqi3", "aqi4", "aqi5", "aqi6", "aqi7", "aqi8", "ok", "warn", "alert"]) P[k] = css("--" + k);
  }
  const RANK = { motorway: 7, trunk: 6, primary: 5, secondary: 4, tertiary: 3, unclassified: 2, residential: 1, living_street: 0, service: 0,
    trunk_link: 5, primary_link: 4, secondary_link: 3, tertiary_link: 2, motorway_link: 6 };
  const ROADS = R.roads.map(([ci, layer, flat]) => { const pts = []; for (let i = 0; i < flat.length; i += 2) pts.push([flat[i], flat[i + 1]]); return { rank: RANK[R.classes[ci]] || 0, layer, pts }; });
  const VIEW = {
    smog: { start: R.meta.smog_start, minutes: R.smog.minutes, step: 2 },
    rain: { start: R.meta.flood_start, minutes: R.flood.minutes + 15, step: 0.5 },
    night: { start: R.meta.night_start, minutes: R.lights.minutes, step: 1 },
  };
  const state = { view: "smog", mode: "connected", layer: "seen", t: { smog: 50, rain: 30, night: 120 }, playing: false };
  try { const s = JSON.parse(localStorage.getItem("city-twin") || "{}"); if (s.theme) document.documentElement.dataset.theme = s.theme; } catch (e) { /* storage blocked */ }

  // ---- canvas, camera, a cached base map ----
  const cv = $("plan"), ctx = cv.getContext("2d"), tl = $("tl"), tctx = tl.getContext("2d");
  let W = 0, H = 0, cam = null, base = null, hits = [];
  function fit() {
    const dpr = window.devicePixelRatio || 1;
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    tl.width = Math.round(tl.clientWidth * dpr); tl.height = Math.round(tl.clientHeight * dpr); tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const [x0, y0, x1, y1] = R.meta.bbox;
    if (!cam) cam = { x: (x0 + x1) / 2, y: (y0 + y1) / 2, z: Math.min(W / (x1 - x0), H / (y1 - y0)) * 0.96 };
    base = null;
  }
  const SX = (x) => (x - cam.x) * cam.z + W / 2, SY = (y) => (y - cam.y) * cam.z + H / 2;
  const WX = (sx) => (sx - W / 2) / cam.z + cam.x, WY = (sy) => (sy - H / 2) / cam.z + cam.y;
  function strokePts(c, pts) { c.beginPath(); pts.forEach(([x, y], k) => (k ? c.lineTo(SX(x), SY(y)) : c.moveTo(SX(x), SY(y)))); c.stroke(); }
  function baseMap() {
    if (base) return base;
    const dpr = window.devicePixelRatio || 1;
    base = document.createElement("canvas"); base.width = Math.round(W * dpr); base.height = Math.round(H * dpr);
    const c = base.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.fillStyle = P["floor-out"]; c.fillRect(0, 0, W, H); c.lineCap = "round"; c.lineJoin = "round";
    for (const r of ROADS) {
      c.strokeStyle = P.road; c.globalAlpha = r.layer < 0 ? 0.5 : 0.85;
      c.lineWidth = Math.max(0.6, (r.rank >= 4 ? 2.2 : r.rank >= 2 ? 1.2 : 0.7) * Math.min(3, cam.z * 2));
      strokePts(c, r.pts);
    }
    c.globalAlpha = 1;
    return base;
  }

  // ---- smog ----
  // US AQI bands for PM2.5; Lahore's evening sits almost wholly in the top one, so "Hazardous" is
  // split into three shades (250-400, 400-600, 600+) to keep the map readable
  const AQI = [[12, "aqi1", "Good"], [35.4, "aqi2", "Moderate"], [55.4, "aqi3", "Unhealthy for some"], [150.4, "aqi4", "Unhealthy"], [250.4, "aqi5", "Very unhealthy"],
    [400, "aqi6", "Hazardous 250–400"], [600, "aqi7", "Hazardous 400–600"], [1e9, "aqi8", "Hazardous 600+"]];
  const band = (v) => AQI.find(([hi]) => v <= hi);
  const S = R.smog, G = S.grid;
  const frameIdx = () => Math.min(S.frames.length - 1, Math.max(0, Math.round(state.t.smog / 2)));
  function smogField() {
    const k = frameIdx();
    if (state.layer === "truth") return S.truth[k];
    if (state.mode === "connected") return S.sensors_map[k];
    return null;                              // Today: the monitor's one number everywhere, drawn flat
  }
  function drawSmog() {
    const f = smogField(), k = frameIdx();
    const cw = G.cell * cam.z;
    ctx.globalAlpha = 0.5;
    if (f) {
      for (let j = 0; j < G.ny; j++) for (let i = 0; i < G.nx; i++) {
        // cells meet on whole pixels: an overlap doubles the translucent fill and draws a mesh
        const v = f[j * G.nx + i]; ctx.fillStyle = P[band(v)[1]];
        const xa = Math.round(SX(G.x0 + i * G.cell)), xb = Math.round(SX(G.x0 + (i + 1) * G.cell));
        const ya = Math.round(SY(G.y0 + j * G.cell)), yb = Math.round(SY(G.y0 + (j + 1) * G.cell));
        ctx.fillRect(Math.min(xa, xb), Math.min(ya, yb), Math.abs(xb - xa), Math.abs(yb - ya));
      }
    } else {
      ctx.fillStyle = P[band(S.official_map[k])[1]];
      ctx.fillRect(SX(G.x0), SY(G.y0), G.nx * cw, G.ny * cw);
    }
    ctx.globalAlpha = 1;
    // sensors: the official monitor (square) and, when connected, the low-cost network
    const rd = S.readings[k];
    if (state.mode === "connected") S.sensors.forEach((s, n) => {
      ctx.fillStyle = P.bg; ctx.beginPath(); ctx.arc(SX(s.x), SY(s.y), 5.5, 0, 7); ctx.fill();
      ctx.fillStyle = P[band(rd[n])[1]]; ctx.beginPath(); ctx.arc(SX(s.x), SY(s.y), 4, 0, 7); ctx.fill();
      hits.push({ x: SX(s.x), y: SY(s.y), r: 8, text: `${s.name} (${s.kind}) · ${rd[n]} µg/m³` });
    });
    const o = S.official;
    ctx.fillStyle = P.text; ctx.fillRect(SX(o.x) - 6, SY(o.y) - 6, 12, 12); ctx.fillStyle = P[band(S.official_map[k])[1]]; ctx.fillRect(SX(o.x) - 4, SY(o.y) - 4, 8, 8);
    hits.push({ x: SX(o.x), y: SY(o.y), r: 9, text: `Official monitor at ${o.name} · ${S.official_map[k]} µg/m³` });
    if (state.mode === "connected" && state.t.smog >= S.minutes - 15) {
      const [hx, hy] = S.hotspot; ctx.strokeStyle = P.text; ctx.lineWidth = 2; ctx.setLineDash([5, 4]);
      ctx.beginPath(); ctx.arc(SX(hx), SY(hy), 400 * cam.z, 0, 7); ctx.stroke(); ctx.setLineDash([]);
      hits.push({ x: SX(hx), y: SY(hy), r: Math.max(12, 400 * cam.z), text: "Hotspot the sensors found: its signals go adaptive to cut idling" });
    }
  }
  function renderSmog() {
    const k = frameIdx(), m = S.metrics, tru = S.truth[k];
    const mean = Math.round(tru.reduce((a, b) => a + b, 0) / tru.length), worst = Math.max(...tru);
    $("k1").textContent = mean; $("k1l").textContent = "µg/m³ PM2.5, area mean now (truth)";
    $("k2").textContent = worst; $("k2l").textContent = "worst street cell now";
    $("k3").textContent = state.mode === "connected" ? m.map_error_sensors : m.map_error_today; $("k3l").textContent = "µg/m³ off near roads at the peak (" + (state.mode === "connected" ? "sensors" : "one monitor") + ")";
    let h = `<h3>A November evening</h3><p class="note">PM2.5 at street level on a 100 m grid: the regional haze under a closing evening inversion, plus what the traffic module's own vehicles emit — exhaust and idling in queues — spread from each road. Traffic is scaled to 36% of the near-road mean at the peak, the last published apportionment for Lahore (2010 data). ${S.trips.toLocaleString("en")} trips in the hour.</p>`;
    h += `<table class="cmp"><tr><th></th><th>Today</th><th>Connected</th></tr>
      <tr><td>Sensors</td><td class="num">1 official</td><td class="num">1 + 25 low-cost</td></tr>
      <tr><td>Map error near roads, µg/m³</td><td class="num">${m.map_error_today}</td><td class="num best">${m.map_error_sensors}</td></tr>
      <tr><td>Hotspot found</td><td class="num">no</td><td class="num best">${m.hotspot_found_m} m away</td></tr>
      <tr><td>Where it acted, µg/m³ at the peak</td><td class="num">${m.hotspot_before}</td><td class="num best">${m.hotspot_after}</td></tr>
      <tr><td>At the real hotspot</td><td class="num">${m.true_hotspot_before}</td><td class="num best">${m.true_hotspot_after}</td></tr></table>`;
    h += `<p class="note">Today the city has one official monitor, so its map is one number. Connected adds 25 low-cost sensors — 15 at schools, hospitals and colleges, 10 on main-road junction poles — each with its own gain error and noise, corrected against the one beside the monitor; the map is a regression of their readings on the traffic the signals' loop detectors count. Where it finds the worst hotspot, ${m.adaptive_signals} signals within 400 m go adaptive, cutting idling; the same trips are run again. The area mean at the peak is ${m.area_mean_peak} µg/m³ — Hazardous on the US AQI scale, as Lahore's winter evenings are.</p>`;
    h += `<h3>The sensors now</h3><ul class="sensors">` + S.sensors.map((s, n) => ({ s, v: S.readings[k][n] })).sort((a, b) => b.v - a.v).map(({ s, v }) => `<li title="${esc(s.name)}"><span><i style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;background:var(--${band(v)[1]})"></i><bdi>${esc(s.name)}</bdi></span><b class="num">${v}</b></li>`).join("") + `</ul>`;
    $("pane").innerHTML = h;
  }

  // ---- rain ----
  const F = R.flood;
  const fm = () => F.modes[state.mode];
  const depthNow = (name) => { const d = fm().depth[name], i = Math.min(d.length - 1, Math.max(0, Math.round(state.t.rain * 2))); return d[i]; };
  const closedNow = (name) => (fm().closed[name] || []).some(([a, b]) => a <= state.t.rain * 60 && (b == null || state.t.rain * 60 < b));
  // an underpass's circle grows with its water; on a small map (a phone) the circles shrink with it
  const upR = (d) => (8 + Math.min(18, d * 30)) * Math.min(1, Math.max(0.5, Math.min(W, H) / 700));
  function drawRain() {
    const labels = [];
    for (const u of F.underpasses) {
      const d = depthNow(u.name), x = SX(u.x), y = SY(u.y), r = upR(d);
      ctx.fillStyle = P.water; ctx.globalAlpha = 0.25 + Math.min(0.6, d); ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill(); ctx.globalAlpha = 1;
      ctx.strokeStyle = d >= 0.3 ? P["sig-red"] : P.water; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.stroke();
      if (closedNow(u.name)) { ctx.strokeStyle = P.text; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(x - 9, y); ctx.lineTo(x + 9, y); ctx.stroke(); }
      const stuck = fm().stranded_events.filter(([t, n]) => n === u.name && t <= state.t.rain * 60).length;
      if (stuck) labels.push({ x, y, r, text: `${stuck} stalled` });
      hits.push({ x, y, r: r + 4, text: `${u.name} · ${d.toFixed(2)} m of water${closedNow(u.name) ? " · gate closed" : ""}${stuck ? ` · ${stuck} stalled` : ""}` });
    }
    // underpasses sit close together: put each label above, below, right or left of its circle,
    // wherever it clears the circles and the labels already placed
    ctx.font = "700 11px Segoe UI, system-ui"; ctx.textAlign = "left"; ctx.fillStyle = P["sig-red"];
    const boxes = [], circles = F.underpasses.map((u) => ({ x: SX(u.x), y: SY(u.y), r: upR(depthNow(u.name)) }));
    const hit = (b) => boxes.some((o) => b.x < o.x + o.w && o.x < b.x + b.w && b.y < o.y + o.h && o.y < b.y + b.h)
      || circles.some((c) => Math.max(b.x, Math.min(c.x, b.x + b.w)) - c.x <= c.r && Math.hypot(Math.max(b.x, Math.min(c.x, b.x + b.w)) - c.x, Math.max(b.y, Math.min(c.y, b.y + b.h)) - c.y) < c.r);
    for (const l of labels) {
      const w = ctx.measureText(l.text).width, h = 12;
      const spots = [[l.x - w / 2, l.y - l.r - 4 - h], [l.x - w / 2, l.y + l.r + 4], [l.x + l.r + 4, l.y - h / 2], [l.x - l.r - 4 - w, l.y - h / 2]];
      const [bx, by] = spots.find(([sx, sy]) => !hit({ x: sx, y: sy, w, h })) || spots[0];
      boxes.push({ x: bx, y: by, w, h }); ctx.fillText(l.text, bx, by + h - 2);
    }
  }
  function renderRain() {
    const t = state.t.rain * 60, deep = Math.max(...F.underpasses.map((u) => depthNow(u.name)));
    const stuck = fm().stranded_events.filter(([s]) => s <= t).length, closed = F.underpasses.filter((u) => closedNow(u.name)).length;
    $("k1").textContent = deep.toFixed(2) + " m"; $("k1l").textContent = "deepest water now";
    $("k2").textContent = stuck; $("k2l").textContent = "vehicles stalled so far";
    $("k3").textContent = closed; $("k3l").textContent = "underpasses closed now";
    const cut = t >= F.power_cut[0] && t < F.power_cut[1];
    let h = `<h3>A monsoon storm${cut ? ' · <span style="color:var(--sig-red)">power cut</span>' : ""}</h3>`;
    h += `<ul class="gauges">` + F.underpasses.map((u) => { const d = depthNow(u.name); return `<li><span>${esc(u.name)}${closedNow(u.name) ? ' <b style="color:var(--sig-red)">closed</b>' : ""}</span><span class="bar" title="red marks: motorcycles stall at 0.30 m, cars at 0.45 m"><b style="width:${Math.min(100, d / 0.6 * 100)}%"></b><s style="left:${0.3 / 0.6 * 100}%"></s><s style="left:${0.45 / 0.6 * 100}%"></s></span><span class="num">${d.toFixed(2)} m</span></li>`; }).join("") + `</ul>`;
    h += `<div class="key"><span><i style="background:var(--water)"></i>water depth</span><span><i style="background:var(--muted)"></i>rain, mm/h</span><span><i style="background:rgba(239,68,68,.35)"></i>power cut</span></div><canvas class="chart" id="c-rain" style="height:150px"></canvas>`;
    const a = F.modes.today, b = F.modes.connected;
    h += `<table class="cmp"><tr><th></th><th>Today</th><th>Connected</th></tr>
      <tr><td>Deepest water, m</td><td class="num">${Math.max(...Object.values(a.max_depth))}</td><td class="num best">${Math.max(...Object.values(b.max_depth))}</td></tr>
      <tr><td>Vehicles stalled in water</td><td class="num">${a.stranded}</td><td class="num best">${b.stranded}</td></tr>
      <tr><td>Gridlocked (still 5+ min)</td><td class="num">${a.gridlocked}</td><td class="num best">${b.gridlocked}</td></tr>
      <tr><td>Rerouted round a closed underpass</td><td class="num">${a.rerouted}</td><td class="num">${b.rerouted}</td></tr>
      <tr><td>Trips finished</td><td class="num">${a.completed.toLocaleString("en")}</td><td class="num best">${b.completed.toLocaleString("en")}</td></tr>
      <tr><td>Median delay, s</td><td class="num">${a.delay_median_s}</td><td class="num">${b.delay_median_s}</td></tr></table>`;
    h += `<p class="note">Each real underpass is a basin: rain on the dip and on 2 ha of streets that drain into it, pumped out at 0.25 m³/s while there is power. LESCO's feeder trips from 18:25 to 19:05; Today someone gets a generator running 30 minutes in, Connected's level sensor starts it in 2. Motorcycles and rickshaws stall at 0.30 m, cars at 0.45 m. Connected closes the gate at 0.15 m and routes traffic over the surface. Storm, pumps and catchment are assumptions (Lahore's reports give daily totals, not pump capacities); most underpasses here are mapped short, so five share one dip size and one depth curve.</p>`;
    $("pane").innerHTML = h; drawRainChart();
  }
  function drawRainChart() {
    const c = $("c-rain"); if (!c) return;
    const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight; c.width = w * dpr; c.height = h * dpr;
    const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = F.rain.length, L = 40, B = 16, xs = (i) => L + (w - L - 4) * i / (n - 1), ys = (v) => 4 + (h - B - 4) * (1 - v / 0.6);
    g.fillStyle = "rgba(239,68,68,.15)"; g.fillRect(xs(F.power_cut[0] / 30), 4, xs(F.power_cut[1] / 30) - xs(F.power_cut[0] / 30), h - B - 4);
    g.fillStyle = P.muted; g.globalAlpha = 0.35; F.rain.forEach((r, i) => { const bh = (h - B - 8) * r / 80; g.fillRect(xs(i), h - B - bh, Math.max(1, (w - L) / n), bh); }); g.globalAlpha = 1;
    for (const [v, col] of [[0.3, P["sig-red"]], [0.45, P["sig-red"]]]) { g.strokeStyle = col; g.setLineDash([3, 3]); g.beginPath(); g.moveTo(L, ys(v)); g.lineTo(w - 4, ys(v)); g.stroke(); g.setLineDash([]); }
    g.strokeStyle = P.water; g.lineWidth = 1.5;
    for (const u of F.underpasses) { const d = fm().depth[u.name]; g.beginPath(); d.forEach((v, i) => (i ? g.lineTo(xs(i), ys(Math.min(0.6, v))) : g.moveTo(xs(i), ys(v)))); g.stroke(); }
    g.fillStyle = P.muted; g.font = "10.5px Segoe UI, system-ui"; g.textAlign = "right"; for (const v of [0, 0.3, 0.6]) g.fillText(v.toFixed(1) + " m", L - 3, Math.max(11, ys(v) + 3));
    for (let m = 0; m <= n / 2; m += 15) { g.textAlign = m === 0 ? "left" : m + 15 > n / 2 ? "right" : "center"; g.fillText(C.clock(R.meta.flood_start + m * 60), xs(Math.min(n - 1, m * 2)), h - 3); }
    const x = xs(state.t.rain * 2); g.strokeStyle = P.text; g.globalAlpha = 0.5; g.beginPath(); g.moveTo(x, 4); g.lineTo(x, h - B); g.stroke(); g.globalAlpha = 1;
  }

  // ---- night ----
  const Lt = R.lights;
  const levelAt = (ch, m) => { const i = C.bisectRight(ch, m, (e) => e[0]) - 1; return i >= 0 ? ch[i][1] : 1; };
  function drawNight() {
    const m = Math.floor(state.t.night), mode = Lt.modes[state.mode];
    // the shed feeder, during its hour
    if (m * 60 >= Lt.outage[0] && m * 60 < Lt.outage[1]) { ctx.fillStyle = "rgba(0,0,0,.35)"; ctx.fillRect(SX(Lt.east_of), 0, W, H); }
    ctx.lineCap = "round";
    Lt.roads.forEach((ri, n) => {
      const lv = levelAt(mode.changes[n], m), r = ROADS[ri];
      ctx.strokeStyle = lv === 0 ? P["dark-road"] : lv < 1 ? P["lamp-dim"] : P.lamp; ctx.globalAlpha = lv === 0 ? 0.9 : 0.55 + 0.45 * lv;
      ctx.lineWidth = Math.max(0.8, (Lt.main[n] ? 2.4 : 1.1) * Math.min(3, cam.z * 2)); strokePts(ctx, r.pts);
    });
    ctx.globalAlpha = 1;
    if (state.mode === "connected") Lt.fails.forEach(([ri, fm_], n) => { if (fm_ > m) return;
      const p = ROADS[ri].pts[Math.floor(ROADS[ri].pts.length / 2)]; ctx.fillStyle = P["sig-red"]; ctx.beginPath(); ctx.arc(SX(p[0]), SY(p[1]), 3.5, 0, 7); ctx.fill();
      hits.push({ x: SX(p[0]), y: SY(p[1]), r: 7, text: `Failed lamp on ${(Lt.fail_names || [])[n] || "this road"} since ${C.clock(R.meta.night_start + fm_ * 60)}: it reported itself` });
    });
  }
  function renderNight() {
    const m = Math.floor(state.t.night), mode = Lt.modes[state.mode], kwSoFar = mode.kw.slice(0, m + 1).reduce((a, b) => a + b, 0) / 60;
    $("k1").textContent = Math.round(mode.kw[m]) + " kW"; $("k1l").textContent = "streetlights drawing now";
    $("k2").textContent = Math.round(kwSoFar).toLocaleString("en"); $("k2l").textContent = "kWh since 23:00";
    $("k3").textContent = state.mode === "connected" ? Lt.fails.filter(([, f]) => f <= m).length : 0; $("k3l").textContent = "failed lamps known";
    const a = Lt.modes.today, b = Lt.modes.connected;
    let h = `<h3>A night, 23:00–05:00</h3><div class="key"><span><i style="background:var(--lamp)"></i>full</span><span><i style="background:var(--lamp-dim)"></i>dimmed to 30%</span><span><i style="background:var(--dark-road)"></i>dark</span><span><i style="background:var(--sig-red)"></i>failed lamp</span></div><canvas class="chart" id="c-night" style="height:130px"></canvas>`;
    h += `<table class="cmp"><tr><th></th><th>Today</th><th>Connected</th></tr>
      <tr><td>Energy, kWh</td><td class="num">${a.kwh.toLocaleString("en")}</td><td class="num best">${b.kwh.toLocaleString("en")}</td></tr>
      <tr><td>Busy road-minutes in the dark</td><td class="num">${a.busy_road_minutes_dark.toLocaleString("en")}</td><td class="num best">${b.busy_road_minutes_dark.toLocaleString("en")}</td></tr>
      <tr><td>Failed lamps known by morning</td><td class="num">${a.failures_known_by_morning} of ${Lt.fails.length}</td><td class="num best">${b.failures_known_by_morning} of ${Lt.fails.length}</td></tr></table>`;
    h += `<p class="note">${Lt.lamp_count.toLocaleString("en")} LED lamps on every road from residential up — every 35 m on main roads (150 W), every 40 m on smaller ones (70 W). Today they burn at full power all night and go dark in the load-shedding hour (01:00–02:00 on the eastern feeder); a failed lamp waits for a complaint. Connected dims a road to 30% unless a vehicle is on it or on a road next to it within the last minute — traffic from the simulation, ${Lt.trips.toLocaleString("en")} trips through the night — keeps main roads lit on a battery through the cut, and every lamp reports a failure. Field studies of adaptive dimming: 27–42% saved over static lighting. Wattage, spacing, failure rate and the outage are assumptions.</p>`;
    $("pane").innerHTML = h; drawNightChart();
  }
  function drawNightChart() {
    const c = $("c-night"); if (!c) return;
    const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight; c.width = w * dpr; c.height = h * dpr;
    const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = Lt.minutes, L = 46, B = 16, max = Math.max(...Lt.modes.today.kw, 1) * 1.1;
    const xs = (i) => L + (w - L - 4) * i / (n - 1), ys = (v) => 4 + (h - B - 4) * (1 - v / max);
    g.fillStyle = "rgba(239,68,68,.15)"; g.fillRect(xs(Lt.outage[0] / 60), 4, xs(Lt.outage[1] / 60) - xs(Lt.outage[0] / 60), h - B - 4);
    for (const [k, col, wd] of [["today", P.muted, 1.2], ["connected", P.lamp, 2]]) { g.strokeStyle = col; g.lineWidth = wd; g.beginPath(); Lt.modes[k].kw.forEach((v, i) => (i ? g.lineTo(xs(i), ys(v)) : g.moveTo(xs(i), ys(v)))); g.stroke(); }
    g.fillStyle = P.muted; g.font = "10.5px Segoe UI, system-ui"; g.textAlign = "right"; for (const v of [0, Math.round(max / 2)]) g.fillText(v + " kW", L - 3, Math.max(11, ys(v) + 3));
    for (let m = 0; m <= n; m += 60) { g.textAlign = m === 0 ? "left" : m + 60 > n ? "right" : "center"; g.fillText(C.clock(R.meta.night_start + m * 60), xs(Math.min(n - 1, m)), h - 3); }
    const x = xs(state.t.night); g.strokeStyle = P.text; g.globalAlpha = 0.5; g.beginPath(); g.moveTo(x, 4); g.lineTo(x, h - B); g.stroke(); g.globalAlpha = 1;
  }

  // ---- frame ----
  function draw() {
    hits = [];
    ctx.drawImage(baseMap(), 0, 0, W, H);
    if (state.view === "smog") drawSmog(); else if (state.view === "rain") drawRain(); else drawNight();
  }
  function renderPanel() { if (state.view === "smog") renderSmog(); else if (state.view === "rain") renderRain(); else renderNight(); }
  function renderTimeline() {
    const w = tl.clientWidth, h = tl.clientHeight, V = VIEW[state.view];
    tctx.clearRect(0, 0, w, h);
    tctx.fillStyle = P.accent; tctx.fillRect(w * state.t[state.view] / V.minutes - 1, 0, 2, h);
    const out = [], every = V.minutes > 120 ? 60 : 15; for (let m = 0; m <= V.minutes; m += every) out.push(`<span>${C.clock(V.start + m * 60)}</span>`);
    $("ticks").innerHTML = out.join("");
    $("scrub").max = V.minutes; $("scrub").step = V.step; $("scrub").value = state.t[state.view];
  }
  let lastPanel = 0;
  function frame(force) {
    const V = VIEW[state.view];
    $("clock").textContent = C.clock(V.start + state.t[state.view] * 60);
    $("scrub").setAttribute("aria-valuetext", $("clock").textContent);         // read the time, not the minute count
    draw(); renderTimeline();
    const now = performance.now();
    if (force || now - lastPanel > 400) { lastPanel = now; renderPanel(); }
  }
  function renderLegend() {
    const L = { smog: AQI.map(([hi, k, n]) => `<span><i class="sq" style="background:${P[k]}"></i>${n}</span>`).join("") + `<span>■ official monitor · ● low-cost sensor</span>`,
      rain: `<span><i style="background:${P.water}"></i>water in an underpass</span><span>— gate closed</span><span><i style="background:${P["sig-red"]}"></i>over 0.30 m: motorcycles stall</span>`,
      night: `<span><i class="sq" style="background:${P.lamp}"></i>full</span><span><i class="sq" style="background:${P["lamp-dim"]}"></i>dimmed</span><span><i class="sq" style="background:${P["dark-road"]}"></i>dark</span><span>shaded: the feeder in load-shedding</span>` };
    $("legend").innerHTML = L[state.view];
    $("layers").style.display = state.view === "smog" ? "" : "none";
  }
  let prev = null;
  function loop(ts) {
    if (state.playing) {
      const V = VIEW[state.view], rate = { smog: 1, rain: 1, night: 6 }[state.view];
      if (prev != null) state.t[state.view] = Math.min(V.minutes, state.t[state.view] + (ts - prev) / 1000 * rate);
      if (state.t[state.view] >= V.minutes) setPlaying(false);
      frame(false);
    }
    prev = ts; requestAnimationFrame(loop);
  }
  function setPlaying(on) { state.playing = on; $("play").textContent = on ? "❚❚ Pause" : "▶ Play"; $("play").setAttribute("aria-label", on ? "Pause" : "Play"); }
  function choose(id, key) {
    $(id).onclick = (e) => { const b = e.target.closest("button"); if (!b) return; state[key] = b.dataset[key]; for (const x of $(id).querySelectorAll("button")) x.setAttribute("aria-pressed", x === b); if (key === "view") renderLegend(); frame(true); };
  }
  choose("views", "view"); choose("modes", "mode"); choose("layers", "layer");
  $("play").onclick = () => { if (state.t[state.view] >= VIEW[state.view].minutes) state.t[state.view] = 0; setPlaying(!state.playing); };
  $("scrub").oninput = () => { state.t[state.view] = +$("scrub").value; frame(true); };
  $("theme").onclick = () => { const d = document.documentElement.dataset.theme !== "light"; document.documentElement.dataset.theme = d ? "light" : "dark"; $("theme").textContent = d ? "Dark" : "Light"; readPalette(); base = null; renderLegend(); try { localStorage.setItem("city-twin", JSON.stringify({ theme: document.documentElement.dataset.theme })); } catch (e) { /* ignore */ } frame(true); };
  cv.addEventListener("mousemove", (e) => {
    const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, tip = $("tip");
    const hh = hits.filter((x) => Math.hypot(x.x - mx, x.y - my) < x.r).sort((a, b) => a.r - b.r)[0];
    if (!hh) { tip.style.display = "none"; return; }
    tip.innerHTML = esc(hh.text); tip.style.display = "block"; tip.style.left = (mx + 14) + "px"; tip.style.top = (my + 14) + "px";
  });
  cv.addEventListener("mouseleave", () => { $("tip").style.display = "none"; });
  cv.addEventListener("wheel", (e) => { e.preventDefault(); const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, wx = WX(mx), wy = WY(my);
    cam.z = Math.max(0.03, Math.min(6, cam.z * (e.deltaY < 0 ? 1.2 : 1 / 1.2))); cam.x = wx - (mx - W / 2) / cam.z; cam.y = wy - (my - H / 2) / cam.z; base = null; frame(false); }, { passive: false });
  let drag = null;
  cv.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y }; cv.setPointerCapture(e.pointerId); });
  cv.addEventListener("pointermove", (e) => { if (!drag) return; cam.x = drag.cx - (e.clientX - drag.x) / cam.z; cam.y = drag.cy - (e.clientY - drag.y) / cam.z; base = null; frame(false); });
  cv.addEventListener("pointerup", () => { drag = null; });
  document.addEventListener("keydown", (e) => {
    if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
    if (e.code === "Space" && e.target.tagName !== "BUTTON") { e.preventDefault(); $("play").click(); }
    const V = VIEW[state.view];
    if (e.key === "ArrowRight") { state.t[state.view] = Math.min(V.minutes, state.t[state.view] + V.step * 2); frame(true); }
    if (e.key === "ArrowLeft") { state.t[state.view] = Math.max(0, state.t[state.view] - V.step * 2); frame(true); }
  });
  window.addEventListener("resize", () => { fit(); frame(true); });

  $("theme").textContent = document.documentElement.dataset.theme === "light" ? "Dark" : "Light";
  readPalette(); fit(); renderLegend(); frame(true); requestAnimationFrame(loop);
  window.__city = { state, frame, hits: () => hits };
})();

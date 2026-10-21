/* Traffic Twin viewer: real Lahore roads from OpenStreetMap, a peak hour replayed
 * from window.TRAFFIC, with the real shops and amenities people stop at. The map is cut into tiles and streams in around
 * the camera like a game map; "Follow a vehicle" rides along with one, and the
 * minimap shows where it is. Vehicles drive on the left, as in Pakistan.
 */
"use strict";

(function () {
  const R = window.TRAFFIC;
  const C = TwinCore;
  const T0 = R.meta.start != null ? R.meta.start : 7.5 * 3600;     // 17:30 for the evening, 07:30 for the morning
  const PERIOD = R.meta.period || "evening";
  const POIS = (R.pois || []).map(([x, y, k, name], i) => ({ i, x, y, kind: (R.poi_kinds || [])[k], name }));
  // what each kind of place is, for the map and its key
  const POI_GROUP = { shop: "shop", mall: "shop", marketplace: "shop", supermarket: "shop", bakery: "food",
    restaurant: "food", fast_food: "food", cafe: "food", pharmacy: "health", clinic: "health", hospital: "health",
    school: "school", college: "school", university: "school", bank: "bank", fuel: "fuel", place_of_worship: "mosque" };
  const POI_NAMES = { shop: "Shops and markets", food: "Food", health: "Pharmacy, clinic, hospital", school: "School, college, university", bank: "Bank", fuel: "Fuel", mosque: "Mosque" };
  const POI_COL = { shop: "#ec4899", food: "#f97316", health: "#ef4444", school: "#3b82f6", bank: "#14b8a6", fuel: "#eab308", mosque: "#a855f7" };
  const KIND_TITLE = { fuel: "fuel station", place_of_worship: "mosque", fast_food: "fast food", marketplace: "market" };
  const KIND_LABEL = (k) => KIND_TITLE[k] || (k || "").replace("_", " ");
  const LANE_W = 3.2;
  const KIND_NAMES = { motorcycle: "Motorcycle", car: "Car", rickshaw: "Rickshaw", bus: "Bus / van" };
  const KIND_SIZE = { motorcycle: [2.0, 0.8], car: [4.5, 1.8], rickshaw: [2.8, 1.4], bus: [11, 2.5] };
  const MODE_NAMES = { fixed: "Fixed signals", adaptive: "Adaptive signals" };
  const RANK = { motorway: 7, trunk: 6, primary: 5, secondary: 4, tertiary: 3, unclassified: 2, residential: 1,
                 living_street: 0, service: 0, trunk_link: 5, primary_link: 4, secondary_link: 3, tertiary_link: 2, motorway_link: 6 };

  // ---- roads and links ----
  const roads = R.roads.map(([ci, lanes, oneway, layer, ni, bridge, tunnel, flat]) => {
    const pts = []; for (let i = 0; i < flat.length; i += 2) pts.push([flat[i], flat[i + 1]]);
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [x, y] of pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    const cls = R.classes[ci];
    return { cls, rank: RANK[cls] || 0, lanes, oneway: !!oneway, layer, name: ni >= 0 ? R.names[ni] : "", bridge: !!bridge, tunnel: !!tunnel, pts, box: [x0, y0, x1, y1] };
  });
  const segLen = (pts) => { let L = 0; for (let i = 1; i < pts.length; i++) L += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); return L; };
  const links = R.links.map(([ri, back, lanes]) => {
    const r = roads[ri], pts = back ? r.pts.slice().reverse() : r.pts;
    return { road: ri, pts, lanes, len: segLen(pts), oneway: r.oneway };
  });
  const tileKeys = Object.keys(R.tiles);
  const TILE = R.meta.tile;

  // ---- vehicles (decoded lazily per rule set) ----
  const decoded = {}, visitsOf = {};
  function stopAt(v, t) { for (const s of v.stops) if (s[0] <= t && (s[1] == null ? t <= s[0] + 1 : t < s[1])) return s; return null; }
  function vehiclesOf(mode) {
    if (decoded[mode]) return decoded[mode];
    const out = R.modes[mode].vehicles.map(([ki, t0, ts, done, deltas, lanes, stops], i) => {
      const route = R.routes[i];
      const cum = new Array(deltas.length); let acc = 0;
      for (let k = 0; k < deltas.length; k++) { acc += deltas[k]; cum[k] = acc; }          // metres along the route
      const prefix = [0]; for (const lid of route) prefix.push(prefix[prefix.length - 1] + links[lid].len);
      const purpose = R.trip_purpose ? R.purposes[R.trip_purpose[i]] : "";
      return { i, kind: R.kinds[ki], t0, ts, done, route, cum, lanes, prefix, stops: stops || [], purpose };
    });
    decoded[mode] = out;
    // visits per place over the hour
    const visits = new Array(POIS.length).fill(0);
    for (const v of out) for (const s of v.stops) if (s[3] >= 0) visits[s[3]]++;
    visitsOf[mode] = visits;
    return out;
  }
  function vehAt(v, t) {
    if (!v.cum.length || t < v.ts) return null;
    if (v.done != null && t >= v.done) return null;
    const f = (t - v.ts) / R.meta.sample, k = Math.floor(f);
    if (k >= v.cum.length) return null;
    const d = k + 1 < v.cum.length ? v.cum[k] + (v.cum[k + 1] - v.cum[k]) * (f - k) : v.cum[k];
    let j = C.bisectRight(v.prefix, d, (x) => x) - 1;
    j = Math.max(0, Math.min(v.route.length - 1, j));
    const lk = links[v.route[j]];
    let along = d - v.prefix[j];
    // walk the link's polyline
    let x = lk.pts[0][0], y = lk.pts[0][1], hx = 1, hy = 0;
    for (let s = 1; s < lk.pts.length; s++) {
      const [ax, ay] = lk.pts[s - 1], [bx, by] = lk.pts[s], L = Math.hypot(bx - ax, by - ay) || 1e-6;
      hx = (bx - ax) / L; hy = (by - ay) / L;
      if (along <= L || s === lk.pts.length - 1) { const u = Math.min(along, L); x = ax + hx * u; y = ay + hy * u; break; }
      along -= L;
    }
    // lane: Pakistan drives on the left, so lanes sit to the left of the centre line
    let lane = 0; for (const [kk, ln] of v.lanes) { if (kk <= k) lane = ln; else break; }
    // lane -1: pulled off the road beside the kerb, at the shop's parking
    const parked = lane < 0, ln = parked ? lk.lanes - 1 + 1.4 : lane;
    const off = lk.oneway ? (ln + 0.5 - lk.lanes / 2) * LANE_W : (ln + 0.5) * LANE_W;
    x += hy * off; y += -hx * off;
    return { x, y, hx, hy, link: v.route[j], speed: parked ? 0 : k + 1 < v.cum.length ? (v.cum[k + 1] - v.cum[k]) / R.meta.sample : 0, driven: d, parked };
  }

  // ---- state ----
  const state = { t: 25 * 60, mode: "adaptive", playing: false, speed: 15, follow: null, sel: null, cam: { x: 0, y: 0, z: 0.2 } };
  try {
    const saved = JSON.parse(localStorage.getItem("traffic-twin") || "{}");
    if (saved.theme) document.documentElement.dataset.theme = saved.theme;
    if (saved.mode && R.modes[saved.mode]) state.mode = saved.mode;
  } catch (e) { /* storage blocked */ }
  const $ = (id) => document.getElementById(id);
  const cv = $("plan"), ctx = cv.getContext("2d");
  const mini = $("mini"), mctx = mini.getContext("2d");
  const tl = $("tl"), tctx = tl.getContext("2d");
  $("scrub").max = R.meta.t1 - 1;
  let palette = {};
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  function readPalette() {
    for (const k of ["bg", "panel", "panel-2", "text", "muted", "line", "accent", "floor", "floor-out", "road-major", "road-mid", "road-minor", "road-edge", "road-tunnel",
      "sig-red", "sig-amber", "sig-green", "veh-moto", "veh-car", "veh-rick", "veh-bus", "ok", "alert", "warn"]) palette[k] = css("--" + k);
  }
  const KCOL = () => ({ motorcycle: palette["veh-moto"], car: palette["veh-car"], rickshaw: palette["veh-rick"], bus: palette["veh-bus"] });
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ---- camera ----
  let W = 0, H = 0;
  function fitCanvas() {
    const dpr = window.devicePixelRatio || 1;
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    mini.width = Math.round(mini.clientWidth * dpr); mini.height = Math.round(mini.clientHeight * dpr); mctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    tl.width = Math.round(tl.clientWidth * dpr); tl.height = Math.round(tl.clientHeight * dpr); tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    miniCache = null;
  }
  function fitAll() {
    const [x0, y0, x1, y1] = R.meta.bbox;
    state.cam = { x: (x0 + x1) / 2, y: (y0 + y1) / 2, z: Math.min(W / (x1 - x0), H / (y1 - y0)) * 0.95 };
  }
  const SX = (x) => (x - state.cam.x) * state.cam.z + W / 2;
  const SY = (y) => (y - state.cam.y) * state.cam.z + H / 2;
  const WX = (sx) => (sx - W / 2) / state.cam.z + state.cam.x;
  const WY = (sy) => (sy - H / 2) / state.cam.z + state.cam.y;

  // ---- tile streaming ----
  const loadedAt = {};                // tile key -> when it was streamed in
  const lastSeen = {};                // tile key -> when it was last in view
  function visibleTiles() {
    const m = 120 / state.cam.z;      // a margin of a few metres around the screen
    const x0 = WX(0) - m, x1 = WX(W) + m, y0 = WY(0) - m, y1 = WY(H) + m;
    const out = [];
    for (let i = Math.floor(x0 / TILE); i <= Math.floor(x1 / TILE); i++) for (let j = Math.floor(y0 / TILE); j <= Math.floor(y1 / TILE); j++) {
      const k = i + "," + j; if (R.tiles[k]) out.push(k);
    }
    return out;
  }

  // ---- drawing ----
  let hits = [];
  function roadWidth(r) { return Math.max(r.rank >= 3 ? 1.6 : 0.9, (r.oneway ? r.lanes : 2 * r.lanes) * LANE_W * state.cam.z); }
  function roadColour(r) { return r.rank >= 4 ? palette["road-major"] : r.rank >= 2 ? palette["road-mid"] : palette["road-minor"]; }
  function strokeRoad(r) { ctx.beginPath(); r.pts.forEach(([x, y], k) => (k ? ctx.lineTo(SX(x), SY(y)) : ctx.moveTo(SX(x), SY(y)))); ctx.stroke(); }

  function draw() {
    ctx.fillStyle = palette["floor-out"]; ctx.fillRect(0, 0, W, H);
    const now = performance.now(), z = state.cam.z;
    const tiles = visibleTiles();
    const alpha = {};          // road index -> fade-in alpha
    let loading = 0;
    // like a game map, tiles left behind are released after a couple of seconds out of view
    // and stream back in when the camera returns
    const inView = new Set(tiles);
    for (const k of Object.keys(loadedAt)) {
      if (inView.has(k)) lastSeen[k] = now;
      else if (now - (lastSeen[k] || 0) > 2000) { delete loadedAt[k]; delete lastSeen[k]; }
    }
    for (const k of tiles) {
      if (!(k in loadedAt)) { loadedAt[k] = now; lastSeen[k] = now; }
      const a = Math.min(1, (now - loadedAt[k]) / 450);
      if (a < 1) {
        loading++;
        const [i, j] = k.split(",").map(Number);
        ctx.fillStyle = `rgba(127,140,165,${0.06 * (1 - a)})`;
        ctx.fillRect(SX(i * TILE), SY(j * TILE), TILE * z, TILE * z);
      }
      for (const ri of R.tiles[k]) alpha[ri] = Math.max(alpha[ri] || 0, a);
    }
    $("loadtag").textContent = `${tiles.length} map tiles${loading ? ` · loading ${loading}` : ""} · ${(1 / z).toFixed(1)} m per pixel`;
    const idx = Object.keys(alpha).map(Number);
    // order: underpasses, then ground roads by size, then flyovers on top
    idx.sort((p, q) => (roads[p].layer - roads[q].layer) || (roads[p].rank - roads[q].rank));
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    for (const pass of ["edge", "fill"]) {
      for (const ri of idx) {
        const r = roads[ri], w = roadWidth(r);
        ctx.globalAlpha = alpha[ri] * (r.layer < 0 ? 0.55 : 1);
        if (pass === "edge") {
          if (r.layer > 0) { ctx.strokeStyle = "rgba(0,0,0,0.35)"; ctx.lineWidth = w + 6; ctx.save(); ctx.translate(3, 4); strokeRoad(r); ctx.restore(); }
          // a flyover's deck gets a light outline so it reads as above the roads it crosses
          ctx.strokeStyle = r.layer < 0 ? palette["road-tunnel"] : r.layer > 0 ? palette.text : palette["road-edge"];
          ctx.lineWidth = w + (r.layer > 0 ? 4 : 2);
          if (r.layer < 0) ctx.setLineDash([6, 5]);
          strokeRoad(r); ctx.setLineDash([]);
        } else {
          ctx.strokeStyle = roadColour(r); ctx.lineWidth = w; strokeRoad(r);
          // lane markings once lanes are wide enough to see
          if (z > 1.4 && r.rank >= 1) {
            const total = r.oneway ? r.lanes : 2 * r.lanes;
            ctx.strokeStyle = r.rank >= 4 ? "rgba(20,20,20,0.55)" : "rgba(255,255,255,0.55)"; ctx.lineWidth = 1;
            for (let k = 1; k < total; k++) {
              const off = (k - total / 2) * LANE_W;
              const centre = !r.oneway && k === r.lanes;
              ctx.setLineDash(centre ? [] : [5, 7]);
              ctx.beginPath();
              for (let s = 0; s < r.pts.length - 1; s++) {
                const [ax, ay] = r.pts[s], [bx, by] = r.pts[s + 1], L = Math.hypot(bx - ax, by - ay) || 1, nx = -(by - ay) / L, ny = (bx - ax) / L;
                if (s === 0) ctx.moveTo(SX(ax + nx * off), SY(ay + ny * off));
                ctx.lineTo(SX(bx + nx * off), SY(by + ny * off));
              }
              ctx.stroke();
            }
            ctx.setLineDash([]);
          }
          if (r.oneway && z > 1.0 && r.rank >= 1) drawArrow(r);
        }
      }
    }
    ctx.globalAlpha = 1;
    // names of the big roads
    if (z > 0.35) {
      ctx.font = `600 ${Math.max(10, Math.min(13, z * 9))}px Segoe UI, system-ui`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      const done = new Set();
      for (const ri of idx) {
        const r = roads[ri]; if (!r.name || r.rank < (z > 1 ? 1 : 3) || done.has(r.name)) continue;
        const L = segLen(r.pts); if (L * z < 120) continue;
        done.add(r.name);
        let k = 0, best = 0; for (let s = 1; s < r.pts.length; s++) { const d = Math.hypot(r.pts[s][0] - r.pts[s - 1][0], r.pts[s][1] - r.pts[s - 1][1]); if (d > best) { best = d; k = s; } }
        const [ax, ay] = r.pts[k - 1], [bx, by] = r.pts[k]; let ang = Math.atan2(by - ay, bx - ax); if (ang > Math.PI / 2) ang -= Math.PI; if (ang < -Math.PI / 2) ang += Math.PI;
        ctx.save(); ctx.translate(SX((ax + bx) / 2), SY((ay + by) / 2)); ctx.rotate(ang);
        ctx.lineWidth = 3; ctx.strokeStyle = palette["floor-out"]; ctx.strokeText(r.name + (r.bridge ? " (flyover)" : r.tunnel ? " (underpass)" : ""), 0, 0);
        ctx.fillStyle = palette.text; ctx.fillText(r.name + (r.bridge ? " (flyover)" : r.tunnel ? " (underpass)" : ""), 0, 0); ctx.restore();
      }
    }
    hits = [];
    drawPois();
    drawSignals();
    drawVehicles();
    drawMini();
  }
  function drawArrow(r) {
    const L = segLen(r.pts); const step = 140 / state.cam.z;
    ctx.fillStyle = "rgba(255,255,255,0.7)";
    for (let d = step / 2; d < L; d += step) {
      let along = d, x = 0, y = 0, hx = 1, hy = 0;
      for (let s = 1; s < r.pts.length; s++) { const [ax, ay] = r.pts[s - 1], [bx, by] = r.pts[s], l = Math.hypot(bx - ax, by - ay) || 1; if (along <= l) { hx = (bx - ax) / l; hy = (by - ay) / l; x = ax + hx * along; y = ay + hy * along; break; } along -= l; }
      const sx = SX(x), sy = SY(y), a = 5;
      ctx.beginPath(); ctx.moveTo(sx + hx * a, sy + hy * a); ctx.lineTo(sx - hx * a - hy * a * 0.7, sy - hy * a + hx * a * 0.7); ctx.lineTo(sx - hx * a + hy * a * 0.7, sy - hy * a - hx * a * 0.7); ctx.fill();
    }
  }
  function drawPois() {
    const z = state.cam.z; if (z < 0.7) return;
    const x0 = WX(-20), x1 = WX(W + 20), y0 = WY(-20), y1 = WY(H + 20), r = Math.max(3, Math.min(7, z * 1.8));
    ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.font = "11px Segoe UI, system-ui";
    for (const p of POIS) {
      if (p.x < x0 || p.x > x1 || p.y < y0 || p.y > y1) continue;
      const sx = SX(p.x), sy = SY(p.y), g = POI_GROUP[p.kind] || "shop";
      ctx.fillStyle = POI_COL[g]; ctx.strokeStyle = palette.bg; ctx.lineWidth = 1.5;
      ctx.beginPath(); if (ctx.roundRect) ctx.roundRect(sx - r, sy - r, 2 * r, 2 * r, 2); else ctx.rect(sx - r, sy - r, 2 * r, 2 * r); ctx.fill(); ctx.stroke();
      if (z > 2.2 && p.name) { ctx.lineWidth = 3; ctx.strokeStyle = palette["floor-out"]; ctx.strokeText(p.name, sx + r + 3, sy); ctx.fillStyle = palette.muted; ctx.fillText(p.name, sx + r + 3, sy); }
      hits.push({ type: "poi", id: p.i, x: sx, y: sy, r: Math.max(7, r + 2) });
    }
  }
  function hereNow(pi) {
    let n = 0; for (const v of vehiclesOf(state.mode)) { const s = v.stops.length && stopAt(v, state.t); if (s && s[3] === pi) n++; } return n;
  }
  function signalState(sig, phase, t) {
    const log = R.modes[state.mode].signals[String(sig.id)] || [];
    let ph = 0, st = "green";
    const i = C.bisectRight(log, t, (e) => e[0]) - 1;
    if (i >= 0) { ph = log[i][1]; st = log[i][2]; }
    if (ph !== phase || st === "allred") return "red";
    return st;
  }
  // seconds until this phase's light changes, for the countdown on Lahore's signal heads (fixed plan only)
  function countdown(sig, phase, t) {
    if (state.mode !== "fixed" || !sig.greens) return null;
    const log = R.modes.fixed.signals[String(sig.id)] || [];
    const i = C.bisectRight(log, t, (e) => e[0]) - 1;
    const [since, ph, st] = i >= 0 ? log[i] : [0, 0, "green"];
    const el = t - since, other = 1 - ph;
    if (ph === phase && st === "green") return Math.max(0, Math.ceil(sig.greens[ph] - el));
    // red: what is left of the other phase's green, then its amber and the all-red
    if (st === "green") return Math.max(0, Math.ceil(sig.greens[ph] - el)) + 5;
    if (st === "amber") return Math.max(0, Math.ceil(3 - el)) + 2 + (ph === phase ? sig.greens[other] + 5 : 0);
    return Math.max(0, Math.ceil(2 - el)) + (ph === phase ? sig.greens[other] + 5 : 0);
  }
  function drawSignals() {
    const z = state.cam.z, t = state.t;
    for (const sig of R.signal_sites) {
      const sx = SX(sig.xy[0]), sy = SY(sig.xy[1]);
      if (sx < -40 || sy < -40 || sx > W + 40 || sy > H + 40) continue;
      if (z < 0.5) {
        ctx.fillStyle = palette.accent; ctx.beginPath(); ctx.arc(sx, sy, 3.5, 0, 7); ctx.fill();
      } else {
        sig.phases.forEach((ids, ph) => ids.forEach((lid) => {
          const lk = links[lid], p = lk.pts, [ax, ay] = p[p.length - 2], [bx, by] = p[p.length - 1], L = Math.hypot(bx - ax, by - ay) || 1;
          const hx = (bx - ax) / L, hy = (by - ay) / L, back = Math.min(8, L * 0.4);
          const x = bx - hx * back + hy * (lk.lanes * LANE_W + 1.5), y = by - hy * back - hx * (lk.lanes * LANE_W + 1.5);
          const st = signalState(sig, ph, t);
          ctx.fillStyle = st === "green" ? palette["sig-green"] : st === "amber" ? palette["sig-amber"] : palette["sig-red"];
          ctx.strokeStyle = palette.bg; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.arc(SX(x), SY(y), Math.max(3, z * 1.2), 0, 7); ctx.fill(); ctx.stroke();
          const cd = z > 2.4 ? countdown(sig, ph, t) : null;
          if (cd != null) {
            const ty = SY(y) - Math.max(10, z * 3);
            ctx.font = "700 11px Segoe UI, system-ui"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
            ctx.lineWidth = 3; ctx.strokeStyle = palette.bg; ctx.strokeText(String(cd), SX(x), ty); ctx.fillText(String(cd), SX(x), ty);
          }
        }));
      }
      hits.push({ type: "signal", id: sig.id, x: sx, y: sy, r: Math.max(10, z * 12) });
    }
  }
  function drawVehicles() {
    const z = state.cam.z, t = state.t, col = KCOL();
    const vs = vehiclesOf(state.mode);
    const x0 = WX(-20), x1 = WX(W + 20), y0 = WY(-20), y1 = WY(H + 20);
    for (const v of vs) {
      if (t < v.ts || (v.done != null && t >= v.done)) continue;
      const p = vehAt(v, t); if (!p) continue;
      if (p.x < x0 || p.x > x1 || p.y < y0 || p.y > y1) continue;
      const sx = SX(p.x), sy = SY(p.y), sel = state.follow === v.i;
      ctx.fillStyle = col[v.kind]; ctx.globalAlpha = p.parked ? 0.6 : 1;
      if (z < 0.6) {
        ctx.fillRect(sx - 1, sy - 1, sel ? 5 : 2.2, sel ? 5 : 2.2);
      } else {
        const [L, Wd] = KIND_SIZE[v.kind];
        ctx.save(); ctx.translate(sx, sy); ctx.rotate(Math.atan2(p.hy, p.hx));
        // never smaller than a readable mark, with a dark rim so it shows on any road colour
        const l = Math.max(v.kind === "motorcycle" ? 5 : 8, L * z), wd = Math.max(v.kind === "motorcycle" ? 3 : 4, Wd * z);
        ctx.strokeStyle = palette.bg; ctx.lineWidth = 1;
        ctx.fillRect(-l / 2, -wd / 2, l, wd); ctx.strokeRect(-l / 2, -wd / 2, l, wd);
        ctx.restore();
      }
      ctx.globalAlpha = 1;
      if (sel) { ctx.strokeStyle = palette.text; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(sx, sy, Math.max(9, z * 5), 0, 7); ctx.stroke(); }
      hits.push({ type: "veh", id: v.i, x: sx, y: sy, r: Math.max(6, z * 3) });
    }
  }
  let miniCache = null, miniView = null;
  function drawMini() {
    const w = mini.clientWidth, h = mini.clientHeight, [x0, y0, x1, y1] = R.meta.bbox;
    const s = Math.min((w - 10) / (x1 - x0), (h - 10) / (y1 - y0)), ox = (w - (x1 - x0) * s) / 2, oy = (h - (y1 - y0) * s) / 2;
    miniView = { s, ox, oy, x0, y0 };
    if (!miniCache) {
      miniCache = document.createElement("canvas"); const dpr = window.devicePixelRatio || 1;
      miniCache.width = Math.round(w * dpr); miniCache.height = Math.round(h * dpr);
      const c = miniCache.getContext("2d"); c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.fillStyle = palette.panel; c.fillRect(0, 0, w, h);
      for (const r of roads) {
        if (r.rank < 1) continue;
        c.strokeStyle = r.rank >= 4 ? palette["road-major"] : palette["road-minor"]; c.lineWidth = r.rank >= 4 ? 1.4 : 0.5;
        c.beginPath(); r.pts.forEach(([x, y], k) => (k ? c.lineTo(ox + (x - x0) * s, oy + (y - y0) * s) : c.moveTo(ox + (x - x0) * s, oy + (y - y0) * s))); c.stroke();
      }
    }
    mctx.clearRect(0, 0, w, h);
    mctx.drawImage(miniCache, 0, 0, w, h);
    mctx.strokeStyle = palette.accent; mctx.lineWidth = 1.5;
    mctx.strokeRect(ox + (WX(0) - x0) * s, oy + (WY(0) - y0) * s, (W / state.cam.z) * s, (H / state.cam.z) * s);
    if (state.follow != null) {
      const p = vehAt(vehiclesOf(state.mode)[state.follow], state.t);
      if (p) { mctx.fillStyle = palette.text; mctx.beginPath(); mctx.arc(ox + (p.x - x0) * s, oy + (p.y - y0) * s, 3.5, 0, 7); mctx.fill(); }
    }
  }

  // ---- panels ----
  function kpis() {
    const ser = R.modes[state.mode].series, i = Math.max(0, Math.min(ser.length - 1, Math.floor(state.t / 60)));
    $("k-on").textContent = ser[i] ? ser[i][1].toLocaleString("en") : "–";
    $("k-speed").textContent = ser[i] ? ser[i][2].toFixed(0) + " km/h" : "–";
    $("k-held").textContent = ser[i] && ser[i][4] != null ? ser[i][4].toLocaleString("en") : "–";
    const vs = vehiclesOf(state.mode); let done = 0; for (const v of vs) if (v.done != null && v.done <= state.t) done++;
    $("k-done").textContent = done.toLocaleString("en");
  }
  function renderHot() {
    const m = R.modes[state.mode].metrics;
    let html = `<h3>Worst signalised junctions · ${MODE_NAMES[state.mode]}</h3><p class="note">Vehicle-hours spent stopped within 60 m of the junction over the whole peak. Click one to fly there.</p><ul class="hot">`;
    for (const [name, vh] of m.worst_junctions) {
      const sig = R.signal_sites.find((s) => s.name === name);
      html += `<li data-sig="${sig ? sig.id : ""}" tabindex="0" role="button" aria-label="Fly to ${esc(name)}"><span>${esc(name)}</span><b class="num">${vh.toFixed(2)} veh-h</b></li>`;
    }
    html += `</ul><p class="note">${R.signal_sites.length} signals. OpenStreetMap maps only a couple of signals here, so a signal stands wherever two named through roads (tertiary or bigger) cross at grade, as Lahore signals them; back streets give way instead, and the Canal Road corridor runs signal-free through its underpasses. Fixed plan: the main road 60 s green, the side road 30 s, 3 s amber and 2 s all-red.</p>`;
    $("pane-hot").innerHTML = html;
  }
  function renderFollow() {
    const box = $("pane-follow");
    if (state.follow == null) { box.innerHTML = `<p class="muted">Press <b>Follow a vehicle</b> or click one on the map. The camera rides along and the map streams in around it.</p>`; return; }
    const v = vehiclesOf(state.mode)[state.follow], p = vehAt(v, state.t);
    const total = v.prefix[v.prefix.length - 1];
    const roadsOn = []; for (const lid of v.route) { const n = roads[links[lid].road].name; if (n && roadsOn[roadsOn.length - 1] !== n) roadsOn.push(n); }
    let html = (hopNote ? `<p class="note">${esc(hopNote)}</p>` : "") + `<h3>${KIND_NAMES[v.kind]} #${v.i + 1}</h3>`;
    const cur = stopAt(v, state.t), place = (s) => (s[3] >= 0 && POIS[s[3]] ? (POIS[s[3]].name || KIND_LABEL(POIS[s[3]].kind)) : "the kerb");
    const status = cur ? (cur[1] == null ? `arrived at ${place(cur)}` : p && p.parked ? `parked at ${place(cur)}` : `stopped at the kerb: ${cur[2]}`)
      : p ? (p.speed < 0.5 ? "stopped" : "moving") : v.done != null && state.t >= v.done ? "arrived" : "not on the road yet";
    html += `<div class="row"><span>Why</span><b>${esc(v.purpose || "—")}</b></div>`;
    html += `<div class="row"><span>Status</span><b>${esc(status)}</b></div>`;
    if (p) {
      const r = roads[links[p.link].road];
      html += `<div class="row"><span>On</span><b>${esc(r.name || r.cls.replace("_", " "))}${r.bridge ? " (flyover)" : r.tunnel ? " (underpass)" : ""}</b></div>`;
      html += `<div class="row"><span>Speed</span><b class="num">${(p.speed * 3.6).toFixed(0)} km/h</b></div>`;
      html += `<div class="row"><span>Driven</span><b class="num">${(p.driven / 1000).toFixed(2)} of ${(total / 1000).toFixed(2)} km</b></div>`;
    }
    html += `<div class="row"><span>Set off</span><b class="num">${C.clock(T0 + v.t0)}</b></div>`;
    if (v.done != null) html += `<div class="row"><span>Arrives</span><b class="num">${C.clock(T0 + v.done)} (${Math.round((v.done - v.t0) / 60)} min)</b></div>`;
    if (v.stops.length) {
      html += `<h3>Stops on the way</h3><ul class="stoplist">` + v.stops.map((s) => {
        const now = cur === s, when = s[1] == null ? C.clock(T0 + s[0]) : `${C.clock(T0 + s[0])}–${C.clock(T0 + s[1])}`;
        return `<li class="${now ? "now" : ""}"><span class="num">${when}</span><span>${esc(s[2])}${s[3] >= 0 ? " · " + esc(place(s)) : ""}${s[1] == null ? " (trip ends)" : ""}</span></li>`;
      }).join("") + `</ul>`;
    }
    html += `<h3>Route</h3><p class="note">${roadsOn.map(esc).join(" → ") || "local streets"}</p>`;
    html += `<button class="btn" id="stop-follow">Stop following</button>`;
    box.innerHTML = html;
  }
  function renderJunction() {
    const box = $("pane-junction");
    const sig = state.sel != null ? R.signal_sites.find((s) => s.id === state.sel) : null;
    if (!sig) return;
    const log = (R.modes[state.mode].signals[String(sig.id)] || []).filter((e) => e[0] <= state.t).slice(-8).reverse();
    let html = `<h3>${esc(sig.name)}</h3>`;
    // live: how long the current state has lasted, and who is queued on each phase's approaches
    const all = R.modes[state.mode].signals[String(sig.id)] || [];
    const i = C.bisectRight(all, state.t, (e) => e[0]) - 1, since = i >= 0 ? all[i][0] : 0;
    const queued = sig.phases.map(() => 0);
    const appr = new Map(); sig.phases.forEach((ids, ph) => ids.forEach((lid) => appr.set(lid, ph)));
    for (const v of vehiclesOf(state.mode)) {
      if (state.t < v.ts || (v.done != null && state.t >= v.done)) continue;
      const p = vehAt(v, state.t);
      if (p && p.speed < 0.5 && appr.has(p.link)) queued[appr.get(p.link)]++;
    }
    html += sig.phases.map((ids, ph) => { const cd = countdown(sig, ph, state.t), st = signalState(sig, ph, state.t);
      return `<div class="row"><span>Phase ${ph + 1}${sig.greens ? ` · ${sig.greens[ph]} s green` : ""} · <span class="num">${queued[ph]}</span> waiting</span><b>${st}${cd != null ? ` · <span class="num">${cd}</span> s` : ""}</b></div>`; }).join("");
    html += `<div class="row"><span>In this state for</span><b class="num">${Math.round(state.t - since)} s</b></div>`;
    html += `<h3>Last changes</h3>` + log.map(([t, ph, st]) => `<div class="row"><span class="num muted">${C.clock(T0 + t)}</span><span>phase ${ph + 1} ${st === "allred" ? "all-red" : st}</span></div>`).join("");
    const g = sig.greens || [32, 32];
    html += `<p class="note">${state.mode === "fixed" ? `Fixed: ${g[0]} s / ${g[1]} s green (the bigger road gets the long one), 3 s amber, 2 s all-red, a ${g[0] + g[1] + 10} s cycle all ${PERIOD}. The number beside each light counts down to its next change, as on Lahore's signal heads.` : `Adaptive: green held while the loop detectors 40 m back see vehicles, 10 s minimum, at most ${Math.round(g[0] * 1.5)} s / ${Math.round(g[1] * 1.5)} s, ends after a 3 s gap. No countdown: the green lasts as long as traffic keeps coming.`}</p>`;
    box.innerHTML = html;
  }
  // ---- places: where people stop this hour ----
  let lastPlaces = "";
  function renderPlaces() {
    vehiclesOf(state.mode);
    const visits = visitsOf[state.mode];
    let html = "";
    if (state.place != null) {
      const p = POIS[state.place];
      const here = vehiclesOf(state.mode).filter((v) => { const s = v.stops.length && stopAt(v, state.t); return s && s[3] === p.i; });
      html += `<h3>${esc(p.name || KIND_LABEL(p.kind))}</h3><div class="row"><span>What</span><b>${esc(KIND_LABEL(p.kind))}</b></div>`
        + `<div class="row"><span>Here now</span><b class="num">${here.length}</b></div><div class="row"><span>Visits this hour</span><b class="num">${visits[p.i]}</b></div>`
        + (here.length ? `<p class="note">${here.slice(0, 6).map((v) => `${KIND_NAMES[v.kind]} #${v.i + 1} (${esc(v.purpose)})`).join(", ")}${here.length > 6 ? "…" : ""}</p>` : "");
    }
    const top = POIS.map((p) => [visits[p.i], p]).filter(([n]) => n > 0).sort((a, b) => b[0] - a[0]).slice(0, 15);
    const max = top.length ? top[0][0] : 1;
    html += `<h3>Busiest places this hour · ${MODE_NAMES[state.mode]}</h3><p class="note">Real shops and amenities from OpenStreetMap; a visit is a vehicle pulling in, or stopping at the kerb outside. Click one to fly there.</p><ul class="hot">`
      + top.map(([n, p]) => `<li data-poi="${p.i}" tabindex="0" role="button" aria-label="Fly to ${esc(p.name || KIND_LABEL(p.kind))}"><span>${esc(p.name || KIND_LABEL(p.kind))} <span class="muted">· ${esc(KIND_LABEL(p.kind))}</span><div class="bar" style="width:${(100 * n / max).toFixed(0)}%;background:${POI_COL[POI_GROUP[p.kind] || "shop"]}"></div></span><b class="num">${n}</b></li>`).join("")
      + `</ul><p class="note">${POIS.length} places mapped in this area. OpenStreetMap lists only a few of the area's pharmacies, so pharmacy trips crowd onto those few.</p>`;
    if (html !== lastPlaces) { lastPlaces = html; $("pane-places").innerHTML = html; }
  }
  const ROWS = [["Trips", "trips"], ["Finished", "completed"], ["Median travel time, s", "travel_time_median_s"], ["Median delay, s", "delay_median_s"],
    ["Mean delay, s", "delay_mean_s"], ["Total delay, vehicle-hours", "delay_total_veh_h"], ["Stops per trip", "stops_mean"], ["Mean speed, km/h", "speed_mean_kmh"],
    ["Stopped at signals, vehicle-hours", "signal_delay_veh_h"], ["Still driving at the end", "still_driving"], ["Gridlocked (still for 5+ min)", "gridlocked"], ["Never got onto the road", "not_yet_entered"],
    ["Stops at shops and amenities", "errand_stops"], ["Trips that ended at one", "ended_at_a_place"], ["Rickshaw and wagon passenger stops", "passenger_stops"]];
  function renderCompare() {
    const f = R.modes.fixed.metrics, a = R.modes.adaptive.metrics;
    let html = `<h3>Same vehicles, same ${PERIOD}</h3><table class="cmp"><tr><th></th><th>Fixed</th><th>Adaptive</th></tr>`;
    const better = { travel_time_median_s: -1, delay_median_s: -1, delay_mean_s: -1, delay_total_veh_h: -1, stops_mean: -1, speed_mean_kmh: 1, signal_delay_veh_h: -1, completed: 1, still_driving: -1, gridlocked: -1, not_yet_entered: -1 };
    for (const [label, key] of ROWS) {
      const x = f[key], y = a[key], dir = better[key];
      const bx = dir && x !== y && (dir < 0 ? x < y : x > y), by = dir && x !== y && !bx;
      html += `<tr><td>${label}</td><td class="num ${bx ? "best" : ""}">${x}</td><td class="num ${by ? "best" : ""}">${y}</td></tr>`;
    }
    html += `</table><p class="note">${R.meta.trips.toLocaleString("en")} trips in an hour of ${PERIOD} peak (${C.clock(T0)}–${C.clock(T0 + 3600)}) plus 15 minutes to clear, on ${roads.length.toLocaleString("en")} pieces of real road. Vehicle mix from Lahore's registrations: about 65% motorcycles, 25% cars, 5% rickshaws, 5% buses and vans. The delay leaves out the time spent at a shop. Driving parameters, trip purposes and stop times are assumptions. Green = better.</p>`;
    if (f.purposes) {
      const tot = Object.values(f.purposes).reduce((x, y) => x + y, 0);
      html += `<h3>Why people drove</h3><table class="cmp">` + Object.entries(f.purposes).map(([k, n]) => `<tr><td>${esc(k)}</td><td class="num">${n.toLocaleString("en")}</td><td class="num muted">${(100 * n / tot).toFixed(0)}%</td></tr>`).join("") + `</table>`;
    }
    $("pane-compare").innerHTML = html;
  }
  function renderTimeline() {
    const w = tl.clientWidth, h = tl.clientHeight, T = R.meta.t1;
    tctx.clearRect(0, 0, w, h);
    const ser = R.modes[state.mode].series, other = R.modes[state.mode === "fixed" ? "adaptive" : "fixed"].series;
    const max = Math.max(10, ...ser.map((r) => r[1]), ...other.map((r) => r[1]));
    const line = (s, col, k, top, wd) => { tctx.strokeStyle = col; tctx.lineWidth = wd; tctx.beginPath(); s.forEach((r, i) => { const x = w * r[0] / T, y = (h - 6) * (1 - r[k] / top) + 2; i ? tctx.lineTo(x, y) : tctx.moveTo(x, y); }); tctx.stroke(); };
    line(other, palette.muted, 1, max, 1); line(ser, palette.accent, 1, max, 1.8);
    tctx.fillStyle = palette.accent; tctx.fillRect(w * state.t / T - 1.5, 0, 3, h);
  }
  function renderLegend() {
    const col = KCOL();
    $("legend").innerHTML = Object.entries(KIND_NAMES).map(([k, n]) => `<span><i class="sq" style="background:${col[k]}"></i>${n}</span>`).join("")
      + Object.entries(POI_NAMES).map(([g, n]) => `<span><i class="sq" style="background:${POI_COL[g]}"></i>${n}</span>`).join("")
      + `<span><i style="background:${palette["sig-green"]}"></i>Signal</span><span><i class="sq" style="background:${palette["road-major"]}"></i>Main road</span><span><i class="sq" style="border:1.5px dashed ${palette["road-tunnel"]};background:transparent"></i>Underpass</span><span>Flyovers drawn on top · drive on the left</span>`;
    const out = []; for (let m = 0; m <= R.meta.t1 / 60; m += 15) out.push(`<span>${C.clock(T0 + m * 60)}</span>`); $("ticks").innerHTML = out.join("");
  }

  // ---- loop ----
  let lastPanel = 0;
  function frame(force) {
    if (state.follow != null) {
      const p = vehAt(vehiclesOf(state.mode)[state.follow], state.t);
      if (p) {
        // after a hop the camera glides over rather than jumping across the city
        if (glide) {
          const f = Math.min(1, (performance.now() - glide.at) / 700), e = f * (2 - f);
          state.cam.x = glide.x + (p.x - glide.x) * e; state.cam.y = glide.y + (p.y - glide.y) * e;
          if (f >= 1) glide = null;
        } else { state.cam.x = p.x; state.cam.y = p.y; }
      } else if (state.playing) {                          // arrived: ride with someone else
        const prev = vehiclesOf(state.mode)[state.follow], i = pickLong();
        if (i != null) {
          hopNote = `${KIND_NAMES[prev.kind]} #${prev.i + 1} arrived at ${C.clock(T0 + prev.done)}; now riding with the next one.`;
          glide = { x: state.cam.x, y: state.cam.y, at: performance.now() };
          state.follow = i;
        }
      }
    }
    $("clock").textContent = C.clock(T0 + state.t); $("scrub").value = state.t;
    draw(); renderTimeline(); kpis();
    const now = performance.now();
    if (force || now - lastPanel > 300) {
      lastPanel = now;
      if ($("pane-follow").classList.contains("on")) renderFollow();
      if ($("pane-junction").classList.contains("on")) renderJunction();
      if ($("pane-places").classList.contains("on")) renderPlaces();
    }
  }
  let prev = null;
  function loop(ts) {
    const fading = Object.values(loadedAt).some((t0) => performance.now() - t0 < 500);
    if (state.playing) {
      if (prev != null) state.t = Math.min(R.meta.t1 - 1, state.t + ((ts - prev) / 1000) * state.speed);
      if (state.t >= R.meta.t1 - 1) setPlaying(false);
      frame(false);
    } else if (fading || dirty || glide) { frame(false); dirty = false; }
    prev = ts; requestAnimationFrame(loop);
  }
  let dirty = false;
  let glide = null, hopNote = "";
  function setPlaying(on) { state.playing = on; $("play").textContent = on ? "❚❚ Pause" : "▶ Play"; $("play").setAttribute("aria-label", on ? "Pause" : "Play"); }
  function save() { try { localStorage.setItem("traffic-twin", JSON.stringify({ theme: document.documentElement.dataset.theme, mode: state.mode })); } catch (e) { /* ignore */ } }
  function showTab(name) {
    for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", b.dataset.tab === name);
    for (const p of document.querySelectorAll(".pane")) p.classList.toggle("on", p.id === "pane-" + name);
    if (name === "compare") renderCompare(); if (name === "hot") renderHot(); if (name === "places") { lastPlaces = ""; renderPlaces(); }
    frame(true);
  }
  function follow(i) {
    state.follow = i; hopNote = ""; glide = null;
    if (i != null) { state.cam.z = Math.max(state.cam.z, 2.2); showTab("follow"); } else frame(true);
  }
  function flyTo(x, y, z) { state.follow = null; state.cam = { x, y, z: z || Math.max(state.cam.z, 1.6) }; frame(true); }

  $("play").onclick = () => { if (state.t >= R.meta.t1 - 1) state.t = 0; setPlaying(!state.playing); };
  $("speed").onchange = (e) => { state.speed = +e.target.value; };
  $("scrub").oninput = () => { state.t = +$("scrub").value; frame(true); };
  for (const b of document.querySelectorAll("#modes button")) {
    b.setAttribute("aria-pressed", b.dataset.mode === state.mode);
    b.onclick = () => { state.mode = b.dataset.mode; for (const x of document.querySelectorAll("#modes button")) x.setAttribute("aria-pressed", x === b); save(); renderHot(); if ($("pane-compare").classList.contains("on")) renderCompare(); frame(true); };
  }
  for (const b of document.querySelectorAll(".tabs button")) b.onclick = () => showTab(b.dataset.tab);
  // ride along with someone who still has a long way to go; when they arrive, hop to another
  function pickLong() {
    const vs = vehiclesOf(state.mode).filter((v) => { const p = vehAt(v, state.t); return p && !p.parked && v.prefix[v.prefix.length - 1] - p.driven > 1500; });
    // most of the time, ride with someone who has a stop to make: that is where the city shows
    const errand = vs.filter((v) => v.stops.some((s) => s[0] > state.t + 30 && s[3] >= 0));
    const pool = errand.length && Math.random() < 0.7 ? errand : vs;
    return pool.length ? pool[Math.floor(Math.random() * pool.length)].i : null;
  }
  $("follow-random").onclick = () => { const i = pickLong(); if (i != null) follow(i); };
  $("pane-follow").onclick = (e) => { if (e.target.id === "stop-follow") follow(null); };
  $("pane-places").onclick = (e) => {
    const li = e.target.closest("li[data-poi]"); if (!li) return;
    const p = POIS[+li.dataset.poi]; state.place = p.i; lastPlaces = ""; flyTo(p.x, p.y, 3); showTab("places");
  };
  $("pane-places").onkeydown = (e) => { if ((e.key === "Enter" || e.key === " ") && e.target.closest("li[data-poi]")) { e.preventDefault(); e.target.click(); } };
  // a keyboard user opens a hotspot with Enter or Space
  $("pane-hot").onkeydown = (e) => { if ((e.key === "Enter" || e.key === " ") && e.target.closest("li[data-sig]")) { e.preventDefault(); e.target.click(); } };
  $("pane-hot").onclick = (e) => {
    const li = e.target.closest("li[data-sig]"); if (!li || li.dataset.sig === "") return;
    const sig = R.signal_sites.find((s) => s.id === +li.dataset.sig); state.sel = sig.id;
    flyTo(sig.xy[0], sig.xy[1], 2.6); showTab("junction");
  };
  $("zin").onclick = () => { state.follow = null; state.cam.z = Math.min(12, state.cam.z * 1.6); frame(true); };
  $("zout").onclick = () => { state.follow = null; state.cam.z = Math.max(0.05, state.cam.z / 1.6); frame(true); };
  $("zfit").onclick = () => { state.follow = null; fitAll(); frame(true); };
  $("theme").onclick = () => { const d = document.documentElement.dataset.theme !== "light"; document.documentElement.dataset.theme = d ? "light" : "dark"; $("theme").textContent = d ? "Dark" : "Light"; readPalette(); miniCache = null; renderLegend(); save(); frame(true); };
  // pan and zoom
  let drag = null;
  cv.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, cx: state.cam.x, cy: state.cam.y, moved: false }; cv.setPointerCapture(e.pointerId); });
  cv.addEventListener("pointermove", (e) => {
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) { drag.moved = true; cv.classList.add("drag"); state.follow = null; }
      if (drag.moved) { state.cam.x = drag.cx - dx / state.cam.z; state.cam.y = drag.cy - dy / state.cam.z; dirty = true; }
      return;
    }
    const h = pickAt(e), tip = $("tip"); if (!h) { tip.style.display = "none"; return; }
    const rect = cv.getBoundingClientRect();
    if (h.type === "veh") { const v = vehiclesOf(state.mode)[h.id], p = vehAt(v, state.t); tip.innerHTML = `<b>${KIND_NAMES[v.kind]}</b><br><span class="muted">${p ? (p.speed * 3.6).toFixed(0) + " km/h · click to follow" : ""}</span>`; }
    else if (h.type === "poi") { const p = POIS[h.id]; vehiclesOf(state.mode); tip.innerHTML = `<b>${esc(p.name || KIND_LABEL(p.kind))}</b><br><span class="muted">${esc(KIND_LABEL(p.kind))} · ${hereNow(p.i)} here now · ${visitsOf[state.mode][p.i]} visits this hour</span>`; }
    else { const s = R.signal_sites.find((x) => x.id === h.id); tip.innerHTML = `<b>${esc(s.name)}</b><br><span class="muted">signal · click for phases</span>`; }
    tip.style.display = "block"; tip.style.left = (e.clientX - rect.left + 14) + "px"; tip.style.top = (e.clientY - rect.top + 14) + "px";
  });
  cv.addEventListener("pointerup", (e) => {
    const wasDrag = drag && drag.moved; drag = null; cv.classList.remove("drag");
    if (wasDrag) return;
    const h = pickAt(e);
    if (h && h.type === "veh") follow(h.id);
    else if (h && h.type === "poi") { state.place = h.id; showTab("places"); }
    else if (h && h.type === "signal") { state.sel = h.id; showTab("junction"); }
  });
  cv.addEventListener("mouseleave", () => { $("tip").style.display = "none"; });
  cv.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = cv.getBoundingClientRect(), mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const wx = WX(mx), wy = WY(my), f = e.deltaY < 0 ? 1.2 : 1 / 1.2;
    state.cam.z = Math.max(0.05, Math.min(12, state.cam.z * f));
    if (state.follow == null) { state.cam.x = wx - (mx - W / 2) / state.cam.z; state.cam.y = wy - (my - H / 2) / state.cam.z; }
    dirty = true;
  }, { passive: false });
  mini.addEventListener("click", (e) => {
    const rect = mini.getBoundingClientRect(), v = miniView; if (!v) return;
    flyTo(v.x0 + (e.clientX - rect.left - v.ox) / v.s, v.y0 + (e.clientY - rect.top - v.oy) / v.s);
  });
  function pickAt(e) {
    const rect = cv.getBoundingClientRect(), mx = e.clientX - rect.left, my = e.clientY - rect.top;
    let best = null, bd = Infinity;
    for (const h of hits) { const d = Math.hypot(h.x - mx, h.y - my); if (d < h.r && d < bd) { bd = d; best = h; } }
    return best;
  }
  document.addEventListener("keydown", (e) => {
    if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
    if (e.code === "Space" && e.target.tagName !== "BUTTON") { e.preventDefault(); $("play").click(); }
    if (e.shiftKey && e.key.startsWith("Arrow")) {        // Shift + arrows pan the map a quarter screen
      e.preventDefault(); state.follow = null;
      const d = 0.25 / state.cam.z;
      if (e.key === "ArrowLeft") state.cam.x -= W * d; if (e.key === "ArrowRight") state.cam.x += W * d;
      if (e.key === "ArrowUp") state.cam.y -= H * d; if (e.key === "ArrowDown") state.cam.y += H * d;
      frame(true); return;
    }
    if (e.key === "ArrowRight") { state.t = Math.min(R.meta.t1 - 1, state.t + 60); frame(true); }
    if (e.key === "ArrowLeft") { state.t = Math.max(0, state.t - 60); frame(true); }
    if (e.key === "+" || e.key === "=") $("zin").click();
    if (e.key === "-") $("zout").click();
    if (e.key === "f") $("follow-random").click();
    if (e.key === "Escape") follow(null);
  });
  window.addEventListener("resize", () => { fitCanvas(); frame(true); });

  $("theme").textContent = document.documentElement.dataset.theme === "light" ? "Dark" : "Light";
  readPalette(); fitCanvas(); fitAll(); renderLegend(); renderHot(); frame(true); requestAnimationFrame(loop);
  window.__traffic = { state, frame, showTab, follow, flyTo, hits: () => hits, vehAt, vehiclesOf, loadedAt, visibleTiles };
})();

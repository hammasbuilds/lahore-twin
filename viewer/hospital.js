/* Hospital Twin viewer: replays one simulated day of the Emergency Department
 * and the medical ward from window.HOSPITAL. Positions come from routed trips,
 * beds and equipment from their change logs, "why" from each message's cause.
 * Nothing here re-simulates.
 */
"use strict";

(function () {
  const R = window.HOSPITAL;
  const C = TwinCore;
  const PL = R.plans;
  const ROOMS = { ed: Object.fromEntries(PL.ed.rooms.map((r) => [r.id, r])), ward: Object.fromEntries(PL.ward.rooms.map((r) => [r.id, r])) };
  const MODE_NAMES = { today: "Today", connected: "Connected" };
  const VIEW_NAMES = { site: "Site", ed: "Emergency", ward: "Ward" };
  const ROLE_NAMES = { doctor: "Doctor", nurse: "Nurse", clerk: "Clerk", porter: "Porter", cleaner: "Cleaner", radiographer: "Radiographer", guard: "Guard", patient: "Patient" };
  const PRIO = { red: 0, orange: 1, yellow: 2, green: 3, blue: 4 };
  const KEY_TOPIC = /\/(alarm|call|answered|admit|left|alert|door|below_par|clean_request|triage)$/;

  // ---- index ----
  function indexMode(M) {
    const agents = {};
    for (const [id, a] of Object.entries(M.agents)) agents[id] = { id, ...a, trips: [], labels: [], spans: [] };
    for (const [aid, b, t0, v, pts] of M.trips) agents[aid].trips.push({ t: t0, b, v, pts });
    for (const [t, aid, text] of M.labels) agents[aid].labels.push([t, text]);
    for (const [aid, on, off, b, x, y] of M.presence) agents[aid].spans.push({ on, off: off == null ? Infinity : off, b, x, y });
    for (const a of Object.values(agents)) { a.trips.sort((p, q) => p.t - q.t); a.spans.sort((p, q) => p.on - q.on); }
    const assets = {};
    for (const ev of M.assets) (assets[ev[1]] = assets[ev[1]] || []).push(ev);
    const beds = {};
    for (const [t, id, st] of M.beds) (beds[id] = beds[id] || []).push([t, st]);
    const byId = {};
    for (const m of M.log) byId[m.id] = m;
    const records = Object.fromEntries(M.records.map((r) => [r.id, r]));
    return { ...M, agents, assetEv: assets, bedEv: beds, byId, rec: records };
  }
  const modes = Object.fromEntries(Object.entries(R.modes).map(([k, M]) => [k, indexMode(M)]));

  const state = { t: 11 * 3600, mode: "connected", view: "ed", floor: { ed: "G", ward: "2" }, playing: false, speed: 300, sel: null, follow: null };
  C.setHops([...(PL.ed.portal_hops || []), ...(PL.ward.portal_hops || [])]);
  const FLOORS = { ed: PL.ed.floors, ward: PL.ward.floors };
  function floorOf(b, x, y) {
    for (const f of FLOORS[b] || []) { const [ox, oy] = f.origin; if (x >= ox && x <= ox + f.size[0] && y >= oy && y <= oy + f.size[1]) return f.id; }
    return (FLOORS[b] || [{ id: "G" }])[0].id;
  }
  const floorDef = (b, id) => FLOORS[b].find((f) => f.id === id);
  const curFloor = () => floorDef(state.view, state.floor[state.view]);
  try {
    const saved = JSON.parse(localStorage.getItem("hospital-twin") || "{}");
    if (saved.theme) document.documentElement.dataset.theme = saved.theme;
    if (saved.mode && R.modes[saved.mode]) state.mode = saved.mode;
    if (saved.view && VIEW_NAMES[saved.view]) state.view = saved.view;
  } catch (e) { /* storage blocked: defaults are fine */ }

  const $ = (id) => document.getElementById(id);
  const cv = $("plan"), ctx = cv.getContext("2d");
  const tl = $("tl"), tctx = tl.getContext("2d");
  const scrub = $("scrub");
  const M = () => modes[state.mode];
  let palette = {};
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  function readPalette() {
    for (const k of ["bg", "panel", "panel-2", "floor", "floor-out", "wall", "desk", "ok", "alert", "warn", "text", "muted", "line", "accent", "water", "call",
      "t-red", "t-orange", "t-yellow", "t-green", "t-blue"]) palette[k] = css("--" + k);
  }
  function hex(c) {
    if (c.startsWith("rgb")) return c.match(/\d+/g).slice(0, 3).map(Number);
    c = c.replace("#", ""); if (c.length === 3) c = c.split("").map((x) => x + x).join("");
    return [0, 2, 4].map((i) => parseInt(c.slice(i, i + 2), 16));
  }
  const rgba = (c, a) => { const [r, g, b] = hex(c); return `rgba(${r},${g},${b},${a})`; };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const tri = (c) => palette["t-" + c];
  const mins = (s) => Math.max(0, Math.round(s / 60));

  // ---- state at time t ----
  function agentAt(a, t) {
    let span = null;
    for (const s of a.spans) { if (s.on <= t) span = s; else break; }
    if (!span || t >= span.off) return null;
    const i = C.bisectRight(a.trips, t, (tr) => tr.t) - 1;
    if (i < 0 || a.trips[i].t < span.on) return { b: span.b, x: span.x, y: span.y, moving: false };
    const tr = a.trips[i];
    const [x, y, moving] = C.pointAlong(tr.pts, (t - tr.t) * tr.v);
    return { b: tr.b, x, y, moving };
  }
  const labelAt = (a, t) => { const i = C.bisectRight(a.labels, t, (l) => l[0]) - 1; return i >= 0 ? a.labels[i][1] : ""; };
  function assetAt(id, t) {
    const evs = M().assetEv[id] || []; const i = C.bisectRight(evs, t, (e) => e[0]) - 1;
    if (i < 0) return null;
    const [, , b, x, y, holder] = evs[i];
    if (holder && M().agents[holder]) {
      const at = agentAt(M().agents[holder], t);
      if (at) return { b: at.b, x: at.x + 0.35, y: at.y + 0.35, holder, moving: at.moving };
    }
    return { b, x, y, holder };
  }
  function bedAt(id, t) {
    const evs = M().bedEv[id] || []; const i = C.bisectRight(evs, t, (e) => e[0]) - 1;
    return i >= 0 ? { state: evs[i][1], since: evs[i][0] } : { state: "ready", since: 0 };
  }
  const inED = (r, t) => r.arrive <= t && (r.left == null || t < r.left);
  function openAlarms(t) { return M().alarms.filter((a) => a.annunciated != null && a.annunciated <= t && (a.arrived == null || t < a.arrived)); }
  function openCalls(t) { return M().calls.filter((c) => c.t <= t && (c.arrived == null || t < c.arrived)); }
  function fridgeAt(key, t) { const s = M().fridge[key]; return s[Math.max(0, Math.min(s.length - 1, Math.floor(t / 60)))]; }

  // ---- geometry ----
  function size(v) { return v === "site" ? R.site.size : curFloor().size; }
  // plan coordinates -> floor-local -> what the current view draws (null = not on this view)
  function local(b, x, y) { const f = floorDef(b, floorOf(b, x, y)); return [x - f.origin[0], y - f.origin[1], f.id]; }
  function toView(b, x, y) {
    if (b === "campus") return state.view === "site" ? [x, y] : null;
    if (!FLOORS[b]) return null;
    const [lx, ly, fid] = local(b, x, y);
    if (state.view === b) return fid === state.floor[b] ? [lx, ly] : null;
    if (state.view !== "site") return null;
    if (b === "ed") return [R.site.ed_origin[0] + lx, R.site.ed_origin[1] + ly];
    const w = R.site.ward; return [w.origin[0] + w.dx + ly, w.origin[1] + w.dy - lx];
  }
  let view = { s: 10, ox: 0, oy: 0 };
  function fit() {
    const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const [W, Hh] = size(state.view), top = 16, bottom = w < 700 ? 12 : 64, side = 20;
    const s = Math.min((w - side * 2) / W, (h - top - bottom) / Hh);
    view = { s, ox: (w - W * s) / 2, oy: top + (h - top - bottom - Hh * s) / 2 };
    tl.width = Math.round(tl.clientWidth * dpr); tl.height = Math.round(tl.clientHeight * dpr); tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  const X = (x) => view.ox + x * view.s, Y = (y) => view.oy + y * view.s;
  function poly(pts, close = true) { ctx.beginPath(); pts.forEach(([x, y], k) => (k ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y)))); if (close) ctx.closePath(); }

  // ---- drawing ----
  let hits = [];
  function drawBuilding(b) {
    const F = curFloor(), [fx0, fy0] = F.origin, s = view.s, t = state.t;
    const onF = (x, y) => floorOf(b, x, y) === F.id;
    const P = { ...PL[b],
      rooms: PL[b].rooms.filter((r) => r.floor === F.id).map((r) => ({ ...r, rect: [r.rect[0] - fx0, r.rect[1] - fy0, r.rect[2] - fx0, r.rect[3] - fy0] })),
      furniture: (PL[b].furniture || []).filter((f) => onF(f.rect[0], f.rect[1])).map((f) => ({ ...f, rect: [f.rect[0] - fx0, f.rect[1] - fy0, f.rect[2], f.rect[3]] })),
      labels: (PL[b].labels || []).filter((l) => onF(l.at[0], l.at[1])).map((l) => ({ ...l, at: [l.at[0] - fx0, l.at[1] - fy0] })),
      doors: PL[b].doors.filter((d) => ROOMS[b][d.a].floor === F.id).map((d) => ({ ...d, at: d.at - (d.axis === "x" ? fy0 : fx0), lo: d.lo - (d.axis === "x" ? fx0 : fy0), hi: d.hi - (d.axis === "x" ? fx0 : fy0) })),
      size: F.size };
    const LROOMS = Object.fromEntries(P.rooms.map((r) => [r.id, r]));
    for (const r of P.rooms) {
      const [x0, y0, x1, y1] = r.rect;
      ctx.fillStyle = r.kind === "outdoor" ? palette["floor-out"] : r.kind === "corridor" ? rgba(palette.muted, 0.08) : palette.floor;
      ctx.fillRect(X(x0), Y(y0), (x1 - x0) * s, (y1 - y0) * s);
    }
    ctx.fillStyle = palette.desk;
    for (const f of P.furniture || []) { const [x, y, w, h] = f.rect; ctx.fillRect(X(x), Y(y), w * s, h * s); }
    ctx.strokeStyle = palette.wall; ctx.lineWidth = Math.max(1, s * 0.12);
    for (const r of P.rooms) { if (r.kind === "outdoor") continue; const [x0, y0, x1, y1] = r.rect; ctx.strokeRect(X(x0), Y(y0), (x1 - x0) * s, (y1 - y0) * s); }
    for (const d of P.doors) {
      ctx.strokeStyle = (LROOMS[d.a] || {}).kind === "outdoor" || (LROOMS[d.b] || {}).kind === "outdoor" ? palette["floor-out"] : palette.floor;
      ctx.lineWidth = Math.max(1.5, s * 0.16); ctx.beginPath();
      if (d.axis === "x") { ctx.moveTo(X(d.lo + 0.05), Y(d.at)); ctx.lineTo(X(d.hi - 0.05), Y(d.at)); } else { ctx.moveTo(X(d.at), Y(d.lo + 0.05)); ctx.lineTo(X(d.at), Y(d.hi - 0.05)); }
      ctx.stroke();
    }
    if (P.outline) { ctx.strokeStyle = palette.wall; ctx.lineWidth = Math.max(1.5, s * 0.22); poly(P.outline); ctx.stroke(); }
    // lifts and stairs on this floor
    for (const pt of PL[b].portals || []) {
      const at = pt.at[F.id]; if (!at) continue;
      const x = X(at[0] - fx0), y = Y(at[1] - fy0), r = Math.max(7, s * 0.6);
      ctx.fillStyle = palette["panel-2"]; ctx.strokeStyle = palette.accent; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.rect(x - r, y - r, 2 * r, 2 * r); ctx.fill(); ctx.stroke();
      ctx.fillStyle = palette.accent; ctx.font = `700 ${Math.max(8, r * 0.9)}px Segoe UI`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(pt.kind === "lift" ? "⇅" : "▤", x, y + 0.5);
      const others = Object.keys(pt.at).filter((f) => f !== F.id).join(", ");
      hits.push({ type: "portal", id: pt.id, x, y, r: r + 2, text: `${pt.kind === "lift" ? "Lift" : "Stairs"} to ${others}` });
    }
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (const r of P.rooms) {
      const [x0, y0, x1, y1] = r.rect, name = (s * (x1 - x0) < 70 && P.short_names[r.id]) || r.name;
      ctx.font = `600 ${Math.max(9, Math.min(12, s * 0.45))}px Segoe UI, system-ui`; ctx.fillStyle = palette.muted;
      if (r.kind === "corridor" && (y1 - y0) > (x1 - x0)) { ctx.save(); ctx.translate(X((x0 + x1) / 2), Y((y0 + y1) / 2)); ctx.rotate(-Math.PI / 2); ctx.textBaseline = "middle"; ctx.fillText(name, 0, 0); ctx.restore(); }
      else ctx.fillText(name, X((x0 + x1) / 2), Y(y0) + 3);
    }
    for (const l of P.labels || []) { ctx.fillStyle = palette.muted; ctx.fillText(l.text, X(l.at[0]), Y(l.at[1])); }
    // beds and chairs
    const calls = new Set(openCalls(t).map((c) => c.bed)), alarms = openAlarms(t);
    for (const [id, bd] of Object.entries(R.beds)) {
      if (bd.unit !== b || !onF(bd.spot[0], bd.spot[1])) continue;
      const st = bedAt(id, t), [bx, by] = [bd.spot[0] - fx0, bd.spot[1] - fy0], chair = id.startsWith("chair");
      const w = chair ? 0.7 : 0.95, h = chair ? 0.7 : 1.9;
      const rec = st.state === "occupied" || st.state === "reserved" ? null : null;
      ctx.lineWidth = 1.4;
      let fill = "transparent", stroke = palette.line;
      if (st.state === "occupied") { fill = rgba(palette.accent, 0.18); stroke = palette.accent; }
      else if (st.state === "dirty") { fill = rgba(palette.warn, 0.2); stroke = palette.warn; }
      else if (st.state === "reserved") { stroke = palette.accent; ctx.setLineDash([3, 3]); }
      else if (st.state === "ready") { stroke = rgba(palette.ok, 0.7); }
      ctx.fillStyle = fill; ctx.strokeStyle = stroke;
      const rx = X(bx - w / 2), ry = Y(by - h / 2);
      ctx.fillRect(rx, ry, w * s, h * s); ctx.strokeRect(rx, ry, w * s, h * s); ctx.setLineDash([]);
      if (calls.has(id)) { ctx.strokeStyle = palette.call; ctx.lineWidth = 2.5; ctx.strokeRect(rx - 3, ry - 3, w * s + 6, h * s + 6); }
      const al = alarms.find((a) => a.bed === id);
      if (al) {
        const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 160);
        ctx.strokeStyle = rgba(palette.alert, 0.5 + 0.5 * pulse); ctx.lineWidth = 3;
        ctx.beginPath(); ctx.arc(X(bx), Y(by), Math.max(10, s * 1.5) + pulse * 4, 0, 7); ctx.stroke();
      }
      void rec;
    }
    // fridge chip
    const fkey = b === "ed" ? "ed" : "ward", fg = b === "ed" ? P.spots.fridge[0] : P.spots.meds_fridge[0];
    if (!onF(fg[0], fg[1])) return;
    const fspot = [fg[0] - fx0, fg[1] - fy0];
    const T = fridgeAt(fkey, t), over = T > 8;
    ctx.font = "600 11px Segoe UI, system-ui"; ctx.textBaseline = "middle"; ctx.textAlign = "left";
    const txt = `${T.toFixed(1)} °C`, tw = ctx.measureText(txt).width + 12;
    const fx = Math.min(X(fspot[0]) - tw / 2, X(P.size[0]) - tw - 2);
    ctx.fillStyle = over ? palette.alert : palette["panel-2"]; ctx.strokeStyle = over ? palette.alert : palette.line;
    ctx.beginPath(); ctx.roundRect ? ctx.roundRect(fx, Y(fspot[1]) - 9, tw, 18, 9) : ctx.rect(fx, Y(fspot[1]) - 9, tw, 18); ctx.fill(); ctx.stroke();
    ctx.fillStyle = over ? "#fff" : palette.text; ctx.fillText(txt, fx + 6, Y(fspot[1]));
    hits.push({ type: "fridge", id: fkey, x: fx + tw / 2, y: Y(fspot[1]), r: tw / 2 });
  }

  function drawSite() {
    const S = R.site;
    ctx.fillStyle = palette["floor-out"]; ctx.strokeStyle = palette.line; ctx.lineWidth = 1.5; poly(S.campus); ctx.fill(); ctx.stroke();
    for (const bld of S.buildings) {
      ctx.fillStyle = bld.sim ? rgba(palette.accent, 0.12) : palette.desk; ctx.strokeStyle = bld.sim ? palette.accent : palette.wall;
      ctx.lineWidth = bld.sim ? 1.6 : 0.6; poly(bld.poly); ctx.fill(); ctx.stroke();
    }
    // the two simulated floors inside their footprints
    ctx.strokeStyle = rgba(palette.accent, 0.55); ctx.lineWidth = 0.6;
    for (const b of ["ed", "ward"]) for (const r of PL[b].rooms) {
      if (r.kind === "outdoor" || r.floor !== (b === "ed" ? "G" : "2")) continue;
      const [x0, y0, x1, y1] = r.rect, c = [[x0 + 0.01, y0 + 0.01], [x1 - 0.01, y0 + 0.01], [x1 - 0.01, y1 - 0.01], [x0 + 0.01, y1 - 0.01]].map(([x, y]) => toView(b, x, y));
      ctx.beginPath(); c.forEach(([x, y], k) => (k ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y)))); ctx.closePath(); ctx.stroke();
    }
    ctx.strokeStyle = palette.accent; ctx.lineWidth = 2; ctx.setLineDash([5, 5]); poly(S.path, false); ctx.stroke(); ctx.setLineDash([]);
    ctx.font = "600 12px Segoe UI, system-ui"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
    for (const bld of S.buildings) {
      if (!bld.name) continue;
      const xs = bld.poly.map((p) => p[0]), ys = bld.poly.map((p) => p[1]);
      const nm = bld.name === "Lahore General Hospital" ? "Main block" : bld.name.replace(" (General Hospital)", "").replace(" General Hospital", "");
      ctx.fillStyle = bld.sim ? palette.text : palette.muted;
      ctx.fillText(nm, X(Math.max(...xs)) + 6, Y((Math.min(...ys) + Math.max(...ys)) / 2));
    }
    // north arrow: the plan is turned 17.5° so the buildings sit square
    const ax = X(S.size[0]) - 30, ay = Y(0) + 34, th = -S.rotation_deg * Math.PI / 180;
    ctx.save(); ctx.translate(ax, ay); ctx.rotate(th); ctx.strokeStyle = palette.text; ctx.fillStyle = palette.text; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(0, 14); ctx.lineTo(0, -14); ctx.stroke(); ctx.beginPath(); ctx.moveTo(0, -18); ctx.lineTo(-5, -8); ctx.lineTo(5, -8); ctx.closePath(); ctx.fill();
    ctx.textAlign = "center"; ctx.fillText("N", 0, -26); ctx.restore();
    ctx.fillStyle = palette.muted; ctx.font = "11px Segoe UI, system-ui"; ctx.textAlign = "left";
    ctx.fillText("Campus and buildings © OpenStreetMap contributors (ODbL)", X(0) + 4, Y(S.size[1]) - 8);
  }

  function drawAssets() {
    const s = view.s, t = state.t;
    for (const a of R.assets) {
      const at = assetAt(a.id, t); if (!at) continue;
      const v = toView(at.b, at.x, at.y); if (!v) continue;
      if (state.view === "site" && !at.holder) continue;
      const x = X(v[0]), y = Y(v[1]), r = Math.max(3, Math.min(6, s * 0.22));
      ctx.lineWidth = 1.5; ctx.strokeStyle = palette.water; ctx.fillStyle = rgba(palette.water, 0.35);
      ctx.beginPath();
      if (a.kind === "pump") { ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath(); }
      else if (a.kind === "wheelchair") ctx.arc(x, y, r, 0, 7);
      else ctx.rect(x - r * 1.3, y - r * 0.7, r * 2.6, r * 1.4);
      ctx.fill(); ctx.stroke();
      hits.push({ type: "asset", id: a.id, x, y, r: r + 3 });
    }
  }

  function drawAgents() {
    const s = view.s, t = state.t, r = state.view === "site" ? 2.6 : Math.max(3.5, s * 0.3);
    for (const a of Object.values(M().agents)) {
      const at = agentAt(a, t); if (!at) continue;
      const v = toView(at.b, at.x, at.y); if (!v) continue;
      const rec = M().rec[a.id];
      let col = a.colour;
      if (rec && (rec.triaged == null || t < rec.triaged)) col = palette.muted;      // colour only once triaged
      else if (rec) col = tri(rec.colour);
      const x = X(v[0]), y = Y(v[1]);
      const sel = state.sel && state.sel.type === "agent" && state.sel.id === a.id;
      ctx.beginPath(); ctx.arc(x, y, sel ? r * 1.4 : r, 0, 7); ctx.fillStyle = col; ctx.fill();
      ctx.lineWidth = sel ? 3 : (a.role === "patient" ? 1.2 : 2); ctx.strokeStyle = sel ? palette.text : (a.role === "patient" ? palette.bg : palette.panel);
      ctx.stroke();
      if (a.role !== "patient" && state.view !== "site") { ctx.fillStyle = palette.bg; ctx.font = `700 ${Math.max(7, r * 1.1)}px Segoe UI`; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(a.role[0].toUpperCase(), x, y + 0.5); }
      hits.push({ type: "agent", id: a.id, x, y, r: r + 2 });
    }
  }

  function draw() {
    const w = cv.clientWidth, h = cv.clientHeight;
    ctx.clearRect(0, 0, w, h); hits = [];
    if (state.view === "site") drawSite(); else drawBuilding(state.view);
    drawAssets(); drawAgents();
  }

  // ---- side panel ----
  function kpis() {
    const t = state.t, recs = M().records;
    $("k-ed").textContent = recs.filter((r) => inED(r, t)).length;
    $("k-wait").textContent = recs.filter((r) => inED(r, t) && (r.seen == null || r.seen > t)).length;
    let free = 0, dirty = 0;
    for (const [id, b] of Object.entries(R.beds)) if (b.unit === "ward") { const s = bedAt(id, t).state; if (s === "ready") free++; if (s === "dirty") dirty++; }
    $("k-beds").textContent = free;
    $("k-beds-l").textContent = dirty ? `Ward beds free · ${dirty} to clean` : "Ward beds free";
    const fr = ["ed", "ward"].filter((k) => fridgeAt(k, t) > 8).length;
    $("k-alerts").textContent = openAlarms(t).length + openCalls(t).length + fr;
  }
  function renderBoard() {
    const t = state.t, rows = M().records.filter((r) => inED(r, t));
    rows.sort((a, b) => ((a.triaged != null && a.triaged <= t ? PRIO[a.colour] : 5) - (b.triaged != null && b.triaged <= t ? PRIO[b.colour] : 5)) || a.arrive - b.arrive);
    let html = `<h3>Emergency board · ${rows.length} in the department</h3><table class="board"><tr><th></th><th>Patient</th><th>Where</th><th class="num">Wait</th><th>Now</th></tr>`;
    for (const r of rows) {
      const triaged = r.triaged != null && r.triaged <= t, a = M().agents[r.id];
      const where = r.placed != null && r.placed <= t ? r.place : (triaged ? "Waiting hall" : "Arriving");
      html += `<tr data-agent="${r.id}"><td><i class="chip" style="background:${triaged ? tri(r.colour) : palette.line}" title="${triaged ? r.colour : "not triaged yet"}"></i></td><td>${esc(r.name)}${r.ambulance ? " 🚑" : ""}</td><td>${esc(where)}</td><td class="num">${mins(t - r.arrive)}m</td><td class="muted">${esc(labelAt(a, t))}</td></tr>`;
    }
    html += "</table>";
    if (!rows.length) html += `<p class="muted">Nobody in the department at ${C.clock(t)}.</p>`;
    $("pane-board").innerHTML = html;
  }
  function renderBeds() {
    const t = state.t;
    const tile = (id, b) => { const st = bedAt(id, t), who = st.state === "occupied" ? occupant(id, t) : ""; return `<div class="bed ${st.state}" data-bed="${id}" title="${esc(id)}: ${st.state} since ${C.clock(st.since)}"><b>${esc(id.replace("bed_", ""))}</b>${st.state}${who ? "<br><span class='muted'>" + esc(who) + "</span>" : ""}</div>`; };
    let html = `<h3>Medical ward</h3><div class="beds">`;
    for (const [id, b] of Object.entries(R.beds)) if (b.unit === "ward") html += tile(id, b);
    html += `</div><h3>Emergency department</h3><div class="beds">`;
    for (const [id, b] of Object.entries(R.beds)) if (b.unit === "ed") html += tile(id, b);
    html += "</div>";
    html += `<p class="note">${state.mode === "today" ? "Today: the ED learns a ward bed is ready when the ward phones (10–40 min after cleaning); cleaning is requested by phone 20–90 min after discharge." : "Connected: an emptied bed pages the cleaner at once and the ED sees ready beds live."}</p>`;
    $("pane-beds").innerHTML = html;
  }
  function occupant(bed, t) {
    let who = null;
    for (const m of M().log) { if (m.t > t) break; if (m.topic.endsWith(`/${bed}/state`)) who = m.text; }
    if (!who) return "";
    const mm = who.match(/^(.*?) (placed in|arrived in)/); return mm ? mm[1].split(" ")[0] : "";
  }
  function renderKit() {
    const t = state.t, tracked = state.mode === "connected", mt = M().metrics;
    let html = `<h3>Equipment ${tracked ? "· live locator" : "· not tracked"}</h3>`;
    html += `<p class="note">${tracked ? "Badges on every pump, chair and trolley: staff walk straight to the nearest free one." : "Nobody can see these locations in this rule set: staff look in the store first, then room by room. The map shows where things really are."}</p>`;
    html += `<table><tr><th>Item</th><th>Where</th><th>State</th></tr>`;
    for (const a of R.assets) {
      const at = assetAt(a.id, t); if (!at) continue;
      const room = at.b === "campus" ? "On the campus path" : ((ROOMS[at.b] && Object.values(ROOMS[at.b]).find((r) => at.x > r.rect[0] && at.x < r.rect[2] && at.y > r.rect[1] && at.y < r.rect[3])) || {}).name || at.b;
      const ev = (M().assetEv[a.id] || []).filter((e) => e[0] <= t).pop();
      const holder = ev && ev[5];
      const st = at.holder ? `carried by ${esc(M().agents[at.holder] ? M().agents[at.holder].name.split(" ")[0] : at.holder)}` : holder ? "on a patient" : "free";
      html += `<tr data-asset="${a.id}"><td>${esc(a.id)}</td><td>${esc(room)}${at.b === "ward" ? " (ward)" : at.b === "ed" ? "" : ""}</td><td class="${st === "free" ? "" : "muted"}">${st}</td></tr>`;
    }
    html += `</table><h3>Today so far is not counted here — whole day</h3><div class="row"><span>Fetches</span><b class="num">${mt.equipment_fetches}</b></div>`
      + `<div class="row"><span>Minutes searching (beyond the direct walk)</span><b class="num">${mt.equipment_search_min}</b></div>`
      + `<div class="row"><span>Drips run without a pump</span><b class="num">${mt.drips_without_pump} of ${mt.drips}</b></div>`
      + `<div class="row"><span>Free pumps in the ED at midnight</span><b class="num">${mt.ed_free_pumps_at_end}</b></div>`;
    $("pane-kit").innerHTML = html.replace("<h3>Today so far is not counted here — whole day</h3>", "<h3>Whole day</h3>");
  }
  let lastLogKey = "";
  function renderLog(force) {
    const t = state.t, only = $("only-key").checked;
    const items = M().log.filter((m) => m.t <= t && (!only || KEY_TOPIC.test(m.topic)));
    const key = state.mode + only + items.length;
    if (!force && key === lastLogKey) return;
    lastLogKey = key;
    $("log-count").textContent = `${items.length} shown`;
    const last = items.slice(-250).reverse();
    $("log").innerHTML = last.map((m) => `<li data-msg="${m.id}" class="${/alarm$|alert$|call$|door$|below_par$/.test(m.topic) ? "alert" : ""}"><span class="t num">${C.clock(m.t)}</span><span class="x">${esc(m.text)}</span></li>`).join("");
  }
  function renderInspector() {
    const sel = state.sel, t = state.t, body = $("inspect-body");
    if (!sel) { body.innerHTML = `<p class="muted">Pick someone or something above, or click the plan, the board or an event.</p>`; return; }
    let html = "";
    if (sel.type === "agent") {
      const a = M().agents[sel.id]; if (!a) { body.innerHTML = ""; return; }
      const at = agentAt(a, t), rec = M().rec[a.id];
      html += `<h3>${esc(a.name)} · ${ROLE_NAMES[a.role]}${a.unit ? ` (${a.unit === "ed" ? "Emergency" : "Ward"})` : ""}</h3>`;
      html += `<button class="btn" id="follow-btn" style="margin:2px 0 8px">${state.follow === a.id ? "Stop following" : "Follow on the map"}</button>`;
      html += `<div class="row"><span>Now</span><b>${esc(labelAt(a, t) || (at ? "" : "Not here"))}</b></div>`;
      if (at) html += `<div class="row"><span>Where</span><b>${esc(at.b === "campus" ? "Crossing the campus" : roomName(at.b, at.x, at.y))}</b></div>`;
      if (rec) {
        html += `<div class="row"><span>Triage</span><b><i class="chip" style="background:${tri(rec.colour)}"></i>${rec.colour}${rec.ambulance ? " · ambulance" : ""}</b></div>`;
        const steps = [["Arrived", rec.arrive], ["Registered", rec.registered], ["Triaged", rec.triaged], ["Seen by a doctor", rec.seen], ["Results back", rec.results], ["Decision to admit", rec.decision], ["Left (" + (rec.outcome || "") + ")", rec.left]];
        html += `<h3>Journey</h3>` + steps.filter(([, v]) => v != null).map(([k, v]) => `<div class="row"><span>${k}</span><b class="num ${v > t ? "muted" : ""}">${C.clock(v)}${v > t ? " (later)" : ""}</b></div>`).join("");
      }
      const hist = a.labels.filter((l) => l[0] <= t).slice(-8).reverse();
      html += `<h3>Recent</h3>` + hist.map(([tt, txt]) => `<div class="row"><span class="num muted">${C.clock(tt)}</span><span>${esc(txt)}</span></div>`).join("");
    } else if (sel.type === "bed") {
      const evs = (M().bedEv[sel.id] || []).filter((e) => e[0] <= t).slice(-10).reverse();
      html += `<h3>Bed ${esc(sel.id)}</h3>` + evs.map(([tt, st]) => `<div class="row"><span class="num muted">${C.clock(tt)}</span><span>${st}</span></div>`).join("");
      const msgs = M().log.filter((m) => m.t <= t && m.topic.includes(`/${sel.id}/`)).slice(-6).reverse();
      html += `<h3>Messages</h3>` + msgs.map((m) => `<div class="row" data-msg="${m.id}"><span class="num muted">${C.clock(m.t)}</span><span>${esc(m.text)}</span></div>`).join("");
    } else if (sel.type === "asset") {
      const evs = (M().assetEv[sel.id] || []).filter((e) => e[0] <= t).slice(-10).reverse();
      html += `<h3>${esc(sel.id)}</h3>` + evs.map((e) => `<div class="row"><span class="num muted">${C.clock(e[0])}</span><span>${e[5] ? (M().agents[e[5]] ? (M().agents[e[5]].role === "patient" ? "on " : "with ") + esc(M().agents[e[5]].name) : e[5]) : "left in " + esc(roomName(e[2], e[3], e[4]))}</span></div>`).join("");
    } else if (sel.type === "fridge") {
      const T = fridgeAt(sel.id, t), evs = M().fridge_events.filter((e) => e.fridge === sel.id && e.opened <= t);
      html += `<h3>${sel.id === "ed" ? "ED" : "Ward"} medicine fridge</h3><div class="row"><span>Now</span><b class="num">${T.toFixed(1)} °C</b></div>`;
      html += `<p class="note">${state.mode === "today" ? "Today: read and written down at 08:00 and 20:00; a door left ajar is found when someone next opens it." : "Connected: a probe reads every minute and alerts after 5 minutes above 8 °C."}</p>`;
      html += evs.map((e) => `<div class="row"><span>Door ajar ${C.clock(e.opened)}</span><b class="num">${e.closed != null && e.closed <= t ? "closed " + C.clock(e.closed) : "still open"} · peak ${e.peak.toFixed(1)} °C</b></div>`).join("");
    } else if (sel.type === "msg") {
      const chain = C.whyChain(M(), sel.id);
      html += `<h3>Why</h3><div class="why">${chain.map((m) => `<div><span class="t num">${C.clock(m.t)}</span>${esc(m.text)}</div>`).join("")}</div>`;
      if (chain.length === 1) html += `<p class="note">Nothing caused this inside the hospital: it came from outside (a patient, a monitor, a button).</p>`;
    }
    body.innerHTML = html;
  }
  function roomName(b, x, y) {
    if (!ROOMS[b]) return b;
    const r = Object.values(ROOMS[b]).find((q) => x > q.rect[0] && x < q.rect[2] && y > q.rect[1] && y < q.rect[3]);
    return r ? r.name : (b === "ed" ? "Emergency" : "Ward");
  }
  function fillFinder() {
    const opt = (v, txt) => `<option value="${v}">${esc(txt)}</option>`;
    const ag = Object.values(M().agents);
    $("find").innerHTML = `<option value="">—</option>`
      + `<optgroup label="Staff">${ag.filter((a) => a.role !== "patient").sort((a, b) => a.role.localeCompare(b.role) || a.name.localeCompare(b.name)).map((a) => opt("agent:" + a.id, `${ROLE_NAMES[a.role]} · ${a.name} (${a.unit})`)).join("")}</optgroup>`
      + `<optgroup label="Patients">${ag.filter((a) => a.role === "patient").map((a) => opt("agent:" + a.id, `${a.name}${a.triage ? " · " + a.triage : " · ward"}`)).join("")}</optgroup>`
      + `<optgroup label="Equipment">${R.assets.map((a) => opt("asset:" + a.id, a.id)).join("")}</optgroup>`
      + `<optgroup label="Beds">${Object.keys(R.beds).map((b) => opt("bed:" + b, b)).join("")}</optgroup>`
      + `<optgroup label="Fridges">${opt("fridge:ed", "ED fridge")}${opt("fridge:ward", "Ward fridge")}</optgroup>`;
  }
  const ROWS = [
    ["ED arrivals", "ed_arrivals", "info"],
    ["Door to triage, median min", "door_to_triage_min", "min"],
    ["Door to doctor, median min", "door_to_doctor_all_min", "min"],
    ["… red", (m) => m.door_to_doctor_min.red, "min"],
    ["… yellow", (m) => m.door_to_doctor_min.yellow, "min"],
    ["… green", (m) => m.door_to_doctor_min.green, "min"],
    ["Length of stay, median min", "los_min", "min"],
    ["Left without being seen", "left_unseen", "min"],
    ["Admitted to the ward", "admitted", "info"],
    ["Hours waiting for a ward bed", "boarding_hours", "min"],
    ["Call button answered, median min", "call_response_min", "min"],
    ["… 90th percentile min", "call_response_p90_min", "min"],
    ["HDU alarms that sounded", "alarms_sounded", "min"],
    ["… per nurse-hour", "alarms_per_nurse_hour", "min"],
    ["Walks to false alarms", "false_alarm_trips", "min"],
    ["Real alarm reached, median min", "true_alarm_response_min", "min"],
    ["Brief real events never sounded", "brief_true_events_not_sounded", "cost"],
    ["Minutes searching for equipment", "equipment_search_min", "min"],
    ["Drips without a pump", "drips_without_pump", "min"],
    ["Free ED pumps at midnight", "ed_free_pumps_at_end", "max"],
    ["Hand hygiene, true %", "hand_hygiene_true_pct", "info"],
    ["Hand hygiene, as reported %", "hand_hygiene_reported_pct", "info"],
    ["Fridge minutes above 8 °C", "fridge_minutes_over_8C", "min"],
    ["Bed turnaround, median min", "bed_turnaround_min", "min"],
    ["Ward nurses walked, km", "ward_nurse_km", "min"],
  ];
  function renderCompare() {
    const names = Object.keys(R.modes), ms = names.map((n) => R.modes[n].metrics);
    let html = `<h3>Whole day, same patients, same events</h3><table class="cmp"><tr><th></th>${names.map((n) => `<th>${MODE_NAMES[n]}</th>`).join("")}</tr>`;
    for (const [label, key, dir] of ROWS) {
      const vals = ms.map((m) => (typeof key === "function" ? key(m) : m[key]));
      const nums = vals.filter((v) => v != null);
      const best = dir === "min" ? Math.min(...nums) : dir === "max" ? Math.max(...nums) : null;
      const allSame = nums.every((v) => v === nums[0]);
      html += `<tr><td>${label}</td>${vals.map((v) => `<td class="num ${dir === "cost" && v ? "cost" : ""} ${!allSame && v === best ? "best" : ""}">${v == null ? "–" : Number.isInteger(v) ? v.toLocaleString("en") : v.toFixed(1)}</td>`).join("")}</tr>`;
    }
    html += `</table>`;
    const td = R.modes.today.metrics, cn = R.modes.connected.metrics;
    html += `<p class="note">Hand hygiene: staff really washed ${td.hand_hygiene_true_pct}% / ${cn.hand_hygiene_true_pct}% of the time in both. Today's figure comes from a one-hour audit (${td.hand_hygiene_reported_n} observations, staff wash more when watched); Connected counts ${cn.hand_hygiene_reported_n} dispenser uses against badge entries. Badges are not assumed to change behaviour.</p>`;
    html += `<p class="note">The 15-second alarm delay is not free: ${cn.brief_true_events_not_sounded} brief real desaturations ended before it ran out and never sounded (orange). Critical alarms skip the delay (reached in ${cn.critical_response_s.join(" and ")} s).</p>`;
    html += `<p class="note">Simulated hospital, not a measurement: arrival mix, call rates, alarm rates and fridge events are assumptions or published figures listed in PLAN.md. Green = better.</p>`;
    $("pane-compare").innerHTML = html;
  }

  // ---- timeline ----
  function renderTimeline() {
    const w = tl.clientWidth, h = tl.clientHeight, cen = M().census;
    tctx.clearRect(0, 0, w, h);
    const xs = (t) => w * t / 86400;
    const max = Math.max(10, ...cen.map((c) => c[1]));
    const line = (k, col, wd) => { tctx.strokeStyle = col; tctx.lineWidth = wd; tctx.beginPath(); cen.forEach((c, i) => { const x = xs(c[0]), y = (h - 14) * (1 - c[k] / max) + 2; i ? tctx.lineTo(x, y) : tctx.moveTo(x, y); }); tctx.stroke(); };
    line(1, palette.accent, 1.6); line(2, palette.muted, 1.2); line(3, palette.warn, 1.2);
    for (const a of M().alarms) if (a.annunciated != null) { tctx.fillStyle = rgba(palette.alert, a.kind === "artefact" ? 0.45 : 1); tctx.fillRect(xs(a.annunciated) - 0.5, h - 9, 1.5, 7); }
    for (const e of M().fridge_events) { tctx.fillStyle = rgba(palette.water, 0.4); tctx.fillRect(xs(e.opened), h - 3, Math.max(2, xs(e.closed || 86400) - xs(e.opened)), 3); }
    tctx.fillStyle = palette.accent; tctx.fillRect(xs(state.t) - 1.5, 0, 3, h);
  }
  function renderLegend() {
    const roles = ["doctor", "nurse", "porter", "cleaner", "clerk"].map((r) => `<span><i style="background:${R.roles[r]}"></i>${ROLE_NAMES[r]}</span>`).join("");
    const triage = ["red", "orange", "yellow", "green", "blue"].map((c) => `<span><i style="background:${tri(c)}"></i>${c[0].toUpperCase() + c.slice(1)}</span>`).join("");
    const kit = `<span><i class="sq" style="background:${rgba(palette.water, 0.5)};border:1.5px solid ${palette.water}"></i>Pump ◆ chair ● trolley ▬</span>`;
    const extra = state.view === "ward" ? `<span><i class="sq" style="border:2px solid ${palette.call};background:transparent"></i>Call button</span><span><i style="border:2px solid ${palette.alert};background:transparent"></i>Alarm</span>`
      : state.view === "site" ? `<span><i class="sq" style="background:${palette.accent}"></i>Simulated floors · dashed: campus path (${R.site.path_m} m)</span>` : `<span><i class="sq" style="border:2px solid ${palette.warn};background:transparent"></i>Bed to clean</span>`;
    $("legend").innerHTML = (state.view === "site" ? "" : triage) + roles + kit + extra;
    const out = []; for (let hh = 0; hh <= 24; hh += 2) out.push(`<span>${String(hh).padStart(2, "0")}</span>`); $("ticks").innerHTML = out.join("");
  }

  // ---- loop ----
  let lastPanel = 0;
  function frame(force) {
    $("clock").textContent = C.clock(state.t); scrub.value = state.t;
    followCamera(); renderFloors();
    draw(); renderTimeline(); kpis();
    const nowT = performance.now();
    if (force || nowT - lastPanel > 300) {
      lastPanel = nowT; renderLog(force);
      if ($("pane-board").classList.contains("on")) renderBoard();
      if ($("pane-beds").classList.contains("on")) renderBeds();
      if ($("pane-kit").classList.contains("on")) renderKit();
      if ($("pane-inspect").classList.contains("on")) renderInspector();
    }
  }
  let prev = null;
  function loop(ts) {
    if (state.playing) {
      if (prev != null) state.t = Math.min(86399, state.t + ((ts - prev) / 1000) * state.speed);
      if (state.t >= 86399) setPlaying(false);
      frame(false);
    } else if (openAlarms(state.t).length && state.view !== "site") draw();      // keep alarms pulsing while paused
    prev = ts; requestAnimationFrame(loop);
  }
  function setPlaying(on) { state.playing = on; $("play").textContent = on ? "❚❚ Pause" : "▶ Play"; $("play").setAttribute("aria-label", on ? "Pause" : "Play"); }
  function save() { try { localStorage.setItem("hospital-twin", JSON.stringify({ theme: document.documentElement.dataset.theme, mode: state.mode, view: state.view })); } catch (e) { /* ignore */ } }
  function showTab(name) {
    for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", b.dataset.tab === name);
    for (const p of document.querySelectorAll(".pane")) p.classList.toggle("on", p.id === "pane-" + name);
    if (name === "compare") renderCompare();
    frame(true);
  }
  function renderFloors() {
    const box = $("floors");
    if (state.view === "site") { box.style.display = "none"; return; }
    box.style.display = "";
    const t = state.t, count = {};
    for (const a of Object.values(M().agents)) { const at = agentAt(a, t); if (at && at.b === state.view) { const f = floorOf(at.b, at.x, at.y); count[f] = (count[f] || 0) + 1; } }
    const fl = [...FLOORS[state.view]].sort((p, q) => q.level - p.level);
    const html = fl.map((f) => `<button data-floor="${f.id}" aria-pressed="${f.id === state.floor[state.view]}" title="${esc(f.name)}: ${count[f.id] || 0} people now">${f.id} <span class="muted num">(${count[f.id] || 0})</span></button>`).join("");
    if (box.dataset.html !== html) { box.innerHTML = html; box.dataset.html = html; }
  }
  function setFloor(f) { state.floor[state.view] = f; fit(); frame(true); }
  function setView(v, floor) {
    state.view = v;
    if (floor) state.floor[v] = floor;
    for (const x of document.querySelectorAll("#views button")) x.setAttribute("aria-pressed", x.dataset.view === v);
    fit(); renderLegend(); save(); frame(true);
  }
  // follow mode: keep the selected person on screen across buildings and floors, like a game map
  function followCamera() {
    if (!state.follow) return;
    const a = M().agents[state.follow], at = a && agentAt(a, state.t);
    if (!at) return;
    if (at.b === "campus") { if (state.view !== "site") setView("site"); return; }
    const f = floorOf(at.b, at.x, at.y);
    if (state.view !== at.b || state.floor[at.b] !== f) setView(at.b, f);
  }

  $("play").onclick = () => { if (state.t >= 86399) state.t = 0; setPlaying(!state.playing); };
  $("speed").onchange = (e) => { state.speed = +e.target.value; };
  scrub.oninput = () => { state.t = +scrub.value; frame(true); };
  for (const b of document.querySelectorAll("#modes button")) {
    b.setAttribute("aria-pressed", b.dataset.mode === state.mode);
    b.onclick = () => { state.mode = b.dataset.mode; for (const x of document.querySelectorAll("#modes button")) x.setAttribute("aria-pressed", x === b); lastLogKey = ""; save(); fillFinder(); frame(true); };
  }
  for (const b of document.querySelectorAll("#views button")) b.onclick = () => { state.follow = null; setView(b.dataset.view); };
  $("floors").onclick = (e) => { const b = e.target.closest("button[data-floor]"); if (b) { state.follow = null; setFloor(b.dataset.floor); } };
  for (const b of document.querySelectorAll(".tabs button")) b.onclick = () => showTab(b.dataset.tab);
  $("only-key").onchange = () => renderLog(true);
  const select = (sel) => { state.sel = sel; showTab("inspect"); };
  $("log").onclick = (e) => { const li = e.target.closest("li[data-msg]"); if (li) select({ type: "msg", id: +li.dataset.msg }); };
  $("pane-board").onclick = (e) => { const tr = e.target.closest("tr[data-agent]"); if (tr) select({ type: "agent", id: tr.dataset.agent }); };
  $("pane-beds").onclick = (e) => { const d = e.target.closest("[data-bed]"); if (d) select({ type: "bed", id: d.dataset.bed }); };
  $("pane-kit").onclick = (e) => { const tr = e.target.closest("tr[data-asset]"); if (tr) select({ type: "asset", id: tr.dataset.asset }); };
  $("inspect-body").onclick = (e) => {
    if (e.target.id === "follow-btn" && state.sel && state.sel.type === "agent") { state.follow = state.follow === state.sel.id ? null : state.sel.id; frame(true); return; }
    const d = e.target.closest("[data-msg]"); if (d) select({ type: "msg", id: +d.dataset.msg });
  };
  $("find").onchange = (e) => { const v = e.target.value; if (!v) return; const [type, id] = v.split(/:(.*)/s); state.sel = { type, id }; frame(true); };
  $("theme").onclick = () => { const d = document.documentElement.dataset.theme !== "light"; document.documentElement.dataset.theme = d ? "light" : "dark"; $("theme").textContent = d ? "Dark" : "Light"; readPalette(); renderLegend(); save(); if ($("pane-compare").classList.contains("on")) renderCompare(); frame(true); };
  function pick(ev) {
    const rect = cv.getBoundingClientRect(), mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    let best = null, bd = Infinity;
    for (const h of hits) { const d = Math.hypot(h.x - mx, h.y - my); if (d < h.r && d < bd) { bd = d; best = h; } }
    if (best) return { type: best.type, id: best.id };
    if (state.view === "site") return null;
    const wx = (mx - view.ox) / view.s, wy = (my - view.oy) / view.s;
    const [gx, gy] = [wx + curFloor().origin[0], wy + curFloor().origin[1]];
    for (const [id, b] of Object.entries(R.beds)) if (b.unit === state.view && Math.abs(gx - b.spot[0]) < 0.6 && Math.abs(gy - b.spot[1]) < 1.0) return { type: "bed", id };
    return null;
  }
  cv.addEventListener("click", (ev) => {
    const p = pick(ev);
    if (p && p.type === "portal") return;
    if (p) select(p); else { state.sel = null; frame(true); }
  });
  cv.addEventListener("mousemove", (ev) => {
    const p = pick(ev), tip = $("tip"); if (!p) { tip.style.display = "none"; return; }
    const rect = cv.getBoundingClientRect(), t = state.t; let html = "";
    if (p.type === "agent") { const a = M().agents[p.id], rec = M().rec[p.id]; html = `<b>${esc(a.name)}</b> · ${ROLE_NAMES[a.role]}${rec && rec.triaged != null && rec.triaged <= t ? " · " + rec.colour : ""}<br><span class="muted">${esc(labelAt(a, t))}</span>`; }
    else if (p.type === "asset") { const at = assetAt(p.id, t); html = `<b>${esc(p.id)}</b><br><span class="muted">${at && at.holder ? "with " + esc(M().agents[at.holder].name) : "here"}</span>`; }
    else if (p.type === "bed") { const st = bedAt(p.id, t); html = `<b>${esc(p.id)}</b><br><span class="muted">${st.state} since ${C.clock(st.since)}</span>`; }
    else if (p.type === "fridge") html = `<b>Medicine fridge</b><br><span class="muted">${fridgeAt(p.id, t).toFixed(1)} °C</span>`;
    else if (p.type === "portal") html = `<b>${esc(hits.find((h) => h.id === p.id).text)}</b>`;
    tip.innerHTML = html; tip.style.display = "block";
    tip.style.left = Math.min(ev.clientX - rect.left + 14, rect.width - tip.offsetWidth - 6) + "px";
    tip.style.top = Math.min(ev.clientY - rect.top + 14, rect.height - tip.offsetHeight - 6) + "px";
  });
  cv.addEventListener("mouseleave", () => { $("tip").style.display = "none"; });
  document.addEventListener("keydown", (e) => {
    if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
    // a focused button keeps Space for itself; the other shortcuts still work after a click
    if (e.code === "Space" && e.target.tagName !== "BUTTON") { e.preventDefault(); $("play").click(); }
    if (e.key === "ArrowRight") { state.t = Math.min(86399, state.t + 900); frame(true); }
    if (e.key === "ArrowLeft") { state.t = Math.max(0, state.t - 900); frame(true); }
    if (e.key === "1") setView("site"); if (e.key === "2") setView("ed"); if (e.key === "3") setView("ward");
  });
  window.addEventListener("resize", () => { fit(); frame(true); });

  $("theme").textContent = document.documentElement.dataset.theme === "light" ? "Dark" : "Light";
  for (const x of document.querySelectorAll("#views button")) x.setAttribute("aria-pressed", x.dataset.view === state.view);
  readPalette(); fit(); fillFinder(); renderLegend(); frame(true); requestAnimationFrame(loop);
  window.__hosp = { state, frame, showTab, setView, setFloor, floorOf, hits: () => hits, agentAt, assetAt, bedAt, openAlarms, openCalls, get modes() { return modes; } };
})();

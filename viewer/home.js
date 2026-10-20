/* Home Twin viewer: replays one simulated day of the house from window.HOME.
 * Pure helpers come from core.js (TwinCore). Nothing here re-simulates: power,
 * temperatures and the battery are the simulator's minute samples; device states
 * are the controller's commands; "why" follows each message's cause.
 */
"use strict";

(function () {
  // one replay per season; the plan and appliances are the same house in both
  const SCEN = window.HOME_SCENARIOS || { june: window.HOME };
  let season = SCEN.june ? "june" : Object.keys(SCEN)[0];
  let H = SCEN[season];
  const C = TwinCore;
  const plan = H.plan;
  const rooms = Object.fromEntries(plan.rooms.map((r) => [r.id, r]));
  const APPS = Object.fromEntries(H.appliances.map((a) => [a.id, a]));
  const MODE_NAMES = { default: "Inverter default", ups: "UPS circuit", gridsense_eco: "GridSense eco", gridsense: "GridSense" };
  const ROLE_NAMES = { father: "Father", mother: "Mother", grandmother: "Dadi", school: "School child", student: "University student", helper: "Helper", relative: "Relative visiting", grandparent: "Nana / Nani visiting" };

  // ---- index (rebuilt when the season changes) ----
  let people = {}, modes = {};
  function index() {
    people = {};
    for (const p of H.people) people[p.id] = { ...p, trips: [], labels: [], gone: p.leave < 86400 ? p.leave + 600 : Infinity, entry: null };
    for (const tr of H.trips) people[tr.p].trips.push(tr);
    for (const [t, pid, label] of H.labels) people[pid].labels.push([t, label]);
    for (const p of Object.values(people)) { p.trips.sort((a, b) => a.t - b.t); }
    modes = {};
    for (const [name, M] of Object.entries(H.modes)) {
      const dev = {};
      for (const [t, aid, val, id] of M.devices) (dev[aid] = dev[aid] || []).push([t, val, id]);
      const byId = {};
      for (const m of M.log) byId[m.id] = m;
      modes[name] = { ...M, dev, byId, wired: new Set(H.wiring[name]) };
    }
  }
  index();

  const state = { t: 21.5 * 3600, mode: "gridsense", layer: "state", playing: false, speed: 300, sel: null, floor: "G" };
  // floors: the house is double-storey with a roof; one floor is drawn at a time
  const FLOORS = plan.floors && plan.floors.length ? plan.floors : [{ id: "G", name: "Ground floor", level: 0, origin: [0, 0], size: plan.size }];
  C.setHops(plan.portal_hops);
  const F = () => FLOORS.find((f) => f.id === state.floor) || FLOORS[0];
  function floorOf(x, y) {
    for (const f of FLOORS) { const [ox, oy] = f.origin; if (x >= ox && x <= ox + f.size[0] && y >= oy && y <= oy + f.size[1]) return f.id; }
    return FLOORS[0].id;
  }
  const onFloor = (x, y) => floorOf(x, y) === F().id;
  const roomOnFloor = (rid) => !rooms[rid] || (rooms[rid].floor || FLOORS[0].id) === F().id;
  try {
    const saved = JSON.parse(localStorage.getItem("home-twin") || "{}");
    if (saved.theme) document.documentElement.dataset.theme = saved.theme;
    if (saved.mode && H.modes[saved.mode]) state.mode = saved.mode;
    if (saved.season && SCEN[saved.season]) { season = saved.season; H = SCEN[season]; index(); }
  } catch (e) { /* storage blocked: defaults are fine */ }

  const $ = (id) => document.getElementById(id);
  const cv = $("plan"), ctx = cv.getContext("2d");
  const tl = $("tl"), tctx = tl.getContext("2d");
  const scrub = $("scrub");
  let palette = {};
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  function readPalette() {
    for (const k of ["bg", "panel", "panel-2", "floor", "floor-out", "wall", "desk", "light", "ac", "ok", "alert", "text", "muted", "line", "people", "accent", "solar", "battery", "grid", "outage", "water"]) palette[k] = css("--" + k);
  }
  function hex(c) {
    if (c.startsWith("rgb")) return c.match(/\d+/g).slice(0, 3).map(Number);
    c = c.replace("#", ""); if (c.length === 3) c = c.split("").map((x) => x + x).join("");
    return [0, 2, 4].map((i) => parseInt(c.slice(i, i + 2), 16));
  }
  const rgba = (c, a) => { const [r, g, b] = hex(c); return `rgba(${r},${g},${b},${a})`; };
  const mix = (a, b, f) => { const pa = hex(a), pb = hex(b); return `rgb(${pa.map((v, i) => Math.round(v + (pb[i] - v) * f)).join(",")})`; };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const si = () => Math.max(0, Math.min(H.modes.default.series.t.length - 1, Math.floor(state.t / 60)));
  const M = () => modes[state.mode];

  function gridUp(t) { return !H.outages.some((o) => o.start <= t && t < o.end); }
  function cmdOn(aid, t) {
    const arr = M().dev[aid];
    if (!arr) return aid === "fridge" || aid === "router";
    const i = C.bisectRight(arr, t, (c) => c[0]) - 1;
    return i >= 0 ? !!arr[i][1] : (aid === "fridge" || aid === "router");
  }
  function cmdSince(aid, t) {
    const arr = M().dev[aid]; if (!arr) return null;
    const i = C.bisectRight(arr, t, (c) => c[0]) - 1;
    return i >= 0 ? { on: !!arr[i][1], since: arr[i][0], id: arr[i][2] } : null;
  }
  // a device is live when commanded on, and there is power on its circuit
  function powered(aid, t) {
    const S = M().series, i = Math.min(S.t.length - 1, Math.floor(t / 60));
    if (gridUp(t)) return true;
    if (!M().wired.has(aid)) return false;
    return !S.dark[i];
  }
  const live = (aid, t) => cmdOn(aid, t) && powered(aid, t);

  function personAt(p, t) {
    if (t < p.arrive || t >= p.gone) return null;
    const label = C.labelAt(p, t);
    const at = C.personAt({ ...p, gone: Infinity }, t) || (p.trips.length ? null : null);
    if (!at) return null;
    if ((label.startsWith("Out") || label === "Leaving") && !at.moving) return null;
    return at;
  }

  // ---- geometry ----
  let view = { s: 10, ox: 0, oy: 0 };
  function fit() {
    const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const [W, Hh] = F().size, top = 56, bottom = w < 700 ? 12 : 58, side = 20;
    const s = Math.min((w - side * 2) / W, (h - top - bottom) / Hh);
    view = { s, ox: (w - W * s) / 2, oy: top + (h - top - bottom - Hh * s) / 2 };
    tl.width = Math.round(tl.clientWidth * dpr); tl.height = Math.round(tl.clientHeight * dpr); tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  const X = (x) => view.ox + (x - F().origin[0]) * view.s, Y = (y) => view.oy + (y - F().origin[1]) * view.s;

  function tempColour(T) {
    const f = Math.max(0, Math.min(1, (T - 24) / 14));
    return f < 0.5 ? mix("#38bdf8", "#a3e635", f * 2) : mix("#a3e635", "#f87171", (f - 0.5) * 2);
  }

  // ---- plan ----
  let hits = [];
  function draw() {
    const w = cv.clientWidth, h = cv.clientHeight, s = view.s, t = state.t, i = si();
    const S = M().series;
    ctx.clearRect(0, 0, w, h);
    const dark = !gridUp(t) && S.dark[i];
    const RM = plan.rooms.filter((r) => roomOnFloor(r.id));
    for (const r of RM) {
      const [x0, y0, x1, y1] = r.rect;
      let fill = r.kind === "outdoor" ? palette["floor-out"] : palette.floor;
      if (r.kind !== "outdoor") {
        if (state.layer === "temp" && S.temp[r.id]) fill = mix(palette.floor, tempColour(S.temp[r.id][i]), 0.55);
        else if (state.layer === "occ" && S.occ[r.id] && S.occ[r.id][i] > 0) fill = mix(palette.floor, palette.people, Math.min(0.7, 0.25 + 0.15 * S.occ[r.id][i]));
      }
      ctx.fillStyle = fill;
      ctx.fillRect(X(x0), Y(y0), (x1 - x0) * s, (y1 - y0) * s);
      if (state.layer === "state" && r.kind !== "outdoor" && live(`light:${r.id}`, t)) {
        const cx = X((x0 + x1) / 2), cy = Y((y0 + y1) / 2), rad = Math.hypot(x1 - x0, y1 - y0) * s * 0.6;
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, rad);
        g.addColorStop(0, rgba(palette.light, 0.32)); g.addColorStop(1, rgba(palette.light, 0.08));
        ctx.fillStyle = g; ctx.fillRect(X(x0), Y(y0), (x1 - x0) * s, (y1 - y0) * s);
      }
      if (state.layer === "state" && live(`ac:${r.id}`, t)) {
        ctx.strokeStyle = rgba(palette.ac, 0.9); ctx.lineWidth = 2; ctx.setLineDash([5, 4]);
        ctx.strokeRect(X(x0) + 4, Y(y0) + 4, (x1 - x0) * s - 8, (y1 - y0) * s - 8); ctx.setLineDash([]);
      }
    }
    for (const f of plan.furniture || []) {
      const [fx, fy, fw, fh] = f.rect; if (!onFloor(fx, fy)) continue;
      ctx.fillStyle = palette.desk; rr(X(fx), Y(fy), fw * s, fh * s, (f.radius || 0) * s);
      if (/solar panels/.test(f.what)) {
        // panel cells glow with the solar output right now
        const kw = S.pv_kw[i], g = Math.min(1, kw / 5);
        ctx.fillStyle = rgba(palette.solar, 0.12 + 0.55 * g); ctx.fillRect(X(fx), Y(fy), fw * s, fh * s);
        ctx.strokeStyle = palette.bg; ctx.lineWidth = 1;
        for (let cx = fx + fw / 6; cx < fx + fw - 0.01; cx += fw / 6) { ctx.beginPath(); ctx.moveTo(X(cx), Y(fy)); ctx.lineTo(X(cx), Y(fy + fh)); ctx.stroke(); }
        for (let cy = fy + fh / 3; cy < fy + fh - 0.01; cy += fh / 3) { ctx.beginPath(); ctx.moveTo(X(fx), Y(cy)); ctx.lineTo(X(fx + fw), Y(cy)); ctx.stroke(); }
        ctx.fillStyle = palette.text; ctx.font = `600 ${Math.max(10, s * 0.4)}px Segoe UI`; ctx.textAlign = "center";
        ctx.fillText(`Solar ${kw.toFixed(2)} kW`, X(fx + fw / 2), Y(fy + fh / 2));
      } else if (/water tank/.test(f.what)) {
        const lv = S.tank[i], r = fw * s / 2, cx = X(fx + fw / 2), cy = Y(fy + fh / 2);
        ctx.save(); ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.clip();
        ctx.fillStyle = rgba(palette.water, 0.75); ctx.fillRect(cx - r, cy + r - 2 * r * lv, 2 * r, 2 * r * lv); ctx.restore();
        ctx.fillStyle = palette.text; ctx.font = `600 ${Math.max(10, s * 0.38)}px Segoe UI`; ctx.textAlign = "center";
        ctx.fillText(`Tank ${(lv * 100).toFixed(0)}%`, cx, cy + r + Math.max(12, s * 0.45));
      }
    }
    // walls and doors
    ctx.strokeStyle = palette.wall; ctx.lineWidth = Math.max(2, s * 0.14);
    for (const r of RM) { if (r.kind === "outdoor") continue; const [x0, y0, x1, y1] = r.rect; ctx.strokeRect(X(x0), Y(y0), (x1 - x0) * s, (y1 - y0) * s); }
    for (const d of plan.doors) {
      if (!roomOnFloor(d.a)) continue;
      const out = rooms[d.a].kind === "outdoor" || rooms[d.b].kind === "outdoor";
      ctx.strokeStyle = out ? palette["floor-out"] : palette.floor; ctx.lineWidth = Math.max(3, s * 0.18); ctx.beginPath();
      if (d.axis === "x") { ctx.moveTo(X(d.lo), Y(d.at)); ctx.lineTo(X(d.hi), Y(d.at)); } else { ctx.moveTo(X(d.at), Y(d.lo)); ctx.lineTo(X(d.at), Y(d.hi)); }
      ctx.stroke();
    }
    drawAppliances(t);
    // stairs on this floor, saying where they lead
    for (const pt of plan.portals || []) {
      const at = pt.at[F().id]; if (!at) continue;
      const x = X(at[0]), y = Y(at[1]), r = Math.max(7, s * 0.55);
      ctx.fillStyle = palette["panel-2"]; ctx.strokeStyle = palette.accent; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.rect(x - r, y - r, 2 * r, 2 * r); ctx.fill(); ctx.stroke();
      ctx.fillStyle = palette.accent; ctx.font = `700 ${Math.max(8, r)}px Segoe UI`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("▤", x, y + 0.5); ctx.textBaseline = "alphabetic";
    }
    // labels
    for (const r of RM) {
      const [x0, y0, x1, y1] = r.rect, fs = Math.max(9, Math.min(13, s * 0.42));
      ctx.font = `600 ${fs}px Segoe UI, system-ui`; ctx.textAlign = "center";
      ctx.fillStyle = state.layer === "state" || r.kind === "outdoor" ? palette.muted : palette.text;
      let label = r.name; const room = (x1 - x0) * s - 6;
      if (ctx.measureText(label).width > room) label = (plan.short_names || {})[r.id] || r.name;
      if (ctx.measureText(label).width > room) label = "";
      if (r.kind === "corridor" && (y1 - y0) > (x1 - x0)) {
        ctx.save(); ctx.translate(X((x0 + x1) / 2) + fs * 0.35, Y((y0 + y1) / 2)); ctx.rotate(-Math.PI / 2); ctx.fillText(r.name, 0, 0); ctx.restore();
      } else if (label) ctx.fillText(label, X((x0 + x1) / 2), Y(y0) + fs + 4);
      if (state.layer === "temp" && S.temp[r.id]) { ctx.fillStyle = palette.text; ctx.fillText(S.temp[r.id][i].toFixed(1) + "°", X((x0 + x1) / 2), Y(y0) + fs * 2 + 7); }
      if (state.sel && state.sel.type === "room" && state.sel.id === r.id) { ctx.strokeStyle = palette.accent; ctx.lineWidth = 3; ctx.strokeRect(X(x0) + 1.5, Y(y0) + 1.5, (x1 - x0) * s - 3, (y1 - y0) * s - 3); }
    }
    for (const l of plan.labels || []) { if (!onFloor(l.at[0], l.at[1])) continue; ctx.fillStyle = palette.muted; ctx.textAlign = "left"; ctx.fillText(l.text, X(l.at[0]), Y(l.at[1])); }
    if (dark) {
      ctx.fillStyle = "rgba(0,0,0,0.45)";
      for (const r of RM) if (r.kind !== "outdoor") { const [x0, y0, x1, y1] = r.rect; ctx.fillRect(X(x0), Y(y0), (x1 - x0) * s, (y1 - y0) * s); }
      const why = (S.dark_reason && S.dark_reason[i] === "overload") ? "inverter overloaded" : "battery at cut-off";
      ctx.fillStyle = palette.outage; ctx.font = `700 ${Math.max(12, s * 0.62)}px Segoe UI, system-ui`; ctx.textAlign = "center";
      ctx.fillText(`House dark — ${why}`, X(F().origin[0] + F().size[0] / 2), Y(F().origin[1] + 3.6));
    }
    drawPeople(t);
  }
  function rr(x, y, w, h, r) { ctx.beginPath(); ctx.roundRect ? ctx.roundRect(x, y, w, h, r) : ctx.rect(x, y, w, h); ctx.fill(); }

  function appPos(a) {
    const r = rooms[a.room]; if (!r) return null;
    const [x0, y0, x1, y1] = r.rect, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const spot = { fridge: "fridge", pump: "pump", washer: "washer", iron: "iron" }[a.kind];
    // the spot is where the user stands; a machine they attend (washer, iron, pump) sits 0.6 m beside it, towards the room's
    // middle, or the person using it hides it at exactly the moment it is running
    if (spot && plan.spots[spot]) { const [sx, sy] = plan.spots[spot][0]; return a.kind === "fridge" ? [sx, sy] : [sx + (sx < cx ? 0.6 : -0.6), sy]; }
    if (a.kind === "fan") return [cx, cy];
    if (a.kind === "ac") return [x1 - 0.95, y1 - 0.45];   // bottom-right corner: room names own the top edge
    if (a.kind === "tv") return [cx, y1 - 0.9];
    if (a.kind === "router") return [x1 - 0.5, y0 + 0.5];
    if (a.kind === "microwave") return [x0 + 0.6, y0 + 0.6];
    return null;
  }
  function drawAppliances(t) {
    const s = view.s, spin = (t / 2) % (Math.PI * 2);
    for (const a of H.appliances) {
      if (a.kind === "light" || !roomOnFloor(a.room)) continue;
      const p = appPos(a); if (!p) continue;
      const on = live(a.id, t), wanted = cmdOn(a.id, t), x = X(p[0]), y = Y(p[1]);
      const col = on ? ({ fan: palette.text, ac: palette.ac, pump: palette.water, washer: palette.text, iron: palette.alert, fridge: palette.ok, tv: palette.people, router: palette.ok, microwave: palette.alert }[a.kind] || palette.text) : palette.muted;
      ctx.globalAlpha = on ? 1 : (wanted ? 0.9 : 0.45);
      ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 1.6;
      if (a.kind === "fan") {
        const r = Math.max(5, s * 0.38);
        for (let k = 0; k < 3; k++) { const ang = (on ? spin : 0) + k * 2.094; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + r * Math.cos(ang), y + r * Math.sin(ang)); ctx.stroke(); }
        ctx.beginPath(); ctx.arc(x, y, 2, 0, 7); ctx.fill();
      } else if (a.kind === "ac") {
        ctx.strokeRect(x - s * 0.7, y - s * 0.18, s * 1.4, s * 0.36);
        if (on) { ctx.globalAlpha = 0.25; ctx.fillRect(x - s * 0.7, y - s * 0.18, s * 1.4, s * 0.36); }
      } else {
        const r = Math.max(4, s * 0.22); ctx.beginPath(); ctx.roundRect ? ctx.roundRect(x - r, y - r, 2 * r, 2 * r, 2) : ctx.rect(x - r, y - r, 2 * r, 2 * r);
        on ? ctx.fill() : ctx.stroke();
      }
      if (wanted && !on) { ctx.globalAlpha = 1; ctx.strokeStyle = palette.outage; ctx.beginPath(); ctx.moveTo(x - 5, y - 5); ctx.lineTo(x + 5, y + 5); ctx.stroke(); }
      ctx.globalAlpha = 1;
    }
  }
  function drawPeople(t) {
    const r = Math.max(3.5, view.s * 0.3); hits = [];
    for (const p of Object.values(people)) {
      const at = personAt(p, t); if (!at || !onFloor(at.x, at.y)) continue;
      hits.push({ p, x: X(at.x), y: Y(at.y) });
      const sel = state.sel && state.sel.type === "person" && state.sel.id === p.id;
      const asleep = /Asleep|nap/.test(C.labelAt(p, t));
      ctx.beginPath(); ctx.arc(X(at.x), Y(at.y), sel ? r * 1.35 : r, 0, Math.PI * 2);
      ctx.fillStyle = asleep ? rgba(p.colour, 0.55) : p.colour; ctx.fill();
      ctx.lineWidth = sel ? 3 : 1.5; ctx.strokeStyle = sel ? palette.text : palette.bg; ctx.stroke();
    }
  }

  // ---- power flow card ----
  function drawFlow() {
    const S = M().series, i = si();
    const pv = S.pv_kw[i], load = S.load_kw[i], g = S.grid_kw[i], b = S.batt_kw[i], soc = S.soc[i], up = !!S.grid_up[i];
    const node = (x, y, label, val, sub) => `<g class="node"><rect x="${x - 52}" y="${y - 22}" width="104" height="44" rx="9"/><text x="${x}" y="${y - 4}" text-anchor="middle">${label}</text><text class="sub" x="${x}" y="${y + 13}" text-anchor="middle">${val}${sub ? " · " + sub : ""}</text></g>`;
    const wire = (d, cls, active, reverse) => {
      const base = `<path class="wire" d="${d}"/>`;
      if (!active) return base;
      return base + `<path class="live ${cls}" d="${d}"><animate attributeName="stroke-dashoffset" from="${reverse ? 0 : 28}" to="${reverse ? 28 : 0}" dur="1s" repeatCount="indefinite"/></path>`;
    };
    const cx = 180, cy = 95;
    let svg = "";
    svg += wire(`M${cx} 47 L${cx} ${cy - 16}`, "solar", pv > 0.05, false);
    svg += up ? wire(`M76 ${cy} L${cx - 16} ${cy}`, "grid", Math.abs(g) > 0.05, g < 0) : `<path class="wire down" d="M76 ${cy} L${cx - 16} ${cy}"/>`;
    svg += wire(`M${cx} ${cy + 16} L${cx} 143`, "battery", Math.abs(b) > 0.05, b > 0);
    svg += wire(`M${cx + 16} ${cy} L284 ${cy}`, "home", load > 0.02, false);
    svg += `<circle cx="${cx}" cy="${cy}" r="16" fill="var(--panel-2)" stroke="var(--line)"/><text x="${cx}" y="${cy + 4}" text-anchor="middle" style="fill:var(--muted);font:600 10px Segoe UI">INV</text>`;
    const cut = S.curtailed_kw ? S.curtailed_kw[i] : 0;
    svg += node(cx, 25, "Solar", pv.toFixed(2) + " kW", cut > 0.05 ? cut.toFixed(2) + " kW wasted" : "");
    svg += node(52, cy, up ? "Grid" : "Grid down", up ? (g >= 0 ? g.toFixed(2) + " kW in" : (-g).toFixed(2) + " kW out") : "outage", up ? S.volts[i].toFixed(0) + " V" : "");
    svg += node(cx, 165, "Battery", (soc * 100).toFixed(0) + "%", b > 0.05 ? "giving " + b.toFixed(2) + " kW" : b < -0.05 ? "taking " + (-b).toFixed(2) + " kW" : "idle");
    svg += node(308, cy, "House", load.toFixed(2) + " kW", "");
    $("flow").innerHTML = svg;
    // "100% · giving 0.32 kW" and "4.20 kW · 1.23 kW wasted" outgrow the 104-wide box:
    // grow each box to its widest line, kept inside the card
    for (const g of $("flow").querySelectorAll(".node")) {
      const rect = g.querySelector("rect"), x = +g.querySelector("text").getAttribute("x");
      let w = 104;
      for (const tx of g.querySelectorAll("text")) { try { w = Math.max(w, tx.getComputedTextLength() + 14); } catch (e) { /* not laid out */ } }
      const left = Math.min(Math.max(1, x - w / 2), 359 - w);
      rect.setAttribute("x", left); rect.setAttribute("width", w);
      for (const tx of g.querySelectorAll("text")) tx.setAttribute("x", left + w / 2);
    }
    $("k-soc").textContent = (soc * 100).toFixed(0) + "%";
    $("g-soc").style.width = (soc * 100).toFixed(0) + "%";
    $("k-tank").textContent = (S.tank[i] * 100).toFixed(0) + "%";
    $("g-tank").style.width = (S.tank[i] * 100).toFixed(0) + "%";
    const o = H.outages.find((x) => x.start <= state.t && state.t < x.end);
    $("k-grid").textContent = up ? "On" : "Off";
    $("k-grid").style.color = up ? "" : "var(--outage)";
    // the minute series and the outage list can disagree for a moment at an outage's edge
    $("k-grid-l").textContent = up ? `Grid · ${S.volts[i].toFixed(0)} V`
      : o ? `Outage ${C.clock(o.start)}–${C.clock(o.end)}${o.published ? "" : " (unannounced)"}` : "Outage";
  }

  // ---- events ----
  let lastLogKey = "";
  const KEY_TOPICS = /alert|settings|\/request|\/done|grid\/state/;
  function renderLog(force) {
    const Mm = M(), only = $("only-key").checked;
    const n = C.bisectRight(Mm.log, state.t, (m) => m.t), key = state.mode + n + only;
    if (!force && key === lastLogKey) return;
    lastLogKey = key;
    const items = [];
    for (let k = n - 1; k >= 0 && items.length < 150; k--) {
      const m = Mm.log[k]; if (!m.text) continue;
      const decision = KEY_TOPICS.test(m.topic) || (m.cause == null && /— (pre-cool|outage|hold|solar|latest|deadline|fill|protecting|peak)/.test(m.text)) || /outage:|pre-cool|protecting|latest start|solar surplus|fill the tank/.test(m.text);
      if (only && !decision) continue;
      const alert = /alert|grid\/state/.test(m.topic) && !(m.topic === "home/grid/state" && m.payload);
      items.push(`<li data-msg="${m.id}" class="${alert ? "alert" : ""}"><span class="t num">${C.clock(m.t)}</span><span class="x">${esc(m.text)}</span></li>`);
    }
    $("log").innerHTML = items.join("") || `<li><span></span><span class="muted">Nothing yet — press play.</span></li>`;
    $("log-count").textContent = `${items.length}${items.length === 150 ? "+" : ""} shown`;
  }

  // ---- inspector ----
  function row(k, v) { return `<div class="row"><span class="muted">${k}</span><span class="num">${v}</span></div>`; }
  function whyHtml(id) {
    const chain = C.whyChain(M(), id);
    if (!chain.length) return `<p class="muted">No recorded cause.</p>`;
    return `<div class="why">${chain.map((m, k) => `<div>${k ? "↳ because " : ""}<span class="t num">${C.clock(m.t)}</span>${esc(m.text || describe(m))}</div>`).join("")}</div>`;
  }
  function describe(m) {
    const p = m.topic.split("/");
    if (p[2] === "temp") return `Temperature in ${rooms[p[1]] ? rooms[p[1]].name : p[1]}: ${Number(m.payload).toFixed(1)} °C`;
    if (p[2] === "presence") return `${m.payload} people in ${rooms[p[1]] ? rooms[p[1]].name : p[1]}`;
    if (p[1] === "tank") return `Roof tank at ${(m.payload * 100).toFixed(0)}%`;
    if (p[1] === "grid" && p[2] === "voltage") return `Mains voltage ${Number(m.payload).toFixed(0)} V`;
    return m.topic;
  }
  function renderInspector() {
    const body = $("inspect-body"), i = si(), S = M().series, t = state.t;
    const want = state.sel && state.sel.type !== "msg" ? state.sel.type + ":" + state.sel.id : "";
    if ($("find").value !== want) $("find").value = want;
    if (!state.sel) return;
    if (state.sel.type === "room") {
      const r = rooms[state.sel.id];
      let html = `<h3>${esc(r.name)}</h3>`;
      if (S.temp[r.id]) html += row("Temperature", S.temp[r.id][i].toFixed(1) + " °C") + row("People", S.occ[r.id][i]);
      for (const a of H.appliances.filter((x) => x.room === r.id)) html += appBlock(a, t);
      body.innerHTML = html;
    } else if (state.sel.type === "app") {
      body.innerHTML = appBlock(APPS[state.sel.id], t, true);
    } else if (state.sel.type === "person") {
      const p = people[state.sel.id], at = personAt(p, t);
      let html = `<h3 style="color:${p.colour}">${esc(p.name)}</h3>` + row("Who", ROLE_NAMES[p.role]) + row("Now", esc(C.labelAt(p, t))) + row("Where", at ? roomAt(at.x, at.y) : "Out");
      html += `<h3>Day so far</h3><table>`;
      for (const [lt, l] of p.labels) if (lt <= t) html += `<tr><td class="num muted">${C.clock(lt)}</td><td>${esc(l)}</td></tr>`;
      body.innerHTML = html + `</table>`;
    } else if (state.sel.type === "msg") {
      // message ids differ between controllers: when switching, find the same topic nearest in time
      let m = M().byId[state.sel.id];
      if (!m || (state.sel.topic && m.topic !== state.sel.topic)) {
        const cands = M().log.filter((x) => x.topic === state.sel.topic && x.text);
        m = cands.sort((a, b) => Math.abs(a.t - state.sel.t) - Math.abs(b.t - state.sel.t))[0];
      }
      body.innerHTML = m ? `<h3>Event at ${C.clock(m.t)}</h3><p>${esc(m.text)}</p><p class="muted num">topic <code>${esc(m.topic)}</code></p><h3>Why it happened</h3>${whyHtml(m.id)}` : `<p class="muted">Nothing like that event happens under this controller.</p>`;
    }
  }
  function appBlock(a, t, full) {
    const c = cmdSince(a.id, t), on = live(a.id, t), wanted = cmdOn(a.id, t);
    const wired = M().wired.has(a.id);
    let state_ = on ? `<span class="pill ok">ON</span>` : wanted ? `<span class="pill bad">NO POWER</span>` : `<span class="pill">OFF</span>`;
    let html = `<h3>${esc(a.kind === "ac" ? "AC" : a.kind[0].toUpperCase() + a.kind.slice(1))} ${full ? "· " + esc(rooms[a.room].name) : ""}: ${state_}${c ? ` <span class="muted num">since ${C.clock(c.since)}</span>` : ""}</h3>`;
    html += `<div class="muted" style="font-size:12px">${a.watts} W · ${a.essential ? "essential" : "non-essential"} · ${wired ? "on the inverter" : "grid only (dies in an outage)"}</div>`;
    if (c && c.id != null) html += whyHtml(c.id);
    return html;
  }
  function roomAt(x, y) { for (const r of plan.rooms) { const [x0, y0, x1, y1] = r.rect; if (x > x0 && x < x1 && y > y0 && y < y1) return r.name; } return "Doorway"; }
  function fillFinder() {
    const opt = (v, l) => `<option value="${v}">${esc(l)}</option>`;
    const ps = Object.values(people).sort((a, b) => a.name.localeCompare(b.name));
    $("find").innerHTML = opt("", "— choose —")
      + `<optgroup label="People">${ps.map((p) => opt("person:" + p.id, `${p.name} · ${ROLE_NAMES[p.role]}`)).join("")}</optgroup>`
      + `<optgroup label="Rooms">${plan.rooms.filter((r) => r.kind !== "outdoor").map((r) => opt("room:" + r.id, r.name)).join("")}</optgroup>`
      + `<optgroup label="Appliances">${H.appliances.filter((a) => a.kind !== "light").map((a) => opt("app:" + a.id, `${a.kind === "ac" ? "AC" : a.kind} · ${rooms[a.room].name}`)).join("")}</optgroup>`;
    $("find").onchange = (e) => { const v = e.target.value; const k = v.indexOf(":"); state.sel = v ? { type: v.slice(0, k), id: v.slice(k + 1) } : null; goToSel(); frame(true); };
  }

  // ---- people: who is home, who is out and why, the gate counter ----
  function statusAt(p, t) {
    if (t < p.arrive) return { where: "due", label: p.role === "relative" || p.role === "grandparent" ? "Visiting later" : "Not here yet" };
    if (t >= p.gone) return { where: "left", label: "Gone home" };
    const label = C.labelAt(p, t);
    const at = personAt(p, t);
    if (!at) return { where: "out", label: label.replace(/^Out — /, "") };
    return { where: "home", label, room: roomAt(at.x, at.y), moving: at.moving };
  }
  function homeCount(t) {
    const g = H.gate || [];
    const i = C.bisectRight(g, t, (e) => e[0]) - 1;
    return i >= 0 ? g[i][3] : H.people.filter((p) => p.arrive === 0).length;
  }
  function sinceOut(pid, t) {
    const g = H.gate || [];
    for (let i = C.bisectRight(g, t, (e) => e[0]) - 1; i >= 0; i--) if (g[i][1] === pid) return g[i][2] === "out" ? g[i][0] : null;
    return null;
  }
  let lastPeople = "";
  function renderPeople() {
    const t = state.t, ps = Object.values(people).map((p) => ({ p, s: statusAt(p, t) }));
    const home = ps.filter((x) => x.s.where === "home"), out = ps.filter((x) => x.s.where === "out");
    const guests = home.filter((x) => x.p.role === "relative" || x.p.role === "grandparent").length;
    const li = (x, right) => `<li data-person="${x.p.id}" tabindex="0"><i style="background:${x.p.colour}"></i><span>${esc(x.p.name)} <span class="sub">· ${ROLE_NAMES[x.p.role]}</span><br><span class="sub">${esc(x.s.label)}</span></span><span class="sub num">${right}</span></li>`;
    let html = `<div class="headcount"><span><b class="num">${home.length}</b>at home</span><span><b class="num">${out.length}</b>out</span>${guests ? `<span><b class="num">${guests}</b>guests</span>` : ""}</div>`;
    if (H.gate) html += `<canvas class="chart" id="c-home" style="height:90px" aria-label="People at home through the day"></canvas>`;
    html += `<h3>At home</h3><ul class="who">${home.map((x) => li(x, esc(x.s.moving ? "walking" : x.s.room))).join("") || '<li class="sub">Nobody</li>'}</ul>`;
    html += `<h3>Out</h3><ul class="who">${out.map((x) => { const s = sinceOut(x.p.id, t); return li(x, s != null ? "since " + C.clock(s) : ""); }).join("") || '<li class="sub">Everyone is home</li>'}</ul>`;
    const later = ps.filter((x) => x.s.where === "due" || x.s.where === "left");
    if (later.length) html += `<h3>Visitors</h3><ul class="who">${later.map((x) => li(x, x.s.where === "due" ? "due " + C.clock(x.p.arrive) : "left")).join("")}</ul>`;
    if (H.gate) {
      const g = H.gate.filter((e) => e[0] <= t).slice(-14).reverse();
      html += `<h3>Gate counter</h3><ul class="who gate">${g.map(([tt, pid, way, n]) => `<li><span class="num sub">${C.clock(tt)}</span><span style="color:${way === "in" ? "var(--ok)" : "var(--muted)"}">${way === "in" ? "→" : "←"}</span><span>${esc(people[pid].name)} <span class="sub">${way === "in" ? "came in" : "went out"}</span></span><span class="sub num">${n} home</span></li>`).join("") || '<li class="sub">No one has come or gone yet today</li>'}</ul>`;
      html += `<p class="muted" style="font-size:12px">A beam counter on the gate reports every crossing on home/gate/count. Fans and lights follow each room's presence; the drawing room comes on when guests sit down.</p>`;
    }
    if (html !== lastPeople) { lastPeople = html; $("pane-people").innerHTML = html; }   // rebuild only on change, so a click lands
    if (H.gate) drawHomeCount();
  }
  function drawHomeCount() {
    const c = chartBase("c-home", 0, Math.max(4, ...H.gate.map((e) => e[3])) + 1, true);
    if (!c) return;
    const { g, xs, ys } = c;
    g.strokeStyle = palette.people; g.lineWidth = 2; g.beginPath();
    let n = homeCount(0); g.moveTo(xs(0), ys(n));
    for (const [tt, , , m] of H.gate) { g.lineTo(xs(tt), ys(n)); g.lineTo(xs(tt), ys(m)); n = m; }
    g.lineTo(xs(86400), ys(n)); g.stroke(); now(c);
  }

  // ---- day charts ----
  function renderDay() {
    $("pane-day").innerHTML = `<h3>Power, kW</h3><div class="strip-key"><span><i style="background:var(--solar)"></i>Solar</span><span><i style="background:var(--text)"></i>House load</span><span><i style="background:var(--grid)"></i>Grid (below 0 = export)</span><span><i style="background:rgba(248,113,113,.35)"></i>Outage</span></div><canvas class="chart" id="c-power"></canvas>
      <h3>Battery and roof tank, %</h3><div class="strip-key"><span><i style="background:var(--battery)"></i>Battery</span><span><i style="background:var(--water)"></i>Tank</span></div><canvas class="chart" id="c-soc" style="height:150px"></canvas>
      <h3>The day's outages</h3><table>${H.outages.map((o) => `<tr><td class="num">${C.clock(o.start)}–${C.clock(o.end)}</td><td>${o.published ? "published" : '<span class="pill bad">unannounced</span>'}</td></tr>`).join("")}</table>
      <p class="muted" style="font-size:12px">Feeder category ${H.meta.category}: ${H.meta.category_hours} h of published load-shedding. ${H.meta.season}; solar ${H.meta.day_factor >= 0.95 ? "clear day" : H.meta.day_factor >= 0.7 ? "hazy day" : "overcast day"} (forecast said ${(H.meta.forecast_factor * 100).toFixed(0)}% of clear sky).</p>`;
    drawDay();
  }
  function chartBase(id, lo, hi, plain) {
    const c = document.getElementById(id); if (!c) return null;
    const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
    c.width = w * dpr; c.height = h * dpr; const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const L = 30, B = 16, top = 6, xs = (t) => L + (w - L - 4) * t / 86400, ys = (v) => top + (h - B - top) * (1 - (v - lo) / (hi - lo));
    for (const o of plain ? [] : H.outages) {
      g.fillStyle = rgba(palette.outage, o.published ? 0.22 : 0.14);
      g.fillRect(xs(o.start), top, xs(o.end) - xs(o.start), h - B - top);
    }
    g.strokeStyle = palette.line; g.lineWidth = 1; g.font = "10.5px Segoe UI, system-ui"; g.fillStyle = palette.muted;
    const raw = (hi - lo) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((x) => x >= raw) || raw;
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) {
      const y = ys(v); g.beginPath(); g.moveTo(L, y); g.lineTo(w - 4, y); g.stroke(); g.textAlign = "right";
      g.fillText(Number.isInteger(v) ? String(v) : v.toFixed(1), L - 4, y + 3);
    }
    g.textAlign = "center"; for (let hh = 0; hh <= 24; hh += 4) g.fillText(String(hh).padStart(2, "0"), xs(hh * 3600), h - 3);
    return { g, xs, ys, w, h, top, B };
  }
  function line(c, arr, col, wdt, T) { const { g, xs, ys } = c; g.strokeStyle = col; g.lineWidth = wdt; g.beginPath(); arr.forEach((v, k) => (k ? g.lineTo(xs(T[k]), ys(v)) : g.moveTo(xs(T[k]), ys(v)))); g.stroke(); }
  function drawDay() {
    const S = M().series;
    const hi = Math.max(1, ...S.pv_kw, ...S.load_kw, ...S.grid_kw) * 1.1, lo = Math.min(0, ...S.grid_kw) * 1.1;
    const c1 = chartBase("c-power", lo, hi);
    if (c1) { line(c1, S.pv_kw, palette.solar, 1.6, S.t); line(c1, S.grid_kw, palette.grid, 1.4, S.t); line(c1, S.load_kw, palette.text, 1.6, S.t); now(c1); }
    const c2 = chartBase("c-soc", 0, 100);
    if (c2) { line(c2, S.soc.map((v) => v * 100), palette.battery, 2, S.t); line(c2, S.tank.map((v) => v * 100), palette.water, 1.4, S.t); now(c2); }
  }
  function now(c) { const { g, xs, top, h, B } = c; g.strokeStyle = palette.text; g.globalAlpha = 0.5; g.beginPath(); g.moveTo(xs(state.t), top); g.lineTo(xs(state.t), h - B); g.stroke(); g.globalAlpha = 1; }

  // ---- compare ----
  const ROWS = [
    ["House dark, min", "house_dark_min", "min"],
    ["No fan when wanted", "no_fan_person_min", "min"],
    ["Too hot to sleep", "hot_sleep_person_min", "min"],
    ["Too hot awake", "hot_awake_person_min", "min"],
    ["Tank empty, min", "tank_empty_min", "min"],
    ["Peak grid, kWh", "grid_peak_kwh", "min"],
    ["Off-peak grid, kWh", "grid_offpeak_kwh", "min"],
    ["Exported, kWh", "export_kwh", "info"],
    ["Solar used, %", "solar_used_pct", "max"],
    ["Solar wasted, kWh", "solar_wasted_kwh", "min"],
    ["Bill, Rs", "bill_rs", "min"],
    ["Overload trips", "overload_trips", "min"],
    ["Under 190 V, min", "low_voltage_stress_min", "min"],
  ];
  function renderCompare() {
    const names = Object.keys(H.modes), ms = names.map((n) => H.modes[n].metrics);
    const SHORT = { default: "Default", ups: "UPS", gridsense_eco: "Eco", gridsense: "Grid&shy;Sense" };
    let html = `<h3>Whole day, same family, same outages</h3><div style="overflow-x:auto"><table class="cmp" style="font-size:12px"><tr><th></th>${names.map((n) => `<th title="${MODE_NAMES[n]}">${SHORT[n]}</th>`).join("")}</tr>`;
    for (const [label, key, dir] of ROWS) {
      const vals = ms.map((m) => m[key]);
      const best = dir === "min" ? Math.min(...vals) : dir === "max" ? Math.max(...vals) : null;
      html += `<tr><td>${label}</td>${vals.map((v) => `<td class="num ${v === best ? "best" : ""}">${Number.isInteger(v) ? v.toLocaleString("en") : v.toFixed(1)}</td>`).join("")}</tr>`;
    }
    html += `<tr><td>Jobs late</td>${ms.map((m) => `<td class="num">${m.jobs_late.length}</td>`).join("")}</tr></table></div>`;
    html += `<p class="muted" style="font-size:12px">"No fan when wanted", "too hot to sleep" (felt above 30 °C) and "too hot awake" (felt above 32 °C) are person-minutes; a running fan counts as 2 °C cooler. "Under 190 V" is minutes the AC or fridge ran on low voltage. Green = best.</p>`;
    html += `<p class="muted" style="font-size:12px">Simulated house, not a measurement. Tariff assumptions: off-peak Rs ${H.meta.tariff.offpeak}, peak Rs ${H.meta.tariff.peak}, export Rs ${H.meta.tariff.export} per kWh. The bill values each controller's end-of-day battery change at the off-peak rate, so leaving the battery flat does not look cheap.</p>`;
    $("pane-compare").innerHTML = html;
  }

  // ---- timeline ----
  function renderTimeline() {
    const w = tl.clientWidth, h = tl.clientHeight, S = M().series;
    tctx.clearRect(0, 0, w, h);
    const xs = (t) => w * t / 86400;
    const [p0, p1] = H.meta.peak; tctx.fillStyle = rgba(palette.solar, 0.12); tctx.fillRect(xs(p0), 0, xs(p1) - xs(p0), h);
    for (const o of H.outages) {
      tctx.fillStyle = rgba(palette.outage, o.published ? 0.45 : 0.25); tctx.fillRect(xs(o.start), h - 14, xs(o.end) - xs(o.start), 10);
      if (!o.published) { tctx.strokeStyle = palette.outage; tctx.lineWidth = 1; for (let x = xs(o.start); x < xs(o.end); x += 5) { tctx.beginPath(); tctx.moveTo(x, h - 4); tctx.lineTo(x + 4, h - 14); tctx.stroke(); } }
    }
    tctx.strokeStyle = palette.battery; tctx.lineWidth = 1.5; tctx.beginPath();
    S.soc.forEach((v, k) => { const x = xs(S.t[k]), y = (h - 18) * (1 - v) + 2; k ? tctx.lineTo(x, y) : tctx.moveTo(x, y); }); tctx.stroke();
    for (const m of M().log) if (m.topic.startsWith("home/alert/")) { tctx.fillStyle = palette.alert; tctx.fillRect(xs(m.t) - 1, 0, 2, 7); }
    tctx.fillStyle = palette.accent; tctx.fillRect(xs(state.t) - 1.5, 0, 3, h);
  }
  function renderLegend() {
    $("legend").innerHTML = `<span><i class="sq" style="background:${palette.light}"></i>Lights</span><span><i class="sq" style="border:2px dashed ${palette.ac};background:transparent"></i>AC on</span><span><i class="sq" style="background:${palette.outage}"></i>Wanted, no power ✕</span><span><i class="sq" style="background:${palette.solar};opacity:.5"></i>Peak tariff</span>`
      + H.people.map((p) => `<span><i style="background:${p.colour}"></i>${ROLE_NAMES[p.role]}</span>`).filter((v, k, a) => a.indexOf(v) === k).join("");
    const out = []; for (let hh = 0; hh <= 24; hh += 2) out.push(`<span>${String(hh).padStart(2, "0")}</span>`); $("ticks").innerHTML = out.join("");
  }

  // ---- loop ----
  let lastPanel = 0;
  function renderFloors() {
    const count = {};
    for (const p of Object.values(people)) { const at = personAt(p, state.t); if (at) { const f = floorOf(at.x, at.y); count[f] = (count[f] || 0) + 1; } }
    const html = [...FLOORS].sort((a, b) => b.level - a.level).map((f) => `<button data-floor="${f.id}" aria-pressed="${f.id === F().id}" title="${esc(f.name)}: ${count[f.id] || 0} people now">${f.id} <span class="muted num">(${count[f.id] || 0})</span></button>`).join("");
    const box = $("floors"); if (box.dataset.html !== html) { box.innerHTML = html; box.dataset.html = html; }
    box.style.display = FLOORS.length > 1 ? "" : "none";
  }
  function setFloor(f) { state.floor = f; fit(); frame(true); }
  // picking something on another floor takes you to that floor
  function goToSel() {
    const sel = state.sel; if (!sel) return;
    let f = null;
    if (sel.type === "person") { const at = personAt(people[sel.id], state.t); if (at) f = floorOf(at.x, at.y); }
    else if (sel.type === "room") f = rooms[sel.id] && rooms[sel.id].floor;
    else if (sel.type === "app") f = rooms[APPS[sel.id].room] && rooms[APPS[sel.id].room].floor;
    if (f && f !== state.floor) { state.floor = f; fit(); }
  }
  function frame(force) {
    $("clock").textContent = C.clock(state.t); scrub.value = state.t;
    renderFloors();
    draw(); renderTimeline(); drawFlow();
    const nowT = performance.now();
    if (force || nowT - lastPanel > 250) {
      lastPanel = nowT; renderLog(force);
      if ($("pane-inspect").classList.contains("on")) renderInspector();
      if ($("pane-day").classList.contains("on")) drawDay();
      if ($("pane-people").classList.contains("on")) renderPeople();
    }
  }
  let prev = null;
  function loop(ts) {
    if (state.playing) {
      if (prev != null) state.t = Math.min(86399, state.t + ((ts - prev) / 1000) * state.speed);
      if (state.t >= 86399) setPlaying(false);
      frame(false);
    } else if (performance.now() % 1000 < 20) draw();      // keep fans spinning gently while paused
    prev = ts; requestAnimationFrame(loop);
  }
  function setPlaying(on) { state.playing = on; $("play").textContent = on ? "❚❚ Pause" : "▶ Play"; $("play").setAttribute("aria-label", on ? "Pause" : "Play"); }
  function save() { try { localStorage.setItem("home-twin", JSON.stringify({ theme: document.documentElement.dataset.theme, mode: state.mode, season })); } catch (e) { /* ignore */ } }
  for (const b of document.querySelectorAll("#seasons button")) {
    b.setAttribute("aria-pressed", b.dataset.season === season);
    b.disabled = !SCEN[b.dataset.season];
    b.onclick = () => {
      season = b.dataset.season; H = SCEN[season]; index();
      for (const x of document.querySelectorAll("#seasons button")) x.setAttribute("aria-pressed", x === b);
      state.sel = null; lastLogKey = ""; save(); fillFinder(); renderLegend();
      if ($("pane-day").classList.contains("on")) renderDay();
      if ($("pane-compare").classList.contains("on")) renderCompare();
      frame(true);
    };
  }
  function showTab(name) {
    for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", b.dataset.tab === name);
    for (const p of document.querySelectorAll(".pane")) p.classList.toggle("on", p.id === "pane-" + name);
    if (name === "day") renderDay(); if (name === "compare") renderCompare(); if (name === "inspect") renderInspector(); if (name === "people") renderPeople();
  }

  $("play").onclick = () => { if (state.t >= 86399) state.t = 0; setPlaying(!state.playing); };
  $("speed").onchange = (e) => { state.speed = +e.target.value; };
  scrub.oninput = () => { state.t = +scrub.value; frame(true); };
  for (const b of document.querySelectorAll("#modes button")) {
    b.setAttribute("aria-pressed", b.dataset.mode === state.mode);
    b.onclick = () => { state.mode = b.dataset.mode; for (const x of document.querySelectorAll("#modes button")) x.setAttribute("aria-pressed", x === b); save(); if ($("pane-day").classList.contains("on")) renderDay(); if ($("pane-compare").classList.contains("on")) renderCompare(); frame(true); };
  }
  for (const b of document.querySelectorAll("#layers button")) b.onclick = () => { state.layer = b.dataset.layer; for (const x of document.querySelectorAll("#layers button")) x.setAttribute("aria-pressed", x === b); frame(true); };
  for (const b of document.querySelectorAll(".tabs button")) b.onclick = () => showTab(b.dataset.tab);
  $("floors").onclick = (e) => { const b = e.target.closest("button[data-floor]"); if (b) setFloor(b.dataset.floor); };
  $("only-key").onchange = () => renderLog(true);
  function pickPerson(e) {
    const li = e.target.closest("li[data-person]"); if (!li) return;
    if (e.type === "keydown" && e.key !== "Enter" && e.key !== " ") return;
    state.sel = { type: "person", id: li.dataset.person }; goToSel(); showTab("inspect"); frame(true);
  }
  $("pane-people").onclick = pickPerson; $("pane-people").onkeydown = pickPerson;
  $("log").onclick = (e) => {
    const li = e.target.closest("li[data-msg]"); if (!li) return;
    const m = M().byId[+li.dataset.msg];
    state.sel = { type: "msg", id: +li.dataset.msg, topic: m && m.topic, t: m && m.t };
    showTab("inspect"); frame(true);
  };
  $("theme").onclick = () => { const d = document.documentElement.dataset.theme !== "light"; document.documentElement.dataset.theme = d ? "light" : "dark"; $("theme").textContent = d ? "Dark" : "Light"; readPalette(); renderLegend(); save(); if ($("pane-day").classList.contains("on")) renderDay(); frame(true); };
  function pick(ev) {
    const rect = cv.getBoundingClientRect(), mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    let best = null, bd = Math.max(9, view.s * 0.6);
    for (const hh of hits) { const d = Math.hypot(hh.x - mx, hh.y - my); if (d < bd) { bd = d; best = hh; } }
    if (best) return { type: "person", id: best.p.id };
    for (const a of H.appliances) { if (!roomOnFloor(a.room)) continue; const p = appPos(a); if (p && Math.hypot(X(p[0]) - mx, Y(p[1]) - my) < Math.max(8, view.s * 0.45)) return { type: "app", id: a.id }; }
    const wx = (mx - view.ox) / view.s + F().origin[0], wy = (my - view.oy) / view.s + F().origin[1];
    for (const r of plan.rooms) { if (!roomOnFloor(r.id)) continue; const [x0, y0, x1, y1] = r.rect; if (wx > x0 && wx < x1 && wy > y0 && wy < y1) return { type: "room", id: r.id }; }
    return null;
  }
  cv.addEventListener("click", (ev) => { state.sel = pick(ev); if (state.sel) showTab("inspect"); frame(true); });
  cv.addEventListener("mousemove", (ev) => {
    const p = pick(ev), tip = $("tip"); if (!p) { tip.style.display = "none"; return; }
    const rect = cv.getBoundingClientRect(); let html;
    if (p.type === "person") { const q = people[p.id]; html = `<b>${esc(q.name)}</b> · ${ROLE_NAMES[q.role]}<br><span class="muted">${esc(C.labelAt(q, state.t))}</span>`; }
    else if (p.type === "app") { const a = APPS[p.id]; html = `<b>${a.kind === "ac" ? "AC" : a.kind}</b> · ${esc(rooms[a.room].name)}<br><span class="muted">${live(a.id, state.t) ? "running" : cmdOn(a.id, state.t) ? "wanted, no power" : "off"}</span>`; }
    else { const r = rooms[p.id], S = M().series, i = si(); html = `<b>${esc(r.name)}</b>` + (S.temp[r.id] ? `<br><span class="muted">${S.occ[r.id][i]} inside · ${S.temp[r.id][i].toFixed(1)} °C</span>` : ""); }
    tip.innerHTML = html; tip.style.display = "block";
    tip.style.left = Math.min(ev.clientX - rect.left + 14, rect.width - tip.offsetWidth - 6) + "px";
    tip.style.top = Math.min(ev.clientY - rect.top + 14, rect.height - tip.offsetHeight - 6) + "px";
  });
  cv.addEventListener("mouseleave", () => { $("tip").style.display = "none"; });
  document.addEventListener("keydown", (e) => {
    if (["INPUT", "SELECT", "BUTTON", "TEXTAREA"].includes(e.target.tagName)) return;
    if (e.code === "Space") { e.preventDefault(); $("play").click(); }
    if (e.key === "ArrowRight") { state.t = Math.min(86399, state.t + 900); frame(true); }
    if (e.key === "ArrowLeft") { state.t = Math.max(0, state.t - 900); frame(true); }
  });
  window.addEventListener("resize", () => { fit(); frame(true); });

  $("theme").textContent = document.documentElement.dataset.theme === "light" ? "Dark" : "Light";
  readPalette(); fit(); fillFinder(); renderLegend(); frame(true); requestAnimationFrame(loop);
  // running machines whose glyph a person's dot covers right now (the UI check wants none)
  function hiddenRunning() {
    const t = state.t, rp = Math.max(3.5, view.s * 0.3), out = [];
    for (const a of H.appliances) {
      // fan blades and AC bars reach past a dot; the small square glyphs do not
      if (["light", "fan", "ac"].includes(a.kind) || !live(a.id, t)) continue;
      const p = appPos(a); if (!p) continue;
      for (const h of hits) if (Math.hypot(h.x - X(p[0]), h.y - Y(p[1])) < rp) out.push(a.id + " under " + h.p.name);
    }
    return out;
  }
  window.__home = { state, frame, showTab, setFloor, floorOf, hits: () => hits, hiddenRunning, get people() { return people; }, get modes() { return modes; }, season: () => season };
})();

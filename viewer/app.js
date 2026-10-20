/* Office Twin viewer UI. Pure helpers live in core.js (loaded first). */
"use strict";

// ---------- UI ----------

if (typeof document !== "undefined") (function () {
  const R = window.REPLAY;
  const IX = buildIndex(R);
  const plan = R.plan;
  const rooms = Object.fromEntries(plan.rooms.map((r) => [r.id, r]));
  const MODE_NAMES = { schedule: "Fixed schedule", pir: "Motion", "pir+co2": "Motion + CO₂" };
  const ROLE_NAMES = { staff: "Staff", manager: "Manager", receptionist: "Receptionist", office_boy: "Office boy", guard: "Guard", cleaner: "Cleaner", visitor: "Visitor", courier: "Courier / rider" };

  const state = {
    t: R.meta.t0 + 3600 * 2.5, mode: "pir+co2", layer: "state", playing: false, speed: 60,
    sel: null, // {type:'room'|'person'|'msg', id}
    hover: null, floor: "G",
  };
  // floors: basement car park, ground floor, first floor; one is drawn at a time
  const FLOORS = plan.floors && plan.floors.length ? plan.floors : [{ id: "G", name: "Ground floor", level: 0, origin: [0, 0], size: plan.size }];
  TwinCore.setHops(plan.portal_hops);
  const F = () => FLOORS.find((f) => f.id === state.floor) || FLOORS[0];
  function floorOf(x, y) {
    for (const f of FLOORS) { const [ox, oy] = f.origin; if (x >= ox && x <= ox + f.size[0] && y >= oy && y <= oy + f.size[1]) return f.id; }
    return FLOORS[0].id;
  }
  const onFloor = (x, y) => floorOf(x, y) === F().id;
  const roomOnFloor = (rid) => !rooms[rid] || (rooms[rid].floor || FLOORS[0].id) === F().id;
  const RM = () => plan.rooms.filter((r) => roomOnFloor(r.id));
  try {
    const saved = JSON.parse(localStorage.getItem("office-twin") || "{}");
    if (saved.theme) document.documentElement.dataset.theme = saved.theme;
    if (saved.mode && R.modes[saved.mode]) state.mode = saved.mode;
  } catch (e) { /* storage blocked: defaults are fine */ }

  const $ = (id) => document.getElementById(id);
  const cv = $("plan"), ctx = cv.getContext("2d");
  const tl = $("tl"), tctx = tl.getContext("2d");
  const scrub = $("scrub");
  scrub.min = R.meta.t0; scrub.max = R.meta.t1 - 1;

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  let palette = {};
  function readPalette() {
    for (const k of ["bg", "panel", "floor", "floor-out", "wall", "desk", "light", "ac", "ok", "alert", "warn", "text", "muted", "line", "people", "accent"]) palette[k] = css("--" + k);
  }

  // ---- geometry ----
  let view = { s: 10, ox: 0, oy: 0 };
  function fit() {
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth, h = cv.clientHeight;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const [W, H] = F().size;
    // room for the layer buttons above and the legend below; little else wasted
    const top = 56, bottom = w < 700 ? 12 : 58, side = 20;
    const s = Math.min((w - side * 2) / W, (h - top - bottom) / H);
    view = { s, ox: (w - W * s) / 2, oy: top + (h - top - bottom - H * s) / 2 };
    const tw = tl.clientWidth, th = tl.clientHeight;
    tl.width = Math.round(tw * dpr); tl.height = Math.round(th * dpr);
    tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  const X = (x) => view.ox + (x - F().origin[0]) * view.s;
  const Y = (y) => view.oy + (y - F().origin[1]) * view.s;

  // ---- colour scales ----
  function mix(a, b, f) {
    const pa = hex(a), pb = hex(b);
    return `rgb(${pa.map((v, i) => Math.round(v + (pb[i] - v) * f)).join(",")})`;
  }
  function hex(c) {
    if (c.startsWith("rgb")) return c.match(/\d+/g).slice(0, 3).map(Number);
    c = c.replace("#", "");
    if (c.length === 3) c = c.split("").map((x) => x + x).join("");
    return [0, 2, 4].map((i) => parseInt(c.slice(i, i + 2), 16));
  }
  function rgba(c, a) { const [r, g, b] = hex(c); return `rgba(${r},${g},${b},${a})`; }
  function tempColour(T) {
    const f = Math.max(0, Math.min(1, (T - 22) / 8));
    return f < 0.5 ? mix("#38bdf8", "#a3e635", f * 2) : mix("#a3e635", "#f87171", (f - 0.5) * 2);
  }
  function co2Colour(c) {
    const f = Math.max(0, Math.min(1, (c - 420) / 900));
    return f < 0.5 ? mix("#34d399", "#fbbf24", f * 2) : mix("#fbbf24", "#f87171", (f - 0.5) * 2);
  }

  // ---- drawing ----
  function draw() {
    const M = IX.modes[state.mode];
    const w = cv.clientWidth, h = cv.clientHeight;
    ctx.clearRect(0, 0, w, h);
    const si = seriesIndex(R, state.t);
    const s = view.s;

    for (const r of RM()) {
      const [x0, y0, x1, y1] = r.rect;
      let fill = r.kind === "outdoor" ? palette["floor-out"] : palette.floor;
      if (r.kind !== "outdoor") {
        if (state.layer === "state") {
          /* lit rooms get a glow drawn after the fill */
        } else if (state.layer === "occ") {
          const n = M.series.occ[r.id] ? M.series.occ[r.id][si] : 0;
          const cap = Math.max(1, r.kind === "workspace" ? 24 : r.kind === "meeting" ? 10 : 4);
          if (n > 0) fill = mix(palette.floor, palette.people, Math.min(0.75, 0.2 + 0.55 * n / cap));
        } else if (state.layer === "temp" && M.series.temp[r.id]) {
          fill = mix(palette.floor, tempColour(M.series.temp[r.id][si]), 0.55);
        } else if (state.layer === "co2" && M.series.co2[r.id] && plan.ac_rooms.includes(r.id)) {
          fill = mix(palette.floor, co2Colour(M.series.co2[r.id][si]), 0.55);
        }
      }
      ctx.fillStyle = fill;
      ctx.fillRect(X(x0), Y(y0), (x1 - x0) * s, (y1 - y0) * s);
      if (state.layer === "state" && r.kind !== "outdoor" && deviceAt(M, r.id, "light", state.t).on) {
        const cx = X((x0 + x1) / 2), cy = Y((y0 + y1) / 2);
        const rad = Math.hypot(x1 - x0, y1 - y0) * s * 0.6;
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, rad);
        g.addColorStop(0, rgba(palette.light, 0.30));
        g.addColorStop(1, rgba(palette.light, 0.10));
        ctx.fillStyle = g;
        ctx.fillRect(X(x0), Y(y0), (x1 - x0) * s, (y1 - y0) * s);
      }
      if (state.layer === "state" && r.kind !== "outdoor" && deviceAt(M, r.id, "ac", state.t).on) {
        ctx.strokeStyle = rgba(palette.ac, 0.9);
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 4]);
        ctx.strokeRect(X(x0) + 4, Y(y0) + 4, (x1 - x0) * s - 8, (y1 - y0) * s - 8);
        ctx.setLineDash([]);
      }
    }
    drawFurniture();
    // walls
    ctx.strokeStyle = palette.wall;
    ctx.lineWidth = Math.max(2, s * 0.14);
    ctx.lineCap = "square";
    for (const r of RM()) {
      if (r.kind === "outdoor") continue;
      const [x0, y0, x1, y1] = r.rect;
      ctx.strokeRect(X(x0), Y(y0), (x1 - x0) * s, (y1 - y0) * s);
    }
    // door gaps
    for (const d of plan.doors) {
      if (!roomOnFloor(d.a)) continue;
      const a = rooms[d.a], b = rooms[d.b];
      const outdoor = a.kind === "outdoor" || b.kind === "outdoor";
      ctx.strokeStyle = outdoor ? palette["floor-out"] : palette.floor;
      ctx.lineWidth = Math.max(3, s * 0.18);
      ctx.lineCap = "butt";
      ctx.beginPath();
      if (d.axis === "x") { ctx.moveTo(X(d.lo), Y(d.at)); ctx.lineTo(X(d.hi), Y(d.at)); }
      else { ctx.moveTo(X(d.at), Y(d.lo)); ctx.lineTo(X(d.at), Y(d.hi)); }
      ctx.stroke();
      if (d.gate === "badge") {
        // a reader beside the door, on the secure side, labelled from there
        const fs = Math.max(9, s * 0.3);
        ctx.font = `600 ${fs}px Segoe UI, system-ui`;
        ctx.fillStyle = palette.accent;
        if (d.axis === "x") {
          ctx.fillRect(X(d.lo) - 8, Y(d.at) - 4, 6, 8);
          ctx.textAlign = "right";
          if (s >= 12) readerLabel(X(d.lo) - 11, Y(d.at) + fs + 4, fs);
        } else {
          const secureLeft = rooms[d.b].rect[2] <= d.at + 1e-6;
          ctx.fillRect(X(d.at) - 3, Y(d.hi) + 3, 6, 6);
          ctx.textAlign = secureLeft ? "right" : "left";
          if (s >= 12) readerLabel(X(d.at) + (secureLeft ? -6 : 6), Y(d.hi) + fs + 4, fs);
        }
      }
    }
    // room labels
    ctx.textAlign = "center";
    for (const r of RM()) {
      const [x0, y0, x1, y1] = r.rect;
      const fs = Math.max(9, Math.min(13, s * 0.42));
      ctx.font = `600 ${fs}px Segoe UI, system-ui`;
      // data layers fill rooms with colour, where muted grey stops being readable
      ctx.fillStyle = state.layer === "state" || r.kind === "outdoor" ? palette.muted : palette.text;
      const name = (x1 - x0) * s < 70 ? shortName(r) : r.name;
      if (r.kind === "corridor") {
        const vertical = (y1 - y0) > (x1 - x0);
        ctx.save();
        if (vertical) {
          ctx.translate(X((x0 + x1) / 2) + fs * 0.35, Y((y0 + y1) / 2));
          ctx.rotate(-Math.PI / 2);
          ctx.fillText(name, 0, 0);
        } else {
          ctx.textAlign = "left";
          ctx.fillText(name, X(x0) + 8, Y((y0 + y1) / 2) + fs * 0.35);
        }
        ctx.restore();
        continue;
      }
      const room = (x1 - x0) * s - 6;
      let label = name;
      if (ctx.measureText(label).width > room) label = shortName(r);
      if (ctx.measureText(label).width > room) label = "";
      if (label) ctx.fillText(label, X((x0 + x1) / 2), Y(y0) + fs + 4);
      if (state.layer === "temp" && M.series.temp[r.id] && r.kind !== "outdoor") {
        ctx.fillStyle = palette.text;
        ctx.fillText(M.series.temp[r.id][si].toFixed(1) + "°", X((x0 + x1) / 2), Y(y0) + fs * 2 + 7);
      } else if (state.layer === "co2" && plan.ac_rooms.includes(r.id)) {
        ctx.fillStyle = palette.text;
        ctx.fillText(M.series.co2[r.id][si] + " ppm", X((x0 + x1) / 2), Y(y0) + fs * 2 + 7);
      } else if (state.layer === "occ" && M.series.occ[r.id] && M.series.occ[r.id][si] > 0) {
        ctx.fillStyle = palette.text;
        ctx.fillText(M.series.occ[r.id][si] + " in", X((x0 + x1) / 2), Y(y0) + fs * 2 + 7);
      }
      if (state.sel && state.sel.type === "room" && state.sel.id === r.id) {
        ctx.strokeStyle = palette.accent; ctx.lineWidth = 3;
        ctx.strokeRect(X(x0) + 1.5, Y(y0) + 1.5, (x1 - x0) * s - 3, (y1 - y0) * s - 3);
      }
    }
    drawCars();
    drawPeople();
  }

  // a door's "badge reader" text is left out where it would print over a room's name
  function readerLabel(x, y, fs) {
    const w = ctx.measureText("badge reader").width, align = ctx.textAlign;
    const bx0 = align === "right" ? x - w : x, bx1 = bx0 + w, by0 = y - fs, by1 = y + 2;
    const s = view.s, lf = Math.max(9, Math.min(13, s * 0.42));
    for (const r of RM()) {
      if (r.kind === "corridor") continue;
      const [x0, y0, x1] = r.rect, cx = X((x0 + x1) / 2), half = Math.min((x1 - x0) * s / 2, 60);
      const ly0 = Y(y0) + 4, ly1 = Y(y0) + lf + 6;
      if (bx0 < cx + half && bx1 > cx - half && by0 < ly1 && by1 > ly0) return;
    }
    ctx.fillText("badge reader", x, y);
  }
  function shortName(r) {
    return (plan.short_names || {})[r.id] || r.name;
  }

  function drawFurniture() {
    const s = view.s;
    ctx.fillStyle = palette.desk;
    for (const [x, y] of plan.spots.desk) if (onFloor(x, y)) ctx.fillRect(X(x - 0.9), Y(y - 0.75), 1.8 * s, 0.6 * s);
    for (const k of plan.big_desks || []) for (const [x, y] of plan.spots[k] || []) if (onFloor(x, y)) ctx.fillRect(X(x - 1), Y(y - 0.9), 2 * s, 0.6 * s);
    for (const f of plan.furniture || []) { const [fx, fy, fw, fh] = f.rect; if (onFloor(fx, fy)) rr(X(fx), Y(fy), fw * s, fh * s, (f.radius || 0) * s); }
    // parking bays (in the basement)
    ctx.strokeStyle = rgba(palette.muted, 0.45);
    ctx.lineWidth = 1;
    const bays = plan.parking.spots.filter(([x, y]) => onFloor(x, y));
    for (const [x, y] of bays) ctx.strokeRect(X(x - 1.1), Y(y - 2.3), 2.2 * s, 4.6 * s);
    if (bays.length) {
      ctx.setLineDash([6, 6]);
      ctx.beginPath(); ctx.moveTo(X(F().origin[0] + 1), Y(plan.parking.lane_y)); ctx.lineTo(X(F().origin[0] + F().size[0] - 1), Y(plan.parking.lane_y)); ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.fillStyle = palette.muted;
    ctx.font = `600 ${Math.max(9, s * 0.34)}px Segoe UI, system-ui`;
    ctx.textAlign = "left";
    for (const l of plan.labels || []) if (onFloor(l.at[0], l.at[1])) ctx.fillText(l.text, X(l.at[0]), Y(l.at[1]));
    // lifts, stairs and the car ramp on this floor
    for (const pt of plan.portals || []) {
      const at = pt.at[F().id]; if (!at) continue;
      const x = X(at[0]), y = Y(at[1]), r = Math.max(7, s * 0.5);
      ctx.fillStyle = palette.panel; ctx.strokeStyle = palette.accent; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.rect(x - r, y - r, 2 * r, 2 * r); ctx.fill(); ctx.stroke();
      ctx.fillStyle = palette.accent; ctx.font = `700 ${Math.max(8, r)}px Segoe UI`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(pt.kind === "lift" ? "⇅" : pt.kind === "ramp" ? "↗" : "▤", x, y + 0.5); ctx.textBaseline = "alphabetic"; ctx.textAlign = "left";
    }
  }
  function rr(x, y, w, h, r) {
    ctx.beginPath();
    ctx.roundRect ? ctx.roundRect(x, y, w, h, r) : ctx.rect(x, y, w, h);
    ctx.fill();
  }

  function drawCars() {
    const s = view.s, t = state.t;
    const ramp = (plan.portals || []).find((p) => p.kind === "ramp");
    const gate = ramp ? ramp.at[plan.parking.floor || "G"] || plan.spots.gate[0] : plan.spots.gate[0];
    for (const c of R.cars) {
      const out = c.out == null ? Infinity : c.out;
      if (t < c.in || t >= out + 25) continue;
      const bay = plan.parking.spots[c.bay];
      if (!onFloor(bay[0], bay[1])) continue;
      let x = bay[0], y = bay[1];
      const lane = plan.parking.lane_y;
      const path = [[gate[0], gate[1]], [gate[0], lane], [bay[0], lane], [bay[0], bay[1]]];
      if (t < c.in + 25) {
        const len = Math.abs(lane - gate[1]) + Math.abs(bay[0] - gate[0]) + Math.abs(lane - bay[1]);
        [x, y] = pointAlong(path, len * (t - c.in) / 25);
      } else if (t >= out) {
        const rev = path.slice().reverse();
        const len = Math.abs(lane - gate[1]) + Math.abs(bay[0] - gate[0]) + Math.abs(lane - bay[1]);
        [x, y] = pointAlong(rev, len * (t - out) / 25);
      }
      const p = IX.people[c.p];
      ctx.fillStyle = rgba(p.colour, 0.28);
      ctx.strokeStyle = rgba(p.colour, 0.9);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.roundRect ? ctx.roundRect(X(x - 0.85), Y(y - 1.9), 1.7 * s, 3.8 * s, s * 0.35) : ctx.rect(X(x - 0.85), Y(y - 1.9), 1.7 * s, 3.8 * s);
      ctx.fill(); ctx.stroke();
    }
  }

  function drawPeople() {
    const s = view.s, t = state.t;
    const r = Math.max(3.5, s * 0.34);
    hits = [];
    for (const p of Object.values(IX.people)) {
      const at = personAt(p, t);
      if (!at || !onFloor(at.x, at.y)) continue;
      hits.push({ p, x: X(at.x), y: Y(at.y) });
      const sel = state.sel && state.sel.type === "person" && state.sel.id === p.id;
      ctx.beginPath();
      ctx.arc(X(at.x), Y(at.y), sel ? r * 1.35 : r, 0, Math.PI * 2);
      ctx.fillStyle = p.colour;
      ctx.fill();
      ctx.lineWidth = sel ? 3 : 1.5;
      ctx.strokeStyle = sel ? palette.text : palette.bg;
      ctx.stroke();
    }
  }
  let hits = [];

  // ---- side panels ----
  function renderKpis() {
    const M = IX.modes[state.mode];
    const si = seriesIndex(R, state.t);
    const kwh = M.series.kwh ? M.series.kwh[si] : energyUpTo(M.series, si);
    $("k-energy").textContent = kwh.toFixed(1) + " kWh";
    const SS = IX.modes.schedule.series;
    const base = SS.kwh ? SS.kwh[si] : energyUpTo(SS, si);
    $("k-energy-l").textContent = state.mode === "schedule"
      ? "Lights + AC so far today"
      : `Lights + AC so far · ${base > 0.5 ? savingText(kwh, base) : "fixed schedule has not started yet"}`;
    $("k-onsite").textContent = Object.values(IX.people).filter((p) => personAt(p, state.t)).length;
    $("k-alerts").textContent = M.log.filter((m) => m.t <= state.t && m.topic.startsWith("office/alert/")).length;
  }

  function savingText(kwh, base) {
    const d = (1 - kwh / base) * 100;
    if (Math.abs(d) < 0.5) return "same as the fixed schedule";
    return d > 0 ? `${d.toFixed(0)}% less than the fixed schedule` : `${(-d).toFixed(0)}% more than the fixed schedule`;
  }

  let lastLogKey = "";
  function renderLog(force) {
    const M = IX.modes[state.mode];
    const only = $("only-alerts").checked;
    const n = bisectRight(M.log, state.t, (m) => m.t);
    const key = state.mode + n + only;
    if (!force && key === lastLogKey) return;
    lastLogKey = key;
    const items = [];
    for (let i = n - 1; i >= 0 && items.length < 150; i--) {
      const m = M.log[i];
      if (!m.text) continue;
      const alert = m.topic.startsWith("office/alert/");
      if (only && !alert) continue;
      const kind = m.topic.split("/").pop();
      const act = kind === "light" || kind === "ac";
      const on = act && /\bon\b/.test(m.text.split("—")[0]);
      items.push(`<li data-msg="${m.id}" class="${alert ? "alert" : ""} ${act ? "act" : ""} ${on ? "on-" + kind : ""}"><span class="t num">${clock(m.t)}</span><span class="x">${esc(m.text)}</span></li>`);
    }
    $("log").innerHTML = items.join("") || `<li><span></span><span class="muted">Nothing yet — press play.</span></li>`;
    $("log-count").textContent = `${items.length}${items.length === 150 ? "+" : ""} shown`;
  }

  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  function fillFinder() {
    const people = Object.values(IX.people).sort((a, b) => a.name.localeCompare(b.name));
    const opt = (v, label) => `<option value="${v}">${esc(label)}</option>`;
    $("find").innerHTML = opt("", "— choose a person or room —")
      + `<optgroup label="People">${people.map((p) => opt("person:" + p.id, `${p.name} · ${ROLE_NAMES[p.role]}`)).join("")}</optgroup>`
      + `<optgroup label="Rooms">${plan.rooms.filter((r) => r.kind !== "outdoor").map((r) => opt("room:" + r.id, r.name)).join("")}</optgroup>`;
    $("find").onchange = (e) => {
      const [type, id] = e.target.value.split(":");
      state.sel = id ? { type, id } : null;
      frame(true);
    };
  }

  function renderInspector() {
    const pane = $("inspect-body");
    const want = state.sel && state.sel.type !== "msg" ? state.sel.type + ":" + state.sel.id : "";
    if ($("find").value !== want) $("find").value = want;
    const M = IX.modes[state.mode];
    const si = seriesIndex(R, state.t);
    if (!state.sel) return;
    if (state.sel.type === "room") {
      const r = rooms[state.sel.id];
      const occ = M.series.occ[r.id] ? M.series.occ[r.id][si] : 0;
      let html = `<h3>${esc(r.name)}</h3>`;
      html += row("People inside (true count)", occ);
      if (M.series.temp[r.id]) html += row("Temperature", M.series.temp[r.id][si].toFixed(1) + " °C");
      if (plan.ac_rooms.includes(r.id)) html += row("CO₂", M.series.co2[r.id][si] + " ppm");
      html += row("Area", ((r.rect[2] - r.rect[0]) * (r.rect[3] - r.rect[1])).toFixed(0) + " m²");
      for (const kind of ["light", "ac", "vent"]) {
        if (kind === "ac" && !plan.ac_rooms.includes(r.id)) continue;
        const d = deviceAt(M, r.id, kind, state.t);
        if (kind === "vent" && d.id == null) continue;
        const name = { light: "Lights", ac: "AC", vent: "Ventilation boost" }[kind];
        html += `<h3>${name}: <span class="pill ${d.on ? "ok" : ""}">${d.on ? "ON" : "OFF"}</span>${d.since != null ? ` <span class="muted num">since ${clock(d.since)}</span>` : ""}</h3>`;
        html += d.id != null ? whyHtml(M, d.id) : `<p class="muted">Never switched today under this rule set.</p>`;
      }
      const bk = R.bookings.filter((b) => b.room === r.id);
      if (bk.length) {
        html += `<h3>Bookings</h3><table><tr><th>Time</th><th>What</th><th>Status</th></tr>`;
        for (const b of bk) {
          const released = M.log.some((m) => m.topic === "office/alert/no_show" && m.text.includes(clock(b.start)) && m.t <= state.t && m.text.includes(r.name));
          html += `<tr><td class="num">${clock(b.start)}–${clock(b.end)}</td><td>${esc(b.title)}</td><td>${released ? '<span class="pill bad">released</span>' : b.attendees.length + " invited"}</td></tr>`;
        }
        html += `</table>`;
      }
      pane.innerHTML = html;
    } else if (state.sel.type === "person") {
      const p = IX.people[state.sel.id];
      const reg = M.register[p.id] || {};
      const at = personAt(p, state.t);
      let html = `<h3 style="color:${p.colour}">${esc(p.name)}</h3>`;
      html += row("Role", ROLE_NAMES[p.role]);
      html += row("Now", esc(labelAt(p, state.t)));
      html += row("Where", at ? roomAt(at.x, at.y) : "Off site");
      html += row("Scheduled", `${clock(p.arrive)} – ${clock(p.leave)}`);
      html += row("Badge in (system)", reg.in != null && reg.in <= state.t ? clock(reg.in) : "—");
      html += row("Badge out (system)", reg.out != null && reg.out <= state.t ? clock(reg.out) : "—");
      html += row("Car", p.car != null ? `Bay ${p.car + 1}` : "No bay");
      if (!p.badge) html += `<p><span class="pill warn">Forgot badge today</span></p>`;
      const tg = R.tailgates.filter(([t, pid]) => pid === p.id && t <= state.t);
      if (tg.length) html += `<p><span class="pill bad">Tailgated at ${tg.map(([t]) => clock(t)).join(", ")}</span></p>`;
      html += `<h3>Day so far</h3><table>`;
      for (const [t, l] of p.labels) if (t <= state.t) html += `<tr><td class="num muted">${clock(t)}</td><td>${esc(l)}</td></tr>`;
      html += `</table>`;
      pane.innerHTML = html;
    } else if (state.sel.type === "msg") {
      const m = M.byId[state.sel.id];
      if (!m) { pane.innerHTML = `<p class="muted">That event does not exist under this rule set.</p>`; return; }
      pane.innerHTML = `<h3>Event at ${clock(m.t)}</h3><p>${esc(m.text)}</p><p class="muted num">topic <code>${esc(m.topic)}</code></p><h3>Why it happened</h3>${whyHtml(M, m.id)}`;
    }
  }
  function row(k, v) { return `<div class="row"><span class="muted">${k}</span><span class="num">${v}</span></div>`; }
  function whyHtml(M, id) {
    const chain = whyChain(M, id);
    if (!chain.length) return `<p class="muted">No recorded cause.</p>`;
    return `<div class="why">${chain.map((m, i) => `<div>${i ? "↳ because " : ""}<span class="t num">${clock(m.t)}</span>${esc(m.text || describe(m))}</div>`).join("")}</div>`;
  }
  function describe(m) {
    const parts = m.topic.split("/");
    if (parts[2] === "motion") return `Motion sensor triggered in ${rooms[parts[1]] ? rooms[parts[1]].name : parts[1]}`;
    const where = rooms[parts[1]] ? rooms[parts[1]].name : parts[1];
    if (parts[2] === "co2") return `CO₂ sensor in ${where} reported ${Math.round(m.payload)} ppm`;
    if (parts[2] === "temp") return `Temperature sensor in ${where} read ${Number(m.payload).toFixed(1)} °C`;
    if (parts[2] === "queue") return `Cafeteria queue counter: ${m.payload}`;
    return m.topic;
  }
  function roomAt(x, y) {
    for (const r of plan.rooms) { const [x0, y0, x1, y1] = r.rect; if (x > x0 && x < x1 && y > y0 && y < y1) return r.name; }
    return "Doorway";
  }

  function renderAttendance() {
    const M = IX.modes[state.mode];
    const t = state.t;
    const list = Object.values(IX.people).filter((p) => p.role !== "visitor").sort((a, b) => a.arrive - b.arrive);
    let inSys = 0, onSite = 0, mismatch = 0;
    const rows = list.map((p) => {
      const reg = M.register[p.id] || {};
      const sysIn = reg.in != null && reg.in <= t;
      const here = !!personAt(p, t);
      const arrived = t >= p.arrive;
      if (sysIn) inSys++;
      if (arrived) onSite++;
      let status;
      if (arrived && !sysIn && here) { status = `<span class="pill bad">on site, not in register</span>`; mismatch++; }
      else if (!arrived) status = `<span class="pill">not arrived</span>`;
      else if (!here) status = reg.out != null && reg.out <= t ? `<span class="pill">left</span>` : `<span class="pill warn">left, no badge-out</span>`;
      else status = `<span class="pill ok">present</span>`;
      const late = p.role in { staff: 1, manager: 1 } && reg.in != null && reg.in >= 9 * 3600 + 16 * 60 && sysIn;
      return `<tr><td>${esc(p.name)}<div class="muted" style="font-size:11.5px">${ROLE_NAMES[p.role]}</div></td><td class="num ${late ? "flag" : ""}">${sysIn ? clock(reg.in) : "—"}</td><td class="num">${reg.out != null && reg.out <= t ? clock(reg.out) : "—"}</td><td>${status}</td></tr>`;
    });
    const S = M.series, si = seriesIndex(R, t);
    const wifi = S.roll_wifi ? S.roll_wifi[si] : null, est = wifi != null ? wifi : S.roll_estimate[si], truth = S.roll_truth[si];
    const off = est - truth;
    $("pane-attendance").innerHTML = `
      <h3>Evacuation roll-call</h3>
      <div class="kpis rc">
        <div class="kpi"><div class="v num">${est}</div><div class="l">Estimated inside${wifi != null ? " (badges + Wi-Fi)" : " the badge line"}</div></div>
        <div class="kpi"><div class="v num ${off ? "flag" : ""}">${truth}</div><div class="l">Truly inside (simulator)</div></div>
      </div>
      <div class="row"><span class="muted">Badge register says inside</span><span class="num">${S.roll_register[si]}</span></div>
      <div class="row"><span class="muted">Door counters say inside</span><span class="num">${S.roll_counter[si]}</span></div>
      ${wifi != null ? `<div class="row"><span class="muted">Badges alone estimate</span><span class="num">${S.roll_estimate[si]}</span></div>` : ""}
      <canvas class="chart" id="rc-chart" style="height:110px"></canvas>
      <p class="muted" style="font-size:12px">${wifi != null ? "Badges + Wi-Fi: a phone on the office Wi-Fi means its owner is in the building, whatever the doors last said (people tap out of one floor and walk in behind a colleague at the other); in the 5 minutes after a badge-out the departing phone is not trusted yet; without a phone, the badge decides. " : ""}Badges alone = register + entries nobody badged for (tailgates) − exits nobody tapped out for. Door counters drift as missed counts pile up, so they are re-zeroed to the badge estimate after 15 minutes of disagreement.</p>
      <h3>Today</h3>
      <div class="row"><span class="muted">Checked in (badge or reception)</span><span class="num">${inSys}</span></div>
      <div class="row"><span class="muted">Arrived (simulator truth)</span><span class="num">${onSite}</span></div>
      <div class="row"><span class="muted">On site but missing from the register</span><span class="num ${mismatch ? "flag" : ""}">${mismatch}</span></div>
      <h3>Register</h3>
      <table><tr><th>Person</th><th>In</th><th>Out</th><th>Status</th></tr>${rows.join("")}</table>
      <p class="muted" style="font-size:12px">Late (red) = staff checking in at 09:16 or later. The register is built only from badge reads and reception check-ins; the truth column comes from the simulator, which a real building would not have.</p>`;
  }

  function drawRollcall() {
    const c = document.getElementById("rc-chart");
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    c.width = w * dpr; c.height = h * dpr;
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const S = IX.modes[state.mode].series;
    const max = Math.max(...S.roll_truth, ...S.roll_estimate, ...(S.roll_wifi || []), 1) * 1.1;
    const xs = (t) => (w * (t - R.meta.t0)) / (R.meta.t1 - R.meta.t0);
    const ys = (v) => h - 22 - (h - 30) * (v / max);   // leave the bottom strip for the legend
    const line = (arr, col, width, dash) => {
      g.strokeStyle = col; g.lineWidth = width; g.setLineDash(dash || []);
      g.beginPath(); S.t.forEach((t, i) => (i ? g.lineTo(xs(t), ys(arr[i])) : g.moveTo(xs(t), ys(arr[i])))); g.stroke();
      g.setLineDash([]);
    };
    line(S.roll_counter, palette.muted, 1, [3, 3]);
    line(S.roll_truth, palette.people, 3);
    line(S.roll_estimate, palette.muted, 1.2);
    if (S.roll_wifi) line(S.roll_wifi, palette.accent, 1.8);
    g.strokeStyle = palette.text; g.globalAlpha = 0.5;
    g.beginPath(); g.moveTo(xs(state.t), 0); g.lineTo(xs(state.t), h - 14); g.stroke(); g.globalAlpha = 1;
    g.font = "11px Segoe UI, system-ui"; g.textAlign = "left";
    let kx = 6;
    [["truth", palette.people], ["badges + Wi-Fi", palette.accent], ["badges", palette.muted], ["counters ┄", palette.muted]].forEach(([n, col]) => {
      g.fillStyle = col; g.fillRect(kx, h - 9, 10, 3); g.fillStyle = palette.muted; g.fillText(n, kx + 14, h - 4);
      kx += 14 + g.measureText(n).width + 14;
    });
  }

  function renderCompare() {
    const names = Object.keys(R.modes);
    const ms = names.map((n) => R.modes[n].metrics);
    const rowsDef = [
      ["Lights + AC, kWh", "total_kwh", "", "min"],
      ["Lights, kWh", "light_kwh", "", "min"],
      ["AC, kWh", "ac_kwh", "", "min"],
      ["Person-minutes in the dark", "person_min_in_dark", "", "min"],
      ["Person-minutes too warm (>26 °C)", "person_min_too_warm", "", "min"],
      ["Person-minutes stuffy (CO₂ >1000)", "person_min_stuffy", "", "min"],
      ["Lights off on someone (false-offs)", "false_offs", "", "min"],
      ["Room-minutes lit while empty", "room_min_lit_empty", "", "min"],
    ];
    let html = `<h3>Power through the day</h3><canvas class="chart" id="chart"></canvas>
      <h3>Whole day, same people, three rule sets</h3>
      <table class="cmp"><tr><th></th>${names.map((n) => `<th>${MODE_NAMES[n]}</th>`).join("")}</tr>`;
    for (const [label, key, unit] of rowsDef) {
      const vals = ms.map((m) => m[key]);
      const best = Math.min(...vals);
      html += `<tr><td>${label}</td>${vals.map((v) => `<td class="num ${v === best ? "best" : ""}">${fmt(v)}${unit}</td>`).join("")}</tr>`;
    }
    html += `</table>`;
    const m0 = ms[0];
    html += `<h3>Gate and attendance</h3>
      ${row("Tailgates that happened", m0.tailgates_true)}
      ${row("Tailgates caught by counter-vs-badge check", m0.tailgates_caught)}
      ${row("False tailgate alarms", m0.tailgate_false_alarms)}
      ${row("Door-counter misses", m0.beam_misses)}
      <p class="muted" style="font-size:12px">All numbers are from the simulator, not a real building. The people, meetings and arrivals are identical in every column; only the rules differ.</p>`;
    $("pane-energy").innerHTML = html;
    drawChart();
  }

  function fmt(v) { return Number.isInteger(v) ? v.toLocaleString("en") : v.toFixed(1); }
  function smooth(a, k) {
    const out = new Array(a.length);
    let sum = 0;
    for (let i = 0; i < a.length; i++) {
      sum += a[i];
      if (i >= k) sum -= a[i - k];
      out[i] = sum / Math.min(i + 1, k);
    }
    return out;
  }

  function drawChart() {
    const c = document.getElementById("chart");
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    c.width = w * dpr; c.height = h * dpr;
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const names = Object.keys(R.modes);
    const cols = { schedule: palette.muted, pir: palette.warn, "pir+co2": palette.accent };
    const series = names.map((n) => R.modes[n].series);
    // AC compressors cycle on a thermostat, so raw kW is a comb; show 15-minute means
    const totals = series.map((s) => smooth(s.light_kw.map((v, i) => v + s.ac_kw[i]), 15));
    const max = Math.max(...totals.flat()) * 1.15 || 1;
    const L = 34, B = 18, top = 22;
    g.font = "11px Segoe UI, system-ui";
    g.fillStyle = palette.muted;
    g.strokeStyle = palette.line;
    g.lineWidth = 1;
    for (let k = 0; k <= 4; k++) {
      const y = top + (h - B - top) * (1 - k / 4);
      g.beginPath(); g.moveTo(L, y); g.lineTo(w - 4, y); g.stroke();
      g.textAlign = "right"; g.fillText((max * k / 4).toFixed(0), L - 5, y + 4);
    }
    g.textAlign = "center";
    for (let hr = 8; hr <= 20; hr += 2) {
      const x = L + (w - L - 4) * ((hr * 3600 - R.meta.t0) / (R.meta.t1 - R.meta.t0));
      g.fillText(String(hr).padStart(2, "0"), x, h - 4);
    }
    names.forEach((n, j) => {
      const s = series[j];
      g.strokeStyle = cols[n]; g.lineWidth = n === state.mode ? 2.4 : 1.4;
      g.setLineDash(n === "schedule" ? [5, 4] : []);
      g.beginPath();
      s.t.forEach((t, i) => {
        const x = L + (w - L - 4) * ((t - R.meta.t0) / (R.meta.t1 - R.meta.t0));
        const y = top + (h - B - top) * (1 - totals[j][i] / max);
        i ? g.lineTo(x, y) : g.moveTo(x, y);
      });
      g.stroke();
      g.setLineDash([]);
    });
    const x = L + (w - L - 4) * ((state.t - R.meta.t0) / (R.meta.t1 - R.meta.t0));
    g.strokeStyle = palette.text; g.globalAlpha = 0.5; g.beginPath(); g.moveTo(x, top); g.lineTo(x, h - B); g.stroke(); g.globalAlpha = 1;
    g.textAlign = "left";
    let lx = L + 6;
    names.forEach((n) => {
      if (n === "schedule") { g.fillStyle = cols[n]; g.fillRect(lx, 6, 4, 3); g.fillRect(lx + 7, 6, 4, 3); }
      else { g.fillStyle = cols[n]; g.fillRect(lx, 6, 11, 3); }
      g.fillStyle = palette.muted; g.fillText(MODE_NAMES[n], lx + 14, 11); lx += g.measureText(MODE_NAMES[n]).width + 26; });
    g.fillText("kW", 2, 11);
  }

  function renderTimeline() {
    const w = tl.clientWidth, h = tl.clientHeight;
    tctx.clearRect(0, 0, w, h);
    const M = IX.modes[state.mode];
    const s = M.series;
    const max = Math.max(...s.on_site, 1);
    const xs = (t) => (w * (t - R.meta.t0)) / (R.meta.t1 - R.meta.t0);
    tctx.fillStyle = rgba(palette.people, 0.25);
    tctx.beginPath(); tctx.moveTo(0, h);
    s.t.forEach((t, i) => tctx.lineTo(xs(t), h - (h - 10) * (s.on_site[i] / max)));
    tctx.lineTo(w, h); tctx.closePath(); tctx.fill();
    for (const m of M.log) {
      if (!m.topic.startsWith("office/alert/")) continue;
      tctx.fillStyle = palette.alert;
      tctx.fillRect(xs(m.t) - 1, 0, 2, 7);
    }
    const x = xs(state.t);
    tctx.fillStyle = palette.accent;
    tctx.fillRect(x - 1.5, 0, 3, h);
  }

  function renderLegend() {
    const L = {
      state: `<span><i style="background:${palette.light}" class="sq"></i>Lights on</span><span><i style="border:2px dashed ${palette.ac};background:transparent" class="sq"></i>AC on</span>`,
      occ: `<span><i style="background:${palette.people}" class="sq"></i>More people = darker</span>`,
      temp: `<span><i style="background:#38bdf8" class="sq"></i>22°</span><span><i style="background:#a3e635" class="sq"></i>26°</span><span><i style="background:#f87171" class="sq"></i>30°+</span>`,
      co2: `<span><i style="background:#34d399" class="sq"></i>420</span><span><i style="background:#fbbf24" class="sq"></i>870</span><span><i style="background:#f87171" class="sq"></i>1320+ ppm</span>`,
    }[state.layer];
    const roles = [...new Set(Object.values(IX.people).map((p) => p.role))];
    $("legend").innerHTML = L + roles.map((r) => `<span><i style="background:${R.people.find((p) => p.role === r).colour}"></i>${ROLE_NAMES[r]}</span>`).join("");
  }

  function renderTicks() {
    const out = [];
    for (let hr = 7; hr <= 21; hr++) out.push(`<span>${String(hr).padStart(2, "0")}</span>`);
    $("ticks").innerHTML = out.join("");
  }

  // ---- frame loop ----
  let lastPanel = 0;
  function frame(force) {
    $("clock").textContent = clock(state.t);
    scrub.value = state.t;
    draw();
    renderTimeline();
    const now = performance.now();
    if (force || now - lastPanel > 250) {
      lastPanel = now;
      renderKpis();
      renderLog(force);
      if ($("pane-inspect").classList.contains("on")) renderInspector();
      if ($("pane-attendance").classList.contains("on")) { renderAttendance(); drawRollcall(); }
      if ($("pane-energy").classList.contains("on")) drawChart();
    }
  }
  let prev = null;
  function loop(ts) {
    if (state.playing) {
      if (prev != null) state.t = Math.min(R.meta.t1 - 1, state.t + ((ts - prev) / 1000) * state.speed);
      if (state.t >= R.meta.t1 - 1) setPlaying(false);
      frame(false);
    }
    prev = ts;
    requestAnimationFrame(loop);
  }

  function setPlaying(on) {
    state.playing = on;
    $("play").textContent = on ? "❚❚ Pause" : "▶ Play";
    $("play").setAttribute("aria-label", on ? "Pause" : "Play");
  }
  function save() {
    try { localStorage.setItem("office-twin", JSON.stringify({ theme: document.documentElement.dataset.theme, mode: state.mode })); } catch (e) { /* ignore */ }
  }

  // ---- events ----
  $("play").onclick = () => { if (state.t >= R.meta.t1 - 1) state.t = R.meta.t0; setPlaying(!state.playing); };
  $("speed").onchange = (e) => { state.speed = +e.target.value; };
  scrub.oninput = () => { state.t = +scrub.value; frame(true); };
  for (const b of document.querySelectorAll("#modes button")) {
    b.onclick = () => {
      state.mode = b.dataset.mode;
      for (const x of document.querySelectorAll("#modes button")) x.setAttribute("aria-pressed", x === b);
      save();
      if ($("pane-energy").classList.contains("on")) renderCompare();
      frame(true);
    };
    b.setAttribute("aria-pressed", b.dataset.mode === state.mode);
  }
  for (const b of document.querySelectorAll("#layers button")) {
    b.onclick = () => {
      state.layer = b.dataset.layer;
      for (const x of document.querySelectorAll("#layers button")) x.setAttribute("aria-pressed", x === b);
      renderLegend();
      frame(true);
    };
  }
  function showTab(name) {
    for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", b.dataset.tab === name);
    for (const p of document.querySelectorAll(".pane")) p.classList.toggle("on", p.id === "pane-" + name);
    if (name === "attendance") { renderAttendance(); drawRollcall(); }
    if (name === "energy") renderCompare();
    if (name === "inspect") renderInspector();
  }
  for (const b of document.querySelectorAll(".tabs button")) b.onclick = () => showTab(b.dataset.tab);
  $("only-alerts").onchange = () => renderLog(true);
  $("log").onclick = (e) => {
    const li = e.target.closest("li[data-msg]");
    if (!li) return;
    state.sel = { type: "msg", id: +li.dataset.msg };
    showTab("inspect");
    frame(true);
  };
  $("theme").onclick = () => {
    const dark = document.documentElement.dataset.theme !== "light";
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    $("theme").textContent = dark ? "Dark" : "Light";
    readPalette(); renderLegend(); save();
    if ($("pane-energy").classList.contains("on")) renderCompare();
    frame(true);
  };

  function pick(ev) {
    const rect = cv.getBoundingClientRect();
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    let best = null, bd = Math.max(9, view.s * 0.6);
    for (const h of hits) { const d = Math.hypot(h.x - mx, h.y - my); if (d < bd) { bd = d; best = h; } }
    if (best) return { type: "person", id: best.p.id };
    const wx = (mx - view.ox) / view.s + F().origin[0], wy = (my - view.oy) / view.s + F().origin[1];
    for (const r of RM()) { const [x0, y0, x1, y1] = r.rect; if (wx > x0 && wx < x1 && wy > y0 && wy < y1) return { type: "room", id: r.id }; }
    return null;
  }
  cv.addEventListener("click", (ev) => {
    const p = pick(ev);
    state.sel = p;
    if (p) showTab("inspect");
    frame(true);
  });
  cv.addEventListener("mousemove", (ev) => {
    const p = pick(ev);
    const tip = $("tip");
    if (!p) { tip.style.display = "none"; return; }
    const rect = cv.getBoundingClientRect();
    let html;
    if (p.type === "person") { const q = IX.people[p.id]; html = `<b>${esc(q.name)}</b> · ${ROLE_NAMES[q.role]}<br><span class="muted">${esc(labelAt(q, state.t))}</span>`; }
    else { const r = rooms[p.id]; const M = IX.modes[state.mode]; const si = seriesIndex(R, state.t); html = `<b>${esc(r.name)}</b>` + (M.series.occ[r.id] ? `<br><span class="muted">${M.series.occ[r.id][si]} inside · ${M.series.temp[r.id][si].toFixed(1)} °C</span>` : ""); }
    tip.innerHTML = html;
    tip.style.display = "block";
    const x = ev.clientX - rect.left + 14, y = ev.clientY - rect.top + 14;
    tip.style.left = Math.min(x, rect.width - tip.offsetWidth - 6) + "px";
    tip.style.top = Math.min(y, rect.height - tip.offsetHeight - 6) + "px";
  });
  cv.addEventListener("mouseleave", () => { $("tip").style.display = "none"; });
  document.addEventListener("keydown", (e) => {
    // a focused control keeps its own keys: arrows move a select or slider, space presses a button
    if (["INPUT", "SELECT", "BUTTON", "TEXTAREA"].includes(e.target.tagName)) return;
    if (e.code === "Space") { e.preventDefault(); $("play").click(); }
    if (e.key === "ArrowRight") { state.t = Math.min(R.meta.t1 - 1, state.t + 300); frame(true); }
    if (e.key === "ArrowLeft") { state.t = Math.max(R.meta.t0, state.t - 300); frame(true); }
  });
  window.addEventListener("resize", () => { fit(); frame(true); });

  // ---- start ----
  $("theme").textContent = document.documentElement.dataset.theme === "light" ? "Dark" : "Light";
  readPalette();
  fit();
  fillFinder();
  renderLegend();
  renderTicks();
  frame(true);
  requestAnimationFrame(loop);
  function renderFloors() {
    const count = {};
    for (const p of Object.values(IX.people)) { const at = personAt(p, state.t); if (at) { const f = floorOf(at.x, at.y); count[f] = (count[f] || 0) + 1; } }
    const html = [...FLOORS].sort((a, b) => b.level - a.level).map((f) => `<button data-floor="${f.id}" aria-pressed="${f.id === F().id}" title="${f.name}: ${count[f.id] || 0} people now">${f.id} <span class="muted num">(${count[f.id] || 0})</span></button>`).join("");
    const box = $("floors"); if (!box) return;
    if (box.dataset.html !== html) { box.innerHTML = html; box.dataset.html = html; }
    box.style.display = FLOORS.length > 1 ? "" : "none";
  }
  function setFloor(f) { state.floor = f; fit(); frame(true); }
  if ($("floors")) $("floors").onclick = (e) => { const b = e.target.closest("button[data-floor]"); if (b) setFloor(b.dataset.floor); };
  setInterval(renderFloors, 400);
  renderFloors();
  window.__twin = { state, frame, showTab, IX, hits: () => hits, setFloor, floorOf };
})();

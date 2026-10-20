/* Shared viewer core for the Lahore Twin pages (office, home): pure functions,
 * no DOM. Loaded by every page before its own script, and by tests under node.
 *
 * Office viewer notes:
 *
 * The page only draws what the simulator recorded. Positions come from routed
 * trips (start time, speed, polyline), devices from their change log, and the
 * "why" panel from each message's cause id. Nothing here re-simulates.
 */
"use strict";

// ---------- core (no DOM; also loaded by tests under node) ----------

function bisectRight(arr, x, key) {
  let lo = 0, hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (key(arr[mid]) <= x) lo = mid + 1; else hi = mid;
  }
  return lo;
}

// floor-change segments (stairs, lifts, ramps) and their real lengths, from plan.portal_hops;
// the walker waits where they got on, then appears where they get off, as in the simulator
const HOPS = new Map();
const hopKey = (ax, ay, bx, by) => [ax, ay, bx, by].map((v) => Math.round(v * 1000) / 1000).join(",");
function setHops(list) {
  HOPS.clear();
  for (const [ax, ay, bx, by, m] of list || []) HOPS.set(hopKey(ax, ay, bx, by), m);
}

function pointAlong(pts, dist) {
  for (let i = 0; i < pts.length - 1; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[i + 1];
    const hop = HOPS.get(hopKey(ax, ay, bx, by));
    const seg = hop != null ? hop : Math.hypot(bx - ax, by - ay);
    if (dist <= seg) {
      if (hop != null) return [ax, ay, true];
      const f = seg ? dist / seg : 0;
      return [ax + (bx - ax) * f, ay + (by - ay) * f, true];
    }
    dist -= seg;
  }
  const last = pts[pts.length - 1];
  return [last[0], last[1], false];
}

function buildIndex(R) {
  const people = {};
  for (const p of R.people) {
    people[p.id] = { ...p, trips: [], labels: [], gone: Infinity, entry: null };
  }
  for (const tr of R.trips) people[tr.p].trips.push(tr);
  for (const [t, pid, label] of R.labels) {
    people[pid].labels.push([t, label]);
    if (label === "Gone home") people[pid].gone = t;
  }
  for (const p of Object.values(people)) {
    p.trips.sort((a, b) => a.t - b.t);
    if (p.trips.length) p.entry = p.trips[0].pts[0];
  }
  const modes = {};
  for (const [name, M] of Object.entries(R.modes)) {
    const dev = {};
    for (const ch of M.devices) {
      const [t, room, kind, val, id] = ch;
      const k = room + "/" + kind;
      (dev[k] = dev[k] || []).push([t, val, id]);
    }
    const byId = {};
    for (const m of M.log) byId[m.id] = m;
    modes[name] = { ...M, dev, byId };
  }
  return { people, modes };
}

function personAt(p, t) {
  if (t < p.arrive || t >= p.gone) return null;
  const i = bisectRight(p.trips, t, (tr) => tr.t) - 1;
  if (i < 0) return p.entry ? { x: p.entry[0], y: p.entry[1], moving: false } : null;
  const tr = p.trips[i];
  const [x, y, moving] = pointAlong(tr.pts, (t - tr.t) * tr.v);
  return { x, y, moving };
}

function labelAt(p, t) {
  const i = bisectRight(p.labels, t, (l) => l[0]) - 1;
  return i >= 0 ? p.labels[i][1] : "Not here yet";
}

function deviceAt(mode, room, kind, t) {
  const arr = mode.dev[room + "/" + kind];
  if (!arr) return { on: false, id: null };
  const i = bisectRight(arr, t, (c) => c[0]) - 1;
  return i >= 0 ? { on: !!arr[i][1], id: arr[i][2], since: arr[i][0] } : { on: false, id: null };
}

function whyChain(mode, id) {
  const out = [];
  const seen = new Set();
  while (id != null && mode.byId[id] && !seen.has(id)) {
    seen.add(id);
    out.push(mode.byId[id]);
    id = mode.byId[id].cause;
  }
  return out;
}

function clock(t) {
  t = Math.max(0, Math.floor(t));
  return String(Math.floor(t / 3600)).padStart(2, "0") + ":" + String(Math.floor((t % 3600) / 60)).padStart(2, "0");
}

function seriesIndex(R, t) {
  return Math.max(0, Math.min(R.modes[Object.keys(R.modes)[0]].series.t.length - 1, Math.floor((t - R.meta.t0) / 60)));
}

function energyUpTo(series, idx) {
  let kwh = 0;
  for (let i = 0; i < idx && i < series.t.length; i++) kwh += (series.light_kw[i] + series.ac_kw[i]) / 60;
  return kwh;
}

const TwinCore = { bisectRight, pointAlong, setHops, buildIndex, personAt, labelAt, deviceAt, whyChain, clock, energyUpTo, seriesIndex };
if (typeof module !== "undefined") module.exports = TwinCore;

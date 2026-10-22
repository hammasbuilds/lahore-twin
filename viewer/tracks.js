/* Vehicle tracks for the junction planner and the city systems: each vehicle's point on the road
 * every few seconds (lahore_twin/tracks.py), moved smoothly between samples and drawn the way the
 * traffic page draws its vehicles (same colours, sizes and rim).
 *
 *   const tr = TwinTracks.decode(data);              // once per data set
 *   TwinTracks.draw(ctx, tr, t, SX, SY, pxPerMetre, colours, hits)
 */
"use strict";

window.TwinTracks = (function () {
  const SIZE = { motorcycle: [2.0, 0.8], car: [4.5, 1.8], rickshaw: [2.8, 1.4], bus: [11, 2.5], ambulance: [5.5, 2.0] };
  const NAMES = { motorcycle: "Motorcycle", car: "Car", rickshaw: "Rickshaw", bus: "Bus / van", ambulance: "Ambulance" };

  function decode(data) {
    if (!data) return null;
    const q = data.q || 1;
    const list = data.v.map(([ki, t0, flat, runs]) => {
      // the points where it moved, with each standing run ([k, n]: n more samples where point k was) put back
      const moved = flat.length / 2, extra = new Map((runs || []).map(([k, c]) => [k, c]));
      let n = moved; for (const c of extra.values()) n += c;
      const xs = new Float32Array(n), ys = new Float32Array(n), still = new Set();
      let x = 0, y = 0, s = 0;
      for (let k = 0; k < moved; k++) {
        x += flat[2 * k]; y += flat[2 * k + 1];
        xs[s] = x * q; ys[s] = y * q; s++;
        const c = extra.get(k) || 0;
        if (c) { still.add(s - 1); for (let r = 0; r < c; r++) { xs[s] = x * q; ys[s] = y * q; still.add(s); s++; } }
      }
      return { kind: data.kinds[ki], t0, t1: t0 + (n - 1) * data.dt, xs, ys, still };
    });
    list.sort((a, b) => a.t0 - b.t0);
    return { dt: data.dt, list, maxSpan: list.reduce((m, v) => Math.max(m, v.t1 - v.t0), 0) };
  }

  // where one track is at time t: position, heading, and whether it is standing
  function at(tr, v, t) {
    if (t < v.t0 || t > v.t1) return null;
    const f = (t - v.t0) / tr.dt, k = Math.min(Math.floor(f), v.xs.length - 1), u = f - k;
    const k2 = Math.min(k + 1, v.xs.length - 1);
    const x = v.xs[k] + (v.xs[k2] - v.xs[k]) * u, y = v.ys[k] + (v.ys[k2] - v.ys[k]) * u;
    // heading from the nearest sample pair that moved, so a queued vehicle keeps pointing the right way
    let hx = 0, hy = 0;
    for (let a = k, b = k2, tries = 0; tries < 6 && !(hx || hy); tries++) {
      hx = v.xs[b] - v.xs[a]; hy = v.ys[b] - v.ys[a];
      if (!(hx || hy)) { if (b < v.xs.length - 1) { a++; b++; } else if (a > 0) { a--; b--; } else break; }
    }
    const L = Math.hypot(hx, hy) || 1;
    return { x, y, hx: hx / L, hy: hy / L, still: v.still.has(k) && v.still.has(k2), speed: Math.hypot(v.xs[k2] - v.xs[k], v.ys[k2] - v.ys[k]) / tr.dt };
  }

  // every track live at t (tracks are sorted by start, so the scan stops early)
  function live(tr, t) {
    const out = [];
    for (const v of tr.list) {
      if (v.t0 > t) break;
      if (t - v.t0 > tr.maxSpan) continue;
      const p = at(tr, v, t);
      if (p) out.push([v, p]);
    }
    return out;
  }

  function draw(ctx, tr, t, SX, SY, z, col, hits, opt = {}) {
    if (!tr) return 0;
    const L = live(tr, t);
    for (const [v, p] of L) {
      const sx = SX(p.x), sy = SY(p.y);
      if (sx < -20 || sy < -20 || sx > ctx.canvas.clientWidth + 20 || sy > ctx.canvas.clientHeight + 20) continue;
      ctx.fillStyle = col[v.kind] || col.car;
      if (z < 0.6) {                                   // a whole-city view: one dot per vehicle
        const r = opt.dot || 1.6;
        ctx.fillRect(sx - r / 2, sy - r / 2, r, r);
      } else {
        const [l0, w0] = SIZE[v.kind] || SIZE.car;
        const l = Math.max(v.kind === "motorcycle" ? 5 : 8, l0 * z), wd = Math.max(v.kind === "motorcycle" ? 3 : 4, w0 * z);
        ctx.save(); ctx.translate(sx, sy);
        ctx.rotate(Math.atan2(SY(p.y + p.hy) - sy, SX(p.x + p.hx) - sx));
        ctx.strokeStyle = opt.rim || "rgba(0,0,0,.5)"; ctx.lineWidth = 1;
        ctx.fillRect(-l / 2, -wd / 2, l, wd); ctx.strokeRect(-l / 2, -wd / 2, l, wd);
        ctx.restore();
      }
      if (hits && z >= 0.6) hits.push({ veh: true, x: sx, y: sy, r: 7, text: `${NAMES[v.kind] || v.kind} · ${p.still ? "standing" : Math.round(p.speed * 3.6) + " km/h"}` });
    }
    return L.length;
  }

  return { decode, at, live, draw, NAMES };
})();

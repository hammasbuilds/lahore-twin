/* "Watch the demo": the app runs itself. Every module is simulated from real inputs through
 * the local server, then opened and driven through its own buttons — play, floors, views,
 * following someone, the comparison — with a caption saying what is on screen.
 * Needs serve.py (the runs are real simulations). Loaded by index.html after shell.js. */
"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  const S = window.__shell;
  const PLAN = [
    { key: "office", glob: "__twin", inputs: { seed: 11, staff: 36, visitors: 6 },
      about: "a working day for 36 staff with desks and 6 visitors" },
    { key: "hospital", glob: "__hosp", inputs: { seed: 7, arrivals_pct: 120, ward_nurses: 3, alarm_delay: 15 },
      about: "a full day with 120% emergency arrivals, 3 ward nurses a shift and a 15 s alarm delay" },
    { key: "traffic", glob: "__traffic", inputs: { seed: 7, per_hour: 9000 },
      about: "a morning peak of 9,000 trips an hour" },
    { key: "home", glob: "__home", inputs: { seed: 3, season: "june", category: "V", pv_kwp: 6, battery_kwh: 10 },
      about: "a June day with 6 hours of load-shedding, 6 kWp of solar and a 10 kWh battery — four controllers, each after a warm-up day" },
  ];
  let on = false;
  class Stopped extends Error {}
  const wait = (ms) => new Promise((ok, no) => {
    const end = Date.now() + ms;
    (function tick() { if (!on) return no(new Stopped()); if (Date.now() >= end) return ok(); setTimeout(tick, 100); })();
  });
  function caption(title, text) {
    $("demo-title").textContent = title;
    $("demo-text").textContent = text;
  }
  async function runFor(step) {
    const r = await fetch(`/api/run/${step.key}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(step.inputs) });
    const out = await r.json();
    if (!r.ok) throw new Error(out.error || r.statusText);
    return out.replay;
  }
  async function moduleWindow(glob) {
    for (let i = 0; i < 200; i++) {
      const f = $("frame");
      try { if (f.contentWindow && f.contentWindow[glob]) return f.contentWindow; } catch (e) { /* not ready */ }
      await wait(150);
    }
    throw new Error("module did not open");
  }
  // drive the module through its own controls
  function ui(w) {
    const d = w.document;
    return {
      click: (sel) => { const el = d.querySelector(sel); if (el) el.click(); },
      play: (speed) => { const p = d.getElementById("play"); if (speed) { const s = d.getElementById("speed"); if (s) { s.value = String(speed); s.dispatchEvent(new Event("change")); } } if (!/Pause/.test(p.textContent)) p.click(); },
      pause: () => { const p = d.getElementById("play"); if (/Pause/.test(p.textContent)) p.click(); },
    };
  }
  const at = (w, glob, hhmm, base = 0) => { const [h, m] = hhmm.split(":").map(Number); w[glob].state.t = h * 3600 + m * 60 - base; w[glob].frame(true); };

  const SHOW = {
    async office(w) {
      const u = ui(w), G = "__twin";
      at(w, G, "08:55");
      u.click('#floors button[data-floor="B1"]');
      caption("Office tower · basement", "8:55 — cars come down the ramp into the basement; drivers walk to the lifts.");
      u.play(60); await wait(9000);
      u.click('#floors button[data-floor="G"]');
      caption("Office tower · ground floor", "Badge readers count everyone in; lights and AC follow motion and CO₂ room by room.");
      await wait(9000);
      u.click('#floors button[data-floor="1"]');
      caption("Office tower · first floor", "The second office has its own badge door; lifts land only in public lobbies.");
      u.play(300); await wait(8000); u.pause();
      u.click(".tabs button[data-tab=attendance]");
      caption("Attendance", "Who arrived late, tailgating the door counters caught, and the evacuation roll-call.");
      await wait(6000);
      u.click(".tabs button[data-tab=energy]");
      caption("The result", "Motion + CO₂ against a fixed timetable: the same people, the same day.");
      await wait(7000);
    },
    async hospital(w) {
      const u = ui(w), G = "__hosp";
      u.click('#modes button[data-mode="connected"]');
      u.click('#views button[data-view="ed"]'); at(w, G, "10:00");
      caption("Hospital · emergency department", "Patients arrive, are triaged by colour, wait for a bed or a doctor; the board on the right updates live.");
      u.play(300); await wait(9000);
      u.click('#views button[data-view="ward"]');
      caption("Hospital · ward, floor 2", "Call buttons light up, monitor alarms pulse; badges route each one to the bed's nurse.");
      await wait(9000);
      u.click('#views button[data-view="site"]');
      caption("Hospital · campus", "Porters wheel admitted patients across the Lahore General Hospital campus, from OpenStreetMap.");
      await wait(7000); u.pause();
      u.click(".tabs button[data-tab=compare]");
      caption("The result", "Today vs Connected on the same patients: alarms, equipment searches, fridges, bed turnaround.");
      await wait(8000);
    },
    async traffic(w) {
      const u = ui(w), G = "__traffic";
      w[G].state.t = 20 * 60; w[G].frame(true);
      caption("Lahore traffic · the map", "Real roads from OpenStreetMap: Gulberg, Kalma Chowk, Garden Town and the Canal Road.");
      await wait(5000);
      u.click("#follow-random");
      caption("Riding along", "The camera follows one vehicle; the map streams in around it like a game map.");
      u.play(15); await wait(12000); u.pause();
      u.click(".tabs button[data-tab=hot]"); u.click("#pane-hot li[data-sig]");
      caption("The worst junction", "Signals change on every approach; the panel counts who is waiting.");
      u.play(15); await wait(7000); u.pause();
      u.click(".tabs button[data-tab=compare]");
      caption("The result", "Fixed against adaptive signals, on exactly the same trips.");
      await wait(7000);
    },
    async home(w) {
      const u = ui(w), G = "__home";
      u.click('#modes button[data-mode="gridsense"]');
      // the inputs change the day, so go to the moments this run's controller actually acted
      const log = w.HOME.modes.gridsense.log;
      const sun = log.find((m) => /^(Pump|Washer) on .*solar surplus/.test(m.text)) || log.find((m) => /solar surplus/.test(m.text));
      const cool = log.find((m) => /pre-cool/.test(m.text));
      const hhmm = (t) => String(Math.floor(t / 3600)).padStart(2, "0") + ":" + String(Math.floor(t % 3600 / 60)).padStart(2, "0");
      if (sun) { w[G].state.t = Math.max(0, sun.t - 60); w[G].frame(true); } else at(w, G, "11:00");
      u.click('#floors button[data-floor="R"]');
      caption("Home · the roof", sun ? `${hhmm(sun.t)} — ${sun.text}` : "The panels make power through the morning.");
      u.play(300); await wait(8000);
      if (cool) {
        w[G].state.t = Math.max(0, cool.t - 30); w[G].frame(true); u.click('#floors button[data-floor="1"]');
        caption("Home · the bedrooms", `${hhmm(cool.t)} — ${cool.text}`);
      } else {
        at(w, G, "22:30"); u.click('#floors button[data-floor="1"]');
        caption("Home · the bedrooms", "Night: GridSense keeps a battery reserve for the next power cut.");
      }
      await wait(9000); u.pause();
      u.click(".tabs button[data-tab=compare]");
      caption("The result", "Four ways to run the same house through the same load-shedding.");
      await wait(8000);
    },
  };

  async function start() {
    if (on) return;
    if (location.protocol === "file:") { alert("The demo runs real simulations: start run.bat and open http://127.0.0.1:8860"); return; }
    on = true;
    document.body.classList.add("demo-on");
    try {
      S.go("overview");
      caption("Lahore Twin", "Four IoT systems for a city like Lahore. Each one is now being simulated from real inputs — watch.");
      // ask for every run now: the server works through them while the first ones are shown
      const runs = PLAN.map((step) => ({ step, replay: runFor(step) }));
      await wait(5000);
      for (const { step, replay } of runs) {
        const title = window.TWIN_ABOUT[step.key].title;
        const t0 = Date.now();
        let done = false, rel = null;
        replay.then((r) => { done = true; rel = r; }, (e) => { done = true; rel = e; });
        while (!done) {
          caption(title, `Simulating ${step.about}… ${Math.round((Date.now() - t0) / 1000)} s`);
          await wait(1000);
        }
        if (rel instanceof Error) throw rel;
        S.go(step.key, rel);
        const w = await moduleWindow(step.glob);
        await wait(800);
        await SHOW[step.key](w);
      }
      S.go("overview");
      caption("That was Lahore Twin", "Every module ran from its inputs on its own. Try “Run with your values” on any card.");
      await wait(9000);
    } catch (e) {
      if (!(e instanceof Stopped)) caption("Demo stopped", String(e.message || e));
    } finally {
      on = false;
      setTimeout(() => document.body.classList.remove("demo-on"), on ? 0 : 4000);
    }
  }
  function stop() { on = false; document.body.classList.remove("demo-on"); }
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-demo]")) start();
    if (e.target.closest("#demo-stop")) stop();
  });
  if (window.__startHash === "#demo" || location.hash === "#demo") setTimeout(start, 300);
  window.__demo = { start, stop, running: () => on };
})();

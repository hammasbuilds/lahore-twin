/* Lahore Twin shell: one interface for every module. The overview shows each
 * module's headline numbers; opening one loads its own dashboard in the frame.
 * "Run with your values" asks the local server (serve.py) to simulate a new day
 * with the user's inputs and opens the module on that run. */
"use strict";

(function () {
  const A = window.TWIN_ABOUT, SUM = window.TWIN_SUMMARY || {};
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const KEYS = Object.keys(A);
  const STATUS = { ready: "Ready", building: "In development", planned: "Planned" };

  // the inputs each module accepts from the form (server checks them again)
  const RUN = {
    office: [
      ["seed", "Day (seed)", "number", 7, 1, 999],
      ["staff", "Staff with desks", "number", 36, 10, 36],
      ["visitors", "Visitors", "number", 4, 0, 8],
    ],
    home: [
      ["seed", "Day (seed)", "number", 7, 1, 999],
      ["season", "Season", "select", "june", ["june", "october"]],
      ["category", "Feeder category", "select", "IV", ["I", "III", "IV", "V"]],
      ["pv_kwp", "Solar panels (kWp)", "number", 6, 0, 12],
      ["battery_kwh", "Battery (kWh)", "number", 10, 0, 20],
    ],
    traffic: [
      ["seed", "Morning (seed)", "number", 7, 1, 999],
      ["per_hour", "Trips per hour", "number", 8000, 2000, 12000],
    ],
    hospital: [
      ["seed", "Day (seed)", "number", 7, 1, 999],
      ["arrivals_pct", "Emergency arrivals (%)", "number", 100, 50, 200],
      ["ward_nurses", "Ward nurses per day shift", "number", 3, 1, 6],
      ["alarm_delay", "Alarm delay (s)", "number", 15, 0, 30],
    ],
  };

  // ---- navigation ----
  $("nav").innerHTML = `<li><button data-go="overview"><span class="ic">◎</span>Overview</button></li>`
    + KEYS.map((k) => `<li><button data-go="${k}"><span class="ic">${A[k].icon}</span>${esc(A[k].title)}${A[k].status !== "ready" ? `<span class="tag">${A[k].status === "building" ? "soon" : "later"}</span>` : ""}</button></li>`).join("");

  function stats(k) {
    const s = SUM[k];
    if (!s || !s.stats) return "";
    return `<div class="stats">${s.stats.slice(0, 3).map(([v, l]) => `<div><b class="num">${esc(v)}</b><span>${esc(l)}</span></div>`).join("")}</div>`;
  }
  function renderOverview() {
    $("overview").innerHTML = `<h1>Lahore Twin</h1>
      <p class="lead">Six IoT systems for a city like Lahore, simulated end to end in one place: an office tower, a home on solar during load-shedding, a hospital, the city's traffic, a planner for jammed junctions, and city-wide sensors. Pick a module to open its dashboard, read what it does, or run it with your own values.</p>
      <div class="cards">${KEYS.map((k) => {
        const a = A[k], ready = a.status === "ready";
        return `<article class="card" data-card="${k}">
          <h2><span class="ic">${a.icon}</span>${esc(a.title)}<span class="status ${a.status}">${STATUS[a.status]}</span></h2>
          <p>${esc(a.what)}</p>${stats(k)}
          <div class="row-btns">
            ${ready ? `<button class="btn primary" data-open="${k}">Open</button>` : ""}
            <button class="btn" data-about="${k}">About</button>
            ${ready && RUN[k] ? `<button class="btn" data-run="${k}">Run with your values</button>` : ""}
          </div></article>`;
      }).join("")}</div>`;
  }

  let current = null;
  function go(key, replay) {
    key = A[key] ? key : "overview";
    if (A[key] && A[key].status !== "ready") { about(key); key = current || "overview"; }
    current = key;
    for (const b of document.querySelectorAll("#nav button")) b.setAttribute("aria-current", b.dataset.go === key ? "page" : "false");
    const frame = $("frame");
    if (key === "overview") {
      frame.style.display = "none"; frame.removeAttribute("src"); $("overview").style.display = "";
      document.title = "Lahore Twin";
    } else {
      $("overview").style.display = "none"; frame.style.display = "block";
      const theme = document.documentElement.dataset.theme;
      const want = `${A[key].page}?embed=1&theme=${theme}${replay ? "&replay=" + encodeURIComponent(replay) : ""}`;
      if (frame.getAttribute("src") !== want) frame.setAttribute("src", want);
      document.title = `${A[key].title} · Lahore Twin`;
    }
    const hash = key === "overview" ? "" : "#" + key + (replay ? "?run=" + encodeURIComponent(replay) : "");
    if (location.hash !== hash) history.replaceState(null, "", hash || location.pathname);
  }

  // ---- dialogs ----
  const dlg = $("dlg");
  function show(body, foot) { $("dlg-body").innerHTML = body; $("dlg-foot").innerHTML = foot || `<button class="btn" data-close>Close</button>`; dlg.showModal(); }
  function about(key) {
    if (key === "all") {
      show(`<h2>About Lahore Twin</h2>
        <p>One simulated world for testing IoT automation without owning a single sensor. Every device — badge readers, motion and CO₂ sensors, smart meters, inverters, bedside monitors, fridge probes, traffic signals — lives behind an MQTT-style topic, so a real ESP32 or Zigbee sensor can replace a simulated one without changing the rules.</p>
        <h3>Modules</h3><ul>${KEYS.map((k) => `<li><b>${esc(A[k].title)}</b> — ${STATUS[A[k].status]}. ${esc(A[k].what)}</li>`).join("")}</ul>
        <h3>How to use it</h3><ul>
          <li>Open a module from the sidebar. Press Play or drag the timeline; switch the rule set at the top to compare.</li>
          <li>Click a person, room, bed or device to see its state and why it changed. Use the floor buttons to move between floors.</li>
          <li>The Compare tab puts the rule sets side by side for the whole day.</li>
          <li>"Run with your values" simulates a new day with your inputs (needs the local server: run.bat).</li>
        </ul>`);
      return;
    }
    const foot = (A[key].status === "ready" ? `<button class="btn primary" data-open="${key}">Open</button>` : "") + `<button class="btn" data-close>Close</button>`;
    show(twinAboutHtml(key), foot);
  }
  function runForm(key) {
    const fields = RUN[key];
    const html = `<h2>Run ${esc(A[key].title)} with your values</h2>
      <p class="muted">The simulator runs a full day with these inputs, then the dashboard opens on it. The other rule sets run too, so Compare still works.</p>
      <form class="runform" id="runform">${fields.map(([name, label, type, def, a, b]) => type === "select"
        ? `<label>${esc(label)}<select name="${name}">${a.map((o) => `<option ${o === def ? "selected" : ""}>${o}</option>`).join("")}</select></label>`
        : `<label>${esc(label)}<input type="number" name="${name}" value="${def}" min="${a}" max="${b}" step="1" required></label>`).join("")}</form>
      <div class="runmsg" id="runmsg"></div>`;
    show(html, `<button class="btn primary" id="run-go">Run</button><button class="btn" data-close>Cancel</button>`);
    $("run-go").onclick = async () => {
      const form = $("runform"), msg = $("runmsg");
      if (!form.reportValidity()) return;
      if (location.protocol === "file:") {
        msg.innerHTML = `This needs the local server. Start <b>run.bat</b> and open <b>http://127.0.0.1:8860</b>, then try again.`;
        return;
      }
      const body = Object.fromEntries(new FormData(form).entries());
      const how = { office: "about 20 seconds", hospital: "about a minute", traffic: "about a minute", home: "3–4 minutes: four controllers, each after a warm-up day" };
      msg.textContent = `Simulating… (${how[key] || "a minute or two"})`;
      $("run-go").disabled = true;
      try {
        const r = await fetch(`/api/run/${key}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        const out = await r.json();
        if (!r.ok) throw new Error(out.error || r.statusText);
        dlg.close();
        go(key, out.replay);
      } catch (e) {
        msg.innerHTML = `<span style="color:var(--alert)">Could not run: ${esc(e.message)}</span>`;
        $("run-go").disabled = false;
      }
    };
  }

  // ---- events ----
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-go],[data-open],[data-about],[data-run],[data-close]");
    if (!t) return;
    if (t.dataset.close !== undefined) { dlg.close(); return; }
    if (t.dataset.go) go(t.dataset.go);
    if (t.dataset.open) { if (dlg.open) dlg.close(); go(t.dataset.open); }
    if (t.dataset.about) about(t.dataset.about);
    if (t.dataset.run) runForm(t.dataset.run);
  });
  $("about-all").onclick = () => about("all");
  // module pages ask the shell to open their About (one dialog for the whole app)
  window.addEventListener("message", (e) => { if (e.data && e.data.twin === "about") about(e.data.key); });
  function setTheme(t) {
    document.documentElement.dataset.theme = t; $("theme").textContent = t === "light" ? "Dark" : "Light";
    try { localStorage.setItem("twin-shell-theme", t); } catch (err) { /* ignore */ }
    const f = $("frame");
    if (f.contentWindow && f.style.display !== "none") try { f.contentWindow.postMessage({ twin: "theme", theme: t }, "*"); } catch (err) { /* ignore */ }
  }
  $("theme").onclick = () => setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
  try { const t = localStorage.getItem("twin-shell-theme"); if (t) setTheme(t); } catch (e) { /* ignore */ }
  window.addEventListener("hashchange", () => fromHash());
  function fromHash() {
    const m = location.hash.match(/^#(\w+)(?:\?run=(.*))?$/);
    go(m ? m[1] : "overview", m && m[2] ? decodeURIComponent(m[2]) : null);
  }
  renderOverview();
  fromHash();
  window.__shell = { go, about, runForm, current: () => current };
})();

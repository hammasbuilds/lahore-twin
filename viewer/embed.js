/* Shared by every module page: the About button, running inside the Lahore Twin
 * shell (theme from the shell, no duplicate navigation), and a marker when the
 * page shows a run made with the user's own values. Load after the page script. */
"use strict";

(function () {
  const q = new URLSearchParams(location.search);
  const key = document.body.dataset.module;
  const embedded = window.parent !== window;
  if (q.get("embed")) document.documentElement.classList.add("embed");
  const themeBtn = document.getElementById("theme");
  const want = q.get("theme");
  if (want && themeBtn && document.documentElement.dataset.theme !== want) themeBtn.click();
  window.addEventListener("message", (e) => {
    if (e.data && e.data.twin === "theme" && themeBtn && document.documentElement.dataset.theme !== e.data.theme) themeBtn.click();
  });

  const btn = document.getElementById("about-btn");
  if (btn) btn.onclick = () => {
    if (embedded) { window.parent.postMessage({ twin: "about", key }, "*"); return; }
    let dlg = document.getElementById("about-dlg");
    if (!dlg) {
      dlg = document.createElement("dialog");
      dlg.id = "about-dlg";
      dlg.className = "about-dlg";
      dlg.innerHTML = `<div class="dlg-body">${typeof twinAboutHtml === "function" ? twinAboutHtml(key) : ""}</div>
        <div class="dlg-foot"><a class="btn" href="index.html#${key}" style="text-decoration:none">Open in Lahore Twin</a><button class="btn" data-close>Close</button></div>`;
      dlg.addEventListener("click", (e) => { if (e.target.closest("[data-close]") || e.target === dlg) dlg.close(); });
      document.body.appendChild(dlg);
    }
    dlg.showModal();
  };

  // a run made with the user's values says so, with the inputs it used
  const run = q.get("replay");
  if (run && /^runs\/[\w.-]+\.js$/.test(run)) {
    const pill = document.createElement("span");
    pill.className = "pill ok";
    pill.id = "your-run";
    const R = window.REPLAY || window.HOME || window.HOSPITAL || window.TRAFFIC || window.JUNCTIONS || {};
    const m = R.meta || {};
    const bits = ["seed " + m.seed];
    if (m.pv_kwp != null) bits.push(`${m.pv_kwp} kWp`, `${m.battery_kwh} kWh`, m.category);
    if (m.arrivals_pct != null) bits.push(`${m.arrivals_pct}% arrivals`, `${m.alarm_delay} s alarm delay`);
    if (m.per_hour != null) bits.push(`${m.period ? m.period + " · " : ""}${Number(m.per_hour).toLocaleString("en")} trips/h`);
    if (m.staff != null) bits.push(`${m.staff} staff`);
    if (m.junction && m.junction !== "worst") bits.push(m.junction);
    pill.textContent = "Your run · " + bits.filter(Boolean).join(" · ");
    pill.title = "Simulated with the values you entered";
    const h1 = document.querySelector("header h1");
    if (h1) h1.after(pill);
  }
})();

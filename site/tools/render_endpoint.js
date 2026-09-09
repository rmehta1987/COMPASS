// Render the Metrics panel in its ENDPOINT state, which the committed gate
// cannot reach: site-check renders the static page, where COMPASS_ENDPOINT is
// unset and the keys are never fetched. This drives the other branch with the
// real /api/metrics payload, so a renamed field there fails here rather than in
// a reviewer's browser.
//
// NOT part of site-check, deliberately: it needs a payload only the training
// machine can produce, and site-check must stay runnable on a clone that has
// neither the dictionary nor the scored run. Produce one with the endpoint's
// own route, then:  node site/tools/render_endpoint.js site <payload.json>
//
// It found one real defect on its first run. Question wording went into a
// title="" through `esc`, which escapes &, < and > and leaves the double quote
// alone, so the first wording carrying one would have closed the attribute
// early. The first version of the assertion could not see that -- a broken-out
// value simply ends the title=" match and reads as a shorter title -- so it now
// asserts the exact attribute text, and was confirmed red against `esc` before
// being kept. No wording in the current run carries a quote, so run it against
// a payload with one planted or the check passes vacuously.
"use strict";
const fs = require("fs"), path = require("path");
const site = process.argv[2], payload = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const html = fs.readFileSync(path.join(site, "index.html"), "utf8");
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);

const nodes = {};
function node(id) {
  if (!nodes[id]) nodes[id] = { id, innerHTML: "", value: "", onclick: null, dataset: {}, style: {},
    scrollHeight: 10, getBoundingClientRect: () => ({ width: 10, height: 10 }),
    cloneNode: () => ({ setAttribute() {} }), textContent: "" };
  return nodes[id];
}
const byData = [];
global.document = {
  querySelector: s => node(s),
  querySelectorAll: s => {
    if (s === "style") return [{ textContent: "" }];
    const m = /\[data-(\w+)\]/.exec(s); if (!m) return [];
    const attr = m[1], h = Object.values(nodes).map(n => n.innerHTML).join("");
    const out = [];
    for (const x of h.matchAll(new RegExp(`data-${attr}="([^"]+)"`, "g"))) {
      const b = { dataset: { [attr]: x[1] }, onclick: null }; out.push(b); byData.push(b);
    }
    return out;
  },
  createElement: () => ({ click() {}, set href(v) {}, get href() { return ""; } }),
  createElementNS: () => ({ setAttribute() {}, appendChild() {}, textContent: "" }),
  documentElement: { outerHTML: "<html>" },
  getElementById: () => null,
};
global.window = { devicePixelRatio: 1, COMPASS_ENDPOINT: true };
global.alert = () => {};
// Only /api/metrics is answered; an artefact read still goes to disk.
global.fetch = async (rel) => rel === "/api/metrics"
  ? ({ status: 200, json: async () => payload })
  : ({ json: async () => JSON.parse(fs.readFileSync(path.join(site, rel), "utf8")) });

(async () => {
  for (const s of scripts) new Function(s)();
  await new Promise(r => setTimeout(r, 300));
  let failed = 0;
  document.querySelectorAll("[data-s]");
  const tab = byData.filter(x => x.dataset.s === "metrics" && x.onclick).pop();
  if (!tab) { console.error("no metrics tab handler"); process.exit(1); }
  tab.onclick();

  // the "Show the keys and wording" button, then the enriched table
  document.querySelectorAll("[data-genex]");
  const before = node("#panel").innerHTML;
  if (!before.includes("Show the keys and wording")) {
    console.error("no key request offered on the endpoint"); failed++;
  }
  const btn = node("#met-keys");
  if (!btn.onclick) { console.error("the key button has no handler"); failed++; }
  else { await btn.onclick(); }

  const p = node("#panel").innerHTML;
  for (const bad of ["undefined", "NaN", "[object Object]"]) {
    if (p.includes(bad)) { console.error(`enriched panel contains "${bad}"`); failed++; }
  }
  const anyKey = Object.values(payload.pairs)[0].exposure;
  if (!p.includes(anyKey)) { console.error(`enriched panel is missing ${anyKey}`); failed++; }
  const runs = [...p.matchAll(/data-genex="([^"]+)"/g)].length;
  if (runs !== Object.keys(payload.pairs).length) {
    console.error(`run buttons: ${runs}, expected ${Object.keys(payload.pairs).length}`); failed++;
  }
  // A wording carrying a double quote must not escape its title attribute.
  // Counting title=" runs cannot see that: a broken-out value simply ends the
  // match early and reads as a shorter title. So assert the exact attribute
  // text the page should have produced, for every wording it was handed.
  const esc = t => String(t).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const attExpected = t => esc(t).replace(/"/g, "&quot;");
  let titles = 0;
  for (const v of Object.values(payload.pairs)) {
    for (const w of [v.exposure_wording, v.outcome_wording]) {
      if (!w) continue;
      titles++;
      if (!p.includes(`title="${attExpected(w)}"`)) {
        console.error(`title wrong or broken out: ${JSON.stringify(w.slice(0, 48))}`); failed++;
      }
    }
  }
  // The footer closes by asserting every figure on the page traces to a
  // committed artefact. Standing under a panel this endpoint just produced,
  // that sentence is false, and it is the one a reviewer would quote back. Only
  // this harness can see it: the static render never sets COMPASS_ENDPOINT.
  const f = node("#foot").innerHTML;
  if (!f.includes("<b>not</b> committed")) {
    console.error("footer still claims every figure is committed, under a live panel"); failed++;
  }
  // ...and it must go back to the committed claim on a static stage.
  document.querySelectorAll("[data-s]");
  const stat = byData.filter(x => x.dataset.s === "score" && x.onclick).pop();
  if (!stat) { console.error("no score tab handler"); failed++; }
  else {
    stat.onclick();
    const f2 = node("#foot").innerHTML;
    if (f2.includes("<b>not</b> committed")) {
      console.error("footer still scoped to live figures on a committed panel"); failed++;
    }
    if (!f2.includes("Every figure above is loaded from")) {
      console.error("footer dropped the committed-artefact claim on a static panel"); failed++;
    }
  }

  console.log(failed ? `RED: ${failed} problem(s)`
    : `GREEN: enriched panel renders, ${runs} run button(s), ${titles} wording title(s), footer scoped both ways`);
  process.exit(failed ? 1 : 0);
})();

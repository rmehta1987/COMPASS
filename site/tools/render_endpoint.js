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
    // The WHOLE opening tag, then every data-* on it. Matching only the queried
    // attribute gave each stub a one-key dataset, so a handler reading a second
    // one -- `data-key` beside `data-anchor`, `data-launch` beside `data-genex`
    // -- silently received undefined and the harness proved nothing about it.
    const tagRe = new RegExp(`<[a-zA-Z][^>]*\\bdata-${attr}="[^"]*"[^>]*>`, "g");
    for (const t of h.matchAll(tagRe)) {
      const ds = {};
      for (const d of t[0].matchAll(/data-([a-zA-Z0-9-]+)="([^"]*)"/g)) ds[d[1]] = d[2];
      const b = { dataset: ds, onclick: null }; out.push(b); byData.push(b);
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
// Capture what a download would actually contain.
let lastDownload = null;
global.Blob = class { constructor(parts) { lastDownload = parts.join(""); this.size = lastDownload.length; } };
global.URL = { createObjectURL: () => "blob:x", revokeObjectURL() {} };
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
  // LAUNCHING A RUN FROM A SCORED ARTEFACT must tell Retriever and Intake what
  // was actually run. Before this, the launch set the anchors and started the
  // Specifier while those two stages went on showing whatever was there before
  // -- a committed example, or the previous request's hits -- so the page
  // answered "what was run?" with a different run's numbers.
  //
  // The page is standing on a committed example when the launch happens, which
  // is what makes the clearing below observable.
  node("#q").value = "a query whose retrieval must not survive the launch";
  document.querySelectorAll("[data-s]");
  const retTab = byData.filter(x => x.dataset.s === "retriever" && x.onclick).pop();
  if (retTab) retTab.onclick();

  document.querySelectorAll("[data-genex]");
  const launch = byData.filter(x => x.dataset.genex && x.onclick).pop();
  if (!launch) { console.error("no run button to launch from"); failed++; }
  else {
    if (!launch.dataset.launch) { console.error("the run button carries no launch token"); failed++; }
    const want = { ex: launch.dataset.genex, out: launch.dataset.genout };
    launch.onclick();
    await new Promise(r => setTimeout(r, 50));

    for (const [stage, must] of [["retriever", "NO RETRIEVAL WAS RUN"],
                                 ["intake", "NO QUERY WAS RENDERED"]]) {
      document.querySelectorAll("[data-s]");
      const tab = byData.filter(x => x.dataset.s === stage && x.onclick).pop();
      if (!tab) { console.error(`no ${stage} tab`); failed++; continue; }
      tab.onclick();
      const panel = node("#panel").innerHTML;
      if (!panel.includes(must)) {
        console.error(`${stage} does not say a posed pair was not retrieved`); failed++;
      }
      // ...and it names THIS pair, which is the whole point.
      for (const k of [want.ex, want.out]) {
        if (!panel.includes(k)) { console.error(`${stage} omits ${k}`); failed++; }
      }
      for (const bad of ["undefined", "NaN", "[object Object]"]) {
        if (panel.includes(bad)) { console.error(`${stage} contains "${bad}"`); failed++; }
      }
    }

    // The launch also clears the committed example it was standing on. The
    // panels do not reveal that -- the posed branch wins before the committed
    // one is reached -- so the DOWNLOAD is where the clearing is load-bearing:
    // without it the file mixes a posed run with an unrelated example and takes
    // that example's id for its name.
    const dlp = node("#dl-json");
    if (!dlp || !dlp.onclick) { console.error("no download after a posed launch"); failed++; }
    else {
      dlp.onclick();
      const doc = JSON.parse(lastDownload);
      if (!doc.posed_pair) { console.error("the download omits the posed pair"); failed++; }
      if (doc.example) { console.error("the download carries an unrelated committed example"); failed++; }
    }
  }

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

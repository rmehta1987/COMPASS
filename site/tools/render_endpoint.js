// Drive the page's ENDPOINT branch, which site-check cannot reach: the committed
// gate renders the static page, where COMPASS_ENDPOINT is unset and no route is
// ever called. This drives the live branch instead, so a renamed field there
// fails here rather than in a reviewer's browser.
//
// IT USED TO DRIVE /api/metrics. That route fed the Metrics tab's per-record
// table, which was removed: with keys withheld every row's result column read
// `none` by construction and a row carried a hash and three counts, so it was
// the pipeline's own end-to-end check published as though it were a result.
// The route went with it, and so did the only path by which instrument wording
// reached this page at runtime. What that left stranded was the posed-launch
// regression suite below, whose only source of a [data-genex] button was that
// table. It now launches from the Generate tab's enumerated pairs, which is the
// remaining source, and the payload is synthesised here rather than produced on
// the training machine -- so this runs on any clone:
//
//     node site/tools/render_endpoint.js site
//
// Step 7 of site-check. It needs neither the dictionary nor the scored run now
// that the payload is synthesised here, so it runs on any clone.
//
// One planted value carries a double quote. That is deliberate: an attribute
// written with `esc` rather than `att` closes early on the first such value,
// and a check that counts attribute runs cannot see it -- the broken-out value
// simply ends the match and reads as a shorter attribute. This payload makes
// that check fire instead of passing vacuously.
"use strict";
const fs = require("fs"), path = require("path");
const site = process.argv[2];
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

// Synthetic, and deliberately not instrument content: these are stand-in keys
// with the shape the route returns. QUOTE_KEY is the planted attribute break.
const QUOTE_KEY = 'EXP_Q" onmouseover="x';
const PAIRS = [
  { pair_id: "P_ONE", exposure: "EXP_ONE", outcome: "OUT_ONE",
    exposure_stem: "stem for the first exposure", outcome_stem: "stem for the first outcome" },
  { pair_id: "P_TWO", exposure: QUOTE_KEY, outcome: "OUT_TWO",
    exposure_stem: 'a stem carrying a " double quote', outcome_stem: "stem for the second outcome" },
];
const ENUMERATE = {
  note: "a synthesised enumerate reply, for this harness only",
  shown: PAIRS.length,
  sets: { exposures: PAIRS.length, outcomes: PAIRS.length,
          exposure_module: "MOD_A", exposure_prefix: "PFX_A",
          outcome_module: "MOD_B", outcome_prefix: "PFX_B" },
  counts: { enumerated: PAIRS.length, pruned_S2: 0, live: PAIRS.length,
            estimable: 0, unknown: PAIRS.length, requires_derivation: 0 },
  pairs: PAIRS,
};
global.fetch = async (rel) => rel === "/api/enumerate"
  ? ({ status: 200, json: async () => ENUMERATE })
  : ({ json: async () => JSON.parse(fs.readFileSync(path.join(site, rel), "utf8")) });

(async () => {
  for (const s of scripts) new Function(s)();
  await new Promise(r => setTimeout(r, 300));
  let failed = 0;
  const fail = m => { console.error(m); failed++; };

  // --- the Generate tab's live branch -------------------------------------
  document.querySelectorAll("[data-s]");
  const genTab = byData.filter(x => x.dataset.s === "generate" && x.onclick).pop();
  if (!genTab) { console.error("no generate tab handler"); process.exit(1); }
  genTab.onclick();
  const goGen = node("#go-gen");
  if (!goGen.onclick) fail("the funnel button has no handler on the endpoint");
  else { await goGen.onclick(); await new Promise(r => setTimeout(r, 50)); }

  const g = node("#panel").innerHTML;
  for (const bad of ["undefined", "NaN", "[object Object]"]) {
    if (g.includes(bad)) fail(`the enumerated panel contains "${bad}"`);
  }
  const runs = [...g.matchAll(/data-genex="([^"]+)"/g)].length;
  if (runs !== PAIRS.length) fail(`run buttons: ${runs}, expected ${PAIRS.length}`);

  // A key carrying a double quote must not break out of its attribute. Assert
  // the exact attribute text: counting runs cannot see a broken-out value.
  const want = `data-genex="${QUOTE_KEY.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")}"`;
  if (!g.includes(want)) {
    fail(`a key carrying a double quote escaped its attribute; expected ${JSON.stringify(want)}`);
  }

  // --- the posed launch ----------------------------------------------------
  // A launch poses a pair with no retrieval of its own. Retriever and Intake
  // must say so and must name THIS pair, rather than going on showing whatever
  // was there before -- a committed example, or the previous request's hits --
  // which made the page answer "what was run?" with a different run's numbers.
  // The page is standing on a committed example when the launch happens, which
  // is what makes the clearing below observable.
  node("#q").value = "a query whose retrieval must not survive the launch";
  document.querySelectorAll("[data-s]");
  const retTab = byData.filter(x => x.dataset.s === "retriever" && x.onclick).pop();
  if (retTab) retTab.onclick();

  document.querySelectorAll("[data-genex]");
  // Launch from the PLAIN pair. The planted quote exists for the attribute
  // assertion above; here it would only compare an attribute-encoded value
  // against the same key rendered as element text, which is a difference in
  // this stub's own reading of the DOM, not in the page.
  const launch = byData.filter(x => x.dataset.genex === PAIRS[0].exposure && x.onclick).pop();
  if (!launch) fail("no run button to launch from");
  else {
    if (!launch.dataset.launch) fail("the run button carries no launch token");
    const posed = { ex: launch.dataset.genex, out: launch.dataset.genout };
    launch.onclick();
    await new Promise(r => setTimeout(r, 50));

    for (const [stage, must] of [["retriever", "NO RETRIEVAL WAS RUN"],
                                 ["intake", "NO QUERY WAS RENDERED"]]) {
      document.querySelectorAll("[data-s]");
      const t = byData.filter(x => x.dataset.s === stage && x.onclick).pop();
      if (!t) { fail(`no ${stage} tab`); continue; }
      t.onclick();
      const panel = node("#panel").innerHTML;
      if (!panel.includes(must)) fail(`${stage} does not say a posed pair was not retrieved`);
      for (const k of [posed.ex, posed.out]) {
        if (!panel.includes(k)) fail(`${stage} omits ${k}`);
      }
      for (const bad of ["undefined", "NaN", "[object Object]"]) {
        if (panel.includes(bad)) fail(`${stage} contains "${bad}"`);
      }
    }

    // These chips default to what stages.json says, which describes the shipped
    // pipeline rather than this session. Checking for a literal word went
    // vacuous the moment the vocabulary changed, so assert BOTH that the chip
    // moved off its committed default and what it moved to.
    const railHtml = node("#rail").innerHTML;
    for (const id of ["retriever", "intake"]) {
      const m = new RegExp(`data-s="${id}"[\\s\\S]*?<span class="st[^"]*">([^<]*)</span>`).exec(railHtml);
      const txt = m ? m[1].trim() : "";
      if (/example|past run|committed run|not yet run/i.test(txt)) {
        fail(`${id} chip still shows its committed default: ${JSON.stringify(txt)}`);
      }
      if (!/nothing to show/i.test(txt)) {
        fail(`${id} chip does not report it has no output for the posed pair: ${JSON.stringify(txt)}`);
      }
    }

    // The launch also clears the committed example it was standing on. The
    // panels do not reveal that -- the posed branch wins before the committed
    // one is reached -- so the DOWNLOAD is where the clearing is load-bearing:
    // without it the file mixes a posed run with an unrelated example and takes
    // that example's id for its name.
    const dlp = node("#dl-json");
    if (!dlp || !dlp.onclick) fail("no download after a posed launch");
    else {
      dlp.onclick();
      const doc = JSON.parse(lastDownload);
      if (!doc.posed_pair) fail("the download omits the posed pair");
      if (doc.example) fail("the download carries an unrelated committed example");
    }
  }

  // --- the Metrics tab's structure ----------------------------------------
  document.querySelectorAll("[data-s]");
  const metTab = byData.filter(x => x.dataset.s === "metrics" && x.onclick).pop();
  if (!metTab) { console.error("no metrics tab handler"); process.exit(1); }
  metTab.onclick();
  const p = node("#panel").innerHTML;
  for (const bad of ["undefined", "NaN", "[object Object]"]) {
    if (p.includes(bad)) fail(`the metrics panel contains "${bad}"`);
  }

  // The per-record listing must NOT come back: it is the pipeline's own check,
  // and every row's result column was fixed by construction.
  if (/<th>record<\/th>/.test(p)) fail("the per-record table is published again");
  if (/data-genex=/.test(p)) fail("the Metrics tab offers a per-record launch again");
  if (/Show the keys and wording/.test(p)) fail("the Metrics tab asks the server for instrument wording again");

  // The two lists are independent, and the panel has to say so structurally, not
  // just in prose: back to back, the second table reads as more of the first.
  const heads = [...p.matchAll(/<p class="sec major">([\s\S]*?)<\/p>/g)].map(m =>
    m[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim());
  const wanted = [/Cohort bibliography/, /What the run produced/, /What is shipped/];
  for (const w of wanted) {
    if (!heads.some(t => w.test(t))) fail(`no major section matching ${w}`);
  }
  if (heads.length !== wanted.length) {
    fail(`expected ${wanted.length} major sections, found ${heads.length}: ${JSON.stringify(heads)}`);
  }
  // Each block must sit INSIDE the section it describes. Asserted by position,
  // because a block that drifts back above the headings still renders fine and
  // still says all the right words -- it just answers under the wrong list.
  const at = t => p.indexOf(t);
  const producedAt = at("What the run produced"), biblioAt = at("Cohort bibliography");
  for (const [block, section, start] of [
      ['<p class="sec">observed</p>', "What the run produced", producedAt],
      ['<p class="sec">how to read that</p>', "What the run produced", producedAt],
      ['<p class="sec">verdicts on this scoring run</p>', "Cohort bibliography", biblioAt]]) {
    const i = at(block);
    if (i < 0) { fail(`missing block ${block}`); continue; }
    const nextMajor = p.indexOf('class="sec major"', start + 1);
    const end = nextMajor < 0 ? p.length : nextMajor;
    if (i < start || i > end) fail(`${block} is not inside the "${section}" section`);
  }

  // ...and the pipeline's own output is no longer labelled "artifacts" to the reader.
  if (/the scored artifacts/.test(p)) fail('the pipeline output is still headed "the scored artifacts"');

  // The disqualifying fact must be in the open, not behind a click: when every
  // record carries it, the `shared` hoist used to remove the column BECAUSE it
  // was uniform, and a fold then hid the sentence that replaced it -- so the
  // uniform worst case was the one case the reader could not see.
  // Pin the SENTENCE, not the mark. The mark also reaches this panel through
  // other prose, so searching for it alone stayed green with the sentence
  // deleted -- confirmed by seeding exactly that.
  const estSent = /Every scored record carries estimability <span class="flag">([^<]+)<\/span>/.exec(p);
  if (!estSent) fail("the metrics panel does not state that every scored record carries the estimability mark");
  else {
    const est = estSent.index;
    const fold = p.lastIndexOf("<details", est);
    const close = fold < 0 ? -1 : p.indexOf("</details>", fold);
    if (fold >= 0 && close > est) fail("the estimability mark is inside a fold");
  }

  // Retrieval's shipped summary closes the Metrics tab and must not leak.
  if (!p.includes("Retrieval is in use")) fail("the Metrics tab does not carry the shipped summary");
  document.querySelectorAll("[data-s]");
  const stat = byData.filter(x => x.dataset.s === "score" && x.onclick).pop();
  if (!stat) fail("no score tab handler");
  else {
    stat.onclick();
    // The footer says where the figures come from under EVERY panel but Metrics,
    // which carries its own provenance line in the body. This assertion used to
    // require the footer be empty here -- the behaviour before `foot` was fixed
    // for having been scoped to live panels only, which `render.js::checkFoot`
    // now pins the other way. It was stale, and nothing ran it to notice.
    const f2 = node("#foot").innerHTML.trim();
    if (!/site\/artifacts/.test(f2)) {
      fail(`footer does not say where a static panel's figures come from, got ${JSON.stringify(f2.slice(0, 70))}`);
    }
    if (node("#panel").innerHTML.includes("Retrieval is in use")) {
      fail("the shipped summary leaked onto a non-Metrics panel");
    }
  }

  console.log(failed ? `RED: ${failed} problem(s)`
    : `GREEN: enumerate renders, ${runs} run button(s), posed launch clears and names its pair, metrics publishes no per-record listing`);
  process.exit(failed ? 1 : 0);
})();

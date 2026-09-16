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
// A pair reply whose anchors are RESOLVED, so `adoptProposals` adopts them.
// Synthetic keys and wording, like PAIRS above: no instrument content here.
const PAIR_REPLY = {
  request: "ASKED_TEXT",
  model_id: "harness",
  anchors_proposed_by: "harness",
  not_a_selection: "candidates only",
  // ONE ADOPTED ROLE AND ONE DECLINED, which is the shape a real request
  // produces. MEASURED on "does marijuana cause prostate cancer": the outcome
  // resolved and the exposure came back `ambiguous` naming six
  // operationalisations, with the exposure block in the pool at rank seven. A
  // reply with both roles resolved tested only the happy path, and the panel
  // was silently dropping the declined one.
  roles: {
    exposure: { verdict: "ambiguous", reason: "several operationalisations",
                missing_dimension: "WHICH_OPERATIONALIZATION",
                proposed_indices: [],
                candidates: [{ index: 1, key: "EXP_ASKED", wording: "WORDING_EXP",
                               proposed: false, cos: 0.5 }] },
    outcome: { verdict: "resolved", reason: "because", proposed_indices: [1],
               candidates: [{ index: 1, key: "OUT_ASKED", wording: "WORDING_OUT",
                              proposed: true, cos: 0.5 }] },
  },
};
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
// The stub took only the URL, so nothing could assert what a button POSTED --
// a handler that sent the outcome as the exposure would have passed. It now
// records the last POST body. `/api/specify` answers WITHOUT a ticket on
// purpose: `runSpecifier` stores a ticketless reply and renders it, so the
// assertion runs with no poll loop to wait out.
let lastPost = null;
const posts = [];
global.fetch = async (rel, opts) => {
  if (opts && opts.method === "POST") {
    lastPost = { rel, body: JSON.parse(opts.body) };
    posts.push(lastPost);
  }
  if (rel === "/api/enumerate") return { status: 200, json: async () => ENUMERATE };
  if (rel === "/api/specify") {
    return { status: 403, json: async () => ({ error: "refused by this harness" }) };
  }
  // A TICKET, because that is what the route returns. The first version of this
  // stub answered without one, which took `askResolver`'s ticketless branch --
  // an error shape -- so `adoptProposals` never ran and the harness was testing
  // a path the endpoint does not produce.
  if (rel === "/api/pair") {
    return { status: 200, json: async () => ({ ticket: "TCK", status: "running",
                                               poll_after_ms: 1 }) };
  }
  if (rel === "/api/specify/status") {
    return { status: 200,
             json: async () => Object.assign({ status: "done" }, PAIR_REPLY) };
  }
  return { json: async () => JSON.parse(fs.readFileSync(path.join(site, rel), "utf8")) };
};

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

  // --- the Specifier tab's empty state ----------------------------------
  // It was a dashed placeholder with no way to act, on the stage a reader
  // most wants to trigger. Two things are asserted, and the second is the
  // one a wrong handler would fail: the form is THERE, and the button sends
  // what was typed in the RIGHT ROLES. The prose path takes direction from
  // position, so a form that swapped them would look identical on screen.
  document.querySelectorAll("[data-s]");
  const specTab = byData.filter(x => x.dataset.s === "ask" && x.onclick).pop();
  if (!specTab) fail("no ask tab handler");
  else {
    specTab.onclick();
    const sp = node("#panel").innerHTML;
    // In the HTML, not through `node()`: this stub CACHES a node once wired,
    // so a control deleted from the panel keeps its handler and an assertion
    // on `node("#x").onclick` passes for a form that is no longer rendered.
    // Removing `askForm` from the panel went green exactly that way.
    for (const id of ["spec-q", "spec-ask", "spec-ex", "spec-out", "spec-go"]) {
      if (!sp.includes(`id="${id}"`)) fail(`the Ask tab offers no ${id}`);
    }
    for (const bad of ["undefined", "NaN", "[object Object]"]) {
      if (sp.includes(bad)) fail(`the specifier start form contains "${bad}"`);
    }
    // ASKING MUST FILL THE KEY FIELDS. That is the whole point of the panel: a
    // reader without the codebook cannot type a key, so the question is the
    // entry and the fields are filled from what comes back -- with the wording,
    // because confirming an unreadable key is not confirming.
    const ab = node("#spec-ask");
    if (!ab || !ab.onclick) fail("the specifier tab has no propose handler");
    else {
      node("#spec-q").value = "ASKED_TEXT";
      posts.length = 0;
      await ab.onclick();
      await new Promise(r => setTimeout(r, 120));
      const asked = posts.find(x => x.rel === "/api/pair");
      if (!asked) fail("proposing did not post to /api/pair");
      else if (asked.body.request !== "ASKED_TEXT") {
        fail(`proposing sent ${JSON.stringify(asked.body.request)}`);
      }
      // Asserted on the RENDERED HTML, not on a node's `.value`: this DOM stub
      // fabricates nodes on demand and never parses an assigned innerHTML, so a
      // node's `.value` is whatever the stub initialised and would pass or fail
      // for reasons that have nothing to do with the page.
      const filled = node("#panel").innerHTML;
      // Once a proposal exists the key form is REPLACED by it -- two Run
      // buttons and two sets of fields would leave the reader guessing which
      // one runs -- so the adopted anchor appears in the proposal's chosen-pair
      // block as text, not as an input value. Asserted where it actually is.
      for (const want of ["OUT_ASKED", "WORDING_OUT"]) {
        if (!filled.includes(want)) {
          fail(`asking did not put ${want} in front of the reader`);
        }
      }
      // THE DECLINED ROLE MUST NOT READ AS CHOSEN. `adoptProposals` carries
      // over only `resolved` and `pinned`, so the chosen pair has to say the
      // exposure was not picked -- while still showing why, what would settle
      // it, and a `use` button so the reader can settle it themselves.
      if (!/<dt>exposure<\/dt><dd[^>]*><em>none picked<\/em>/.test(filled)) {
        fail("a declined role reads as the chosen exposure");
      }
      if (!filled.includes("WHICH_OPERATIONALIZATION")) {
        fail("the panel hides what would settle a declined role");
      }
      if (!filled.includes("WORDING_EXP")) {
        fail("the panel offers no candidate wording for a declined role");
      }
      if (!/data-anchor="exposure"[^>]*data-key="EXP_ASKED"/.test(filled)) {
        fail("the panel offers no way to pick a candidate for a declined role");
      }
    }

    const go = node("#spec-go");
    if (!go.onclick) fail("the specifier start button has no handler");
    else {
      node("#spec-ex").value = PAIRS[0].exposure;
      node("#spec-out").value = PAIRS[0].outcome;
      lastPost = null;
      go.onclick();
      await new Promise(r => setTimeout(r, 50));
      if (!lastPost) fail("the specifier start button posted nothing");
      else {
        if (lastPost.rel !== "/api/specify") {
          fail(`the start button posted to ${lastPost.rel}, not /api/specify`);
        }
        if (lastPost.body.exposure !== PAIRS[0].exposure) {
          fail(`exposure posted as ${JSON.stringify(lastPost.body.exposure)}`);
        }
        if (lastPost.body.outcome !== PAIRS[0].outcome) {
          fail(`outcome posted as ${JSON.stringify(lastPost.body.outcome)}`);
        }
      }
    }
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
  const retTab = byData.filter(x => x.dataset.s === "ask" && x.onclick).pop();
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

    for (const [stage, must] of [["ask", "NO RETRIEVAL WAS RUN"],
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
    for (const id of ["ask", "intake"]) {
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
  const wanted = [/Cohort bibliography/, /What is shipped/];
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
  const biblioAt = at("Cohort bibliography");
  for (const [block, section, start] of [
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
  // The pipeline's own output is not reported here at all. These four are the
  // shapes it came back in before: a per-record table, a launch column, a key
  // request, and the counts-and-caveats section left after the table went.
  // Each was removed for reading as evidence, so each is pinned out.
  for (const [re, what] of [
      [/<p class="sec">observed<\/p>/, "the run's own counts"],
      [/<p class="sec">how to read that<\/p>/, "the run's own how-to-read list"],
      [/What the run produced/, "the run's own output section"],
      [/ledger denominator|ledger disposition/, "the ledger's dispositions"]]) {
    if (re.test(p)) fail(`the metrics panel reports ${what} again`);
  }
  // The RESULT is not the pipeline's output and must stay: it is the ceiling
  // and the score against it, which is what the tab is for.
  if (!/records that could have matched/.test(p)) fail("the metrics panel no longer states the ceiling");

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

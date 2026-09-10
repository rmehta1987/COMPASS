// Drive a slow endpoint run and navigate away mid-run, which neither committed
// gate can do: site-check renders a page with COMPASS_ENDPOINT unset, and
// render_endpoint.js drives one request to completion without touching the rail.
//
// The guarantee under test is `steer()`: a stage change decided AFTER an await
// must be forfeited if the reader has picked a stage in the meantime. Panels
// still fill -- the query has not changed and the answer was asked for -- but
// the reader is not dragged off what they are reading. Before this, a Specifier
// run that finished minutes later ended in `finally` with an unconditional
// `sel="record"`.
//
// Step 8 of site-check. It asserts endpoint BEHAVIOUR but stubs the endpoint
// itself, so it needs no server and runs on any clone -- the two were conflated
// while it sat outside the gate, and a rail-vocabulary change went unnoticed.
// Usage: node render_race.js <site dir>
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

// The run is held open until the harness releases it, so "the reader navigates
// mid-run" is a fact of the script rather than a race the test hopes to win.
let release = null;
const held = new Promise(r => { release = r; });
const POLL = 1;              // ms; the page reads this from the reply, never its own
// Opaque placeholders, NOT key-shaped: tier A forbids a variable key anywhere
// under site/, and site-check greps this file like any other. The page treats an
// anchor key as an opaque string, so nothing here needs a real one.
const KEY = { exposure: "EXPOSURE-ANCHOR-STUB", outcome: "OUTCOME-ANCHOR-STUB" };
let specifyStarted = false;

global.fetch = async (rel, opt) => {
  const body = opt && opt.body ? JSON.parse(opt.body) : {};
  if (rel === "/api/pair") return { status: 200, json: async () => ({ ticket: "pair", poll_after_ms: POLL }) };
  if (rel === "/api/specify") { specifyStarted = true; return { status: 200, json: async () => ({ ticket: "spec", poll_after_ms: POLL }) }; }
  if (rel === "/api/specify/status") {
    if (body.ticket === "pair") {
      return { status: 200, json: async () => ({ status: "done", roles: {
        exposure: { verdict: "pinned", pinned_key: KEY.exposure },
        outcome:  { verdict: "pinned", pinned_key: KEY.outcome } } }) };
    }
    await held;                      // the Specifier run, held open
    return { status: 200, json: async () => ({ status: "done",
      selected: { estimability: "estimable", exposure: { key: KEY.exposure }, outcome: { key: KEY.outcome },
                  blocked_on: [], sought_covariates: [] }, tool_log: [] }) };
  }
  return { json: async () => JSON.parse(fs.readFileSync(path.join(site, rel), "utf8")) };
};

const stageOf = () => { const m = /<h2>([^<]*)<\/h2>/.exec(node("#panel").innerHTML); return m ? m[1] : null; };
const tick = (n) => new Promise(r => setTimeout(r, n));
const fire = (attr, val) => {
  document.querySelectorAll(`[data-${attr}]`);
  const b = byData.filter(x => x.dataset[attr] === val && x.onclick).pop();
  if (!b) throw new Error(`no handler for data-${attr}=${val}`);
  b.onclick(); return b;
};

(async () => {
  for (const s of scripts) new Function(s)();
  await tick(300);
  let failed = 0;
  const fail = m => { console.error(m); failed++; };

  const stages = [...node("#rail").innerHTML.matchAll(/data-s="([^"]+)"/g)].map(m => m[1]);
  const away = stages.find(s => s === "score") || stages[stages.length - 1];
  const nameOf = {};
  for (const m of node("#rail").innerHTML.matchAll(/data-s="([^"]+)"[\s\S]*?<\/span>([^<]*)<span/g)) nameOf[m[1]] = m[2].trim();

  node("#q").value = "a request that starts a slow run";
  node("#ask").onclick();                       // resolver -> auto-chains to the Specifier
  await tick(60);
  if (!specifyStarted) { fail("the Specifier run never started; the harness drove nothing"); }

  const during = stageOf();
  fire("s", away);                              // the reader navigates mid-run
  const chosen = stageOf();
  if (chosen === during) fail(`navigating mid-run did not change the panel (still ${chosen})`);

  release();                                    // the run lands, minutes later
  await tick(80);

  const after = stageOf();
  if (after !== chosen) {
    fail(`the completing run dragged the reader from ${JSON.stringify(chosen)} to ${JSON.stringify(after)}`);
  }
  // ...and the answer was kept, not thrown away: the record stage now has one.
  // Assert the run's own anchor is present, not merely that the empty-panel
  // marker is absent: "no PLACEHOLDER" also holds for a panel showing some other
  // run, and it reads as passing when the stub string happens to contain the word.
  fire("s", "record");
  const rec = node("#panel").innerHTML;
  if (!rec.includes(KEY.exposure)) fail("the run's own record was discarded, not merely un-steered");

  // The download must carry the run the reader just watched. It used to be
  // `{stage, example: cur, provenance}` unconditionally, and after a live run
  // `cur` is null -- so the file said `"example": null` and held none of it.
  // The rail is baked from stages.json and used to be built once, at load, so a
  // finished run sat under a chip still reading "blocked, no run yet" and the
  // rail never marked the stage being read.
  const railHtml = node("#rail").innerHTML;
  const chip = id => {
    const m = new RegExp(`data-s="${id}"[\\s\\S]*?<span class="st[^"]*">([^<]*)</span>`).exec(railHtml);
    return m ? m[1].trim() : null;
  };
  if (/no run yet/.test(chip("specifier") || "")) {
    fail(`the specifier chip still reads ${JSON.stringify(chip("specifier"))} after a finished run`);
  }
  // Vocabulary changed in the chip rewrite: a finished Specifier run says "ran".
  if (!/\bran\b|complete|record|refused/i.test(chip("specifier") || "")) {
    fail(`the specifier chip does not report the finished run: ${JSON.stringify(chip("specifier"))}`);
  }
  const marked = [...railHtml.matchAll(/data-s="([^"]+)" aria-current="true"/g)].map(m => m[1]);
  if (marked.length !== 1 || marked[0] !== "record") {
    fail(`the rail marks ${JSON.stringify(marked)}; the reader is on "record"`);
  }

  // The footer lost its three-paragraph summary to the Metrics tab and kept one
  // job: saying that the figures directly above came from this session and are
  // not committed. The reader is on `record`, a live panel, so it must be there.
  const foot = node("#foot").innerHTML;
  if (!/<b>not<\/b> committed/.test(foot)) {
    fail(`the footer does not mark a live panel's figures as uncommitted: ${JSON.stringify(foot.slice(0, 80))}`);
  }
  if (/Retrieval is (?:shipped|in use)/.test(foot)) {
    fail("the shipped summary is still in the footer; it belongs to the Metrics tab");
  }

  const dl = node("#dl-json");
  if (!dl || !dl.onclick) fail("no download offered after a completed run");
  else {
    dl.onclick();
    const doc = JSON.parse(lastDownload);
    if (!doc.specifier_run) fail("the download omits the run that just finished");
    if ("example" in doc && doc.example === null) fail('the download carries a null "example"');
  }

  console.log(failed ? `RED: ${failed} problem(s)`
    : `GREEN: navigated to ${JSON.stringify(chosen)} mid-run, stayed there, record kept, download carries the run`);
  process.exit(failed ? 1 : 0);
})();

// Drive the page's "compare with the paper" section, which only a served page
// with --enable-compare shows, so no static check can reach it:
//
//     node site/tools/render_compare.js site
//
// What it pins, each named for the defect its red state reports:
//   * the request names the record by TICKET and sends no record body, because
//     a caller that could send a record could send one built to probe the key;
//   * each field renders as a sentence, never as a bare MATCH/DIFFERS chip,
//     because a row of chips reads as a grade;
//   * the JSON download does not carry the comparison, because a MATCH
//     discloses the paper's key and a downloaded file travels;
//   * a refusal says there is nothing to compare, and offers no button;
//   * with the route off, the section is absent rather than dead.
//
// The payloads are synthesised here. No key, wording or design is in them.
"use strict";
const fs = require("fs"), path = require("path");
const site = process.argv[2];
const html = fs.readFileSync(path.join(site, "index.html"), "utf8");
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);

let failed = 0;
const fail = m => { console.error(m); failed++; };

const RECORD = { protocol_id: "P_HARNESS", question: "a posed question",
                 exposure: { key: "EXP_KEY" }, outcome: { key: "OUT_KEY" },
                 falsifier: "a falsifier", status: "specified" };
const COMPARE = {
  compare: { pmid: "PMID_FROM_THE_PAGE", design_key_readable: true, same_build: false,
             record_dictionary_version: "BUILD_A", dictionary_version: "BUILD_B",
             complaint_count: 0,
             fields: [{ field: "exposure_keys", state: "MATCH", why: "" },
                      { field: "outcome_keys", state: "DIFFERS", why: "" },
                      { field: "model_form", state: "REVIEW", why: "vocabularies" },
                      { field: "adjusted_covariate_keys", state: "UNAVAILABLE",
                        why: "no covariate column" }] },
  comparisons_this_session: 1,
  not_a_score: "NOT_A_SCORE_SENTENCE",
};

async function run({ enable, refusal }) {
  const nodes = {};
  const node = id => {
    if (!nodes[id]) nodes[id] = { id, innerHTML: "", value: "", onclick: null, dataset: {},
      style: {}, scrollHeight: 10, getBoundingClientRect: () => ({ width: 10, height: 10 }),
      cloneNode: () => ({ setAttribute() {} }), textContent: "" };
    return nodes[id];
  };
  const byData = [];
  global.document = {
    querySelector: s => node(s),
    querySelectorAll: s => {
      if (s === "style") return [{ textContent: "" }];
      const m = /\[data-(\w+)\]/.exec(s); if (!m) return [];
      const h = Object.values(nodes).map(n => n.innerHTML).join("");
      const out = [];
      for (const t of h.matchAll(new RegExp(`<[a-zA-Z][^>]*\\bdata-${m[1]}="[^"]*"[^>]*>`, "g"))) {
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
  global.window = { devicePixelRatio: 1, COMPASS_ENDPOINT: true, COMPASS_COMPARE: enable };
  global.alert = () => {};
  let download = null;
  global.Blob = class { constructor(parts) { download = parts.join(""); this.size = download.length; } };
  global.URL = { createObjectURL: () => "blob:x", revokeObjectURL() {} };
  const posts = [];
  global.fetch = async (rel, opts) => {
    if (opts && opts.method === "POST") posts.push({ rel, body: JSON.parse(opts.body) });
    if (rel === "/api/specify") {
      return { status: 200, json: async () => ({ ticket: "TICKET_ONE", poll_after_ms: 1 }) };
    }
    if (rel === "/api/specify/status") {
      const done = refusal
        ? { status: "done", selected: null, refusal: { pair_id: "P_HARNESS", reason: "r",
            statement: "s", what_would_unblock: "w" } }
        : { status: "done", selected: RECORD, yield: "one record",
            // The identity the route always sends; a sparser one renders
            // "undefined" in the run block, which is this fixture's fault.
            identity: { protocol_id: "P_HARNESS", model_id: "harness",
                        is_pipeline_model: true, selection_mode: "externally_posed",
                        screened_from: 0 } };
      return { status: 200, json: async () => done };
    }
    if (rel === "/api/compare") return { status: 200, json: async () => COMPARE };
    return { json: async () => JSON.parse(fs.readFileSync(path.join(site, rel), "utf8")) };
  };

  for (const s of scripts) new Function(s)();
  await new Promise(r => setTimeout(r, 300));
  document.querySelectorAll("[data-s]");
  const ask = byData.filter(x => x.dataset.s === "ask" && x.onclick).pop();
  if (!ask) { fail("no ask tab handler"); return; }
  ask.onclick();
  node("#spec-ex").value = "EXP_KEY";
  node("#spec-out").value = "OUT_KEY";
  if (!node("#spec-go").onclick) { fail("no specifier start button"); return; }
  node("#spec-go").onclick();
  await new Promise(r => setTimeout(r, 150));
  const p = node("#panel").innerHTML;

  if (!enable) {
    if (/compare with the paper/.test(p)) fail("the section shows with the route off: a dead control");
    return;
  }
  if (!/compare with the paper/.test(p)) { fail("no comparison section under the record"); return; }
  if (refusal) {
    if (!/refused this pair, so there is nothing to place beside the paper/.test(p)) {
      fail("a refusal does not say there is nothing to compare");
    }
    if (p.includes('id="cmp-go"')) fail("a refusal offers a Compare button");
    return;
  }
  if (!p.includes('id="cmp-pmid"') || !p.includes('id="cmp-go"')) {
    fail("the comparison section has no paper picker or no button"); return;
  }
  const first = /<option value="([^"]+)"/.exec(p);
  if (!first) { fail("the paper picker offers no papers"); return; }
  node("#cmp-pmid").value = first[1];
  if (!node("#cmp-go").onclick) { fail("the Compare button has no handler"); return; }
  await node("#cmp-go").onclick();
  await new Promise(r => setTimeout(r, 50));

  const sent = posts.find(x => x.rel === "/api/compare");
  if (!sent) { fail("Compare posted nothing"); return; }
  if (sent.body.ticket !== "TICKET_ONE") fail(`compare named the record as ${JSON.stringify(sent.body.ticket)}`);
  if (sent.body.pmid !== first[1]) fail(`compare sent pmid ${JSON.stringify(sent.body.pmid)}`);
  const extra = Object.keys(sent.body).filter(k => k !== "ticket" && k !== "pmid");
  if (extra.length) fail(`compare sent more than a ticket and a pmid: ${extra}`);

  const q = node("#panel").innerHTML;
  for (const want of ["uses the variable the paper recorded", "uses a different variable",
                      "needs a reader", "not compared: no covariate column",
                      "NOT_A_SCORE_SENTENCE", "two builds disagreeing",
                      "says nothing about the covariates"]) {
    if (!q.includes(want)) fail(`the comparison does not say: ${want}`);
  }
  const shown = q.replace(/<[^>]+>/g, " ");
  for (const chip of ["MATCH", "DIFFERS", "UNAVAILABLE"]) {
    if (new RegExp(`\\b${chip}\\b`).test(shown)) fail(`a bare ${chip} reaches the reader`);
  }
  for (const bad of ["undefined", "NaN", "[object Object]"]) {
    if (q.includes(bad)) fail(`the comparison renders "${bad}": ...${q.slice(Math.max(0, q.indexOf(bad) - 160), q.indexOf(bad) + 40)}`);
  }
  const dl = node("#dl-json");
  if (!dl.onclick) { fail("no download after a run"); return; }
  dl.onclick();
  if (!download) { fail("the download wrote nothing"); return; }
  if (/NOT_A_SCORE_SENTENCE|comparisons_this_session|"compare"/.test(download)) {
    fail("the JSON download carries the comparison, which discloses the key");
  }
}

(async () => {
  await run({ enable: true, refusal: false });
  await run({ enable: true, refusal: true });
  await run({ enable: false, refusal: false });
  console.log(failed ? `RED: ${failed} problem(s)`
    : "GREEN: compare names the record by ticket, speaks in sentences, stays out of the download, and hides on refusal or when off");
  process.exit(failed ? 1 : 0);
})();

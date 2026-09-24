// Drive the page's "compare with the paper" section, which only a served page
// with --enable-compare shows, so no static check can reach it:
//
//     node site/tools/render_compare.js site
//
// What it pins, each named for the defect its red state reports:
//   * the request names the record by TICKET and sends no record body, because
//     a caller that could send a record could send one built to probe the key;
//   * each field renders as a sentence the reader can act on, never as a bare
//     MATCH/DIFFERS chip and never as the scoring clone's own `why` note;
//   * neither the JSON download nor the PNG carries the comparison, because a
//     MATCH discloses the paper's key and both files travel;
//   * a new run clears the previous record's comparison, and an answer that
//     lands after a newer run started is dropped;
//   * a refusal says there is nothing to compare and offers no button; an
//     empty bibliography says so rather than posting an empty pmid;
//   * with the route off, the section is absent rather than dead.
//
// The payloads are synthesised here. No key, wording or design is in them.
"use strict";
const fs = require("fs"), path = require("path");
const site = process.argv[2];
const html = fs.readFileSync(path.join(site, "index.html"), "utf8");
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);

let failed = 0;
const fail = (scenario, m) => { console.error(`[${scenario}] ${m}`); failed++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));

const RECORD = { protocol_id: "P_HARNESS", question: "a posed question",
                 exposure: { key: "EXP_KEY" }, outcome: { key: "OUT_KEY" },
                 falsifier: "a falsifier", status: "specified" };
const WHY_NOTE = "DEVELOPER_NOTE_FROM_THE_SCORING_CLONE";
const COMPARE = {
  compare: { pmid: "PMID_FROM_THE_PAGE", design_key_readable: true, same_build: false,
             record_dictionary_version: "BUILD_A", dictionary_version: "BUILD_B",
             complaint_count: 0,
             fields: [{ field: "exposure_keys", state: "MATCH", why: "" },
                      { field: "outcome_keys", state: "DIFFERS", why: "" },
                      { field: "model_form", state: "REVIEW", why: WHY_NOTE },
                      { field: "adjusted_covariate_keys", state: "UNAVAILABLE",
                        why: WHY_NOTE },
                      // A field this page has no sentence for, so the generic
                      // branch is exercised and must still not quote `why`.
                      { field: "a_field_added_later", state: "UNAVAILABLE",
                        why: WHY_NOTE }] },
  comparisons_this_session: 1,
  not_a_score: "NOT_A_SCORE_SENTENCE",
};
const SENTENCES = ["uses the variable the paper recorded", "uses a different variable",
                   "Search only can show", "Metrics tab's bibliography",
                   "does not record the paper's covariates", "NOT_A_SCORE_SENTENCE",
                   "two builds disagreeing", "says nothing about the covariates",
                   "This server has made"];

async function page(o) {
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
  global.window = { devicePixelRatio: 1, COMPASS_ENDPOINT: true, COMPASS_COMPARE: o.enable };
  global.alert = () => {};
  global.Image = class { set src(v) {} };
  global.XMLSerializer = class { serializeToString() { return "<svg/>"; } };
  const st = { download: null, posts: [], tickets: 0 };
  global.Blob = class { constructor(parts) { st.download = parts.join(""); this.size = st.download.length; } };
  global.URL = { createObjectURL: () => "blob:x", revokeObjectURL() {} };
  global.fetch = async (rel, opts) => {
    if (opts && opts.method === "POST") st.posts.push({ rel, body: JSON.parse(opts.body) });
    if (rel === "/api/specify") {
      st.tickets += 1;
      const t = `TICKET_${st.tickets}`;
      return { status: 200, json: async () => ({ ticket: t, poll_after_ms: 1 }) };
    }
    if (rel === "/api/specify/status") {
      const done = o.refusal
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
    if (rel === "/api/compare") {
      if (o.compareDelayMs) await sleep(o.compareDelayMs);
      return { status: 200, json: async () => COMPARE };
    }
    const doc = JSON.parse(fs.readFileSync(path.join(site, rel), "utf8"));
    if (o.noPapers && rel.endsWith("metrics.json")) doc.papers = [];
    return { json: async () => doc };
  };

  for (const s of scripts) new Function(s)();
  await sleep(300);
  document.querySelectorAll("[data-s]");
  const ask = byData.filter(x => x.dataset.s === "ask" && x.onclick).pop();
  const specRun = async () => {
    node("#spec-ex").value = "EXP_KEY";
    node("#spec-out").value = "OUT_KEY";
    node("#spec-go").onclick();
    await sleep(150);
  };
  return { node, st, ask, specRun, panel: () => node("#panel").innerHTML };
}

async function comparedPage(o) {
  const p = await page(o);
  if (!p.ask) return null;
  p.ask.onclick();
  await p.specRun();
  const first = /<option value="([^"]+)"/.exec(p.panel());
  if (!first || !p.node("#cmp-go").onclick) return null;
  p.node("#cmp-pmid").value = first[1];
  p.pmid = first[1];
  return p;
}

(async () => {
  // 1. the full flow
  {
    const S = "flow";
    const p = await comparedPage({ enable: true });
    if (!p) fail(S, "no comparison section, paper picker or Compare button under the record");
    else {
      if (!/PMID/.test(p.panel()) || !/<option[^>]*>[^<]*·/.test(p.panel())) {
        fail(S, "the paper picker does not describe each paper");
      }
      await p.node("#cmp-go").onclick();
      await sleep(50);
      const sent = p.st.posts.find(x => x.rel === "/api/compare");
      if (!sent) fail(S, "Compare posted nothing");
      else {
        if (sent.body.ticket !== "TICKET_1") fail(S, `compare named the record as ${JSON.stringify(sent.body.ticket)}`);
        if (sent.body.pmid !== p.pmid) fail(S, `compare sent pmid ${JSON.stringify(sent.body.pmid)}`);
        const extra = Object.keys(sent.body).filter(k => k !== "ticket" && k !== "pmid");
        if (extra.length) fail(S, `compare sent more than a ticket and a pmid: ${extra}`);
      }
      const q = p.panel();
      for (const want of SENTENCES) if (!q.includes(want)) fail(S, `the comparison does not say: ${want}`);
      if (q.includes(WHY_NOTE)) fail(S, "the scoring clone's own note reaches the reader");
      const shown = q.replace(/<[^>]+>/g, " ");
      for (const chip of ["MATCH", "DIFFERS", "UNAVAILABLE", "REVIEW"]) {
        if (new RegExp(`\\b${chip}\\b`).test(shown)) fail(S, `a bare ${chip} reaches the reader`);
      }
      for (const bad of ["undefined", "NaN", "[object Object]"]) {
        if (q.includes(bad)) fail(S, `the comparison renders "${bad}"`);
      }
      // JSON download
      p.node("#dl-json").onclick();
      if (!p.st.download) fail(S, "the download wrote nothing");
      else if (/NOT_A_SCORE_SENTENCE|comparisons_this_session|"compare"/.test(p.st.download)) {
        fail(S, "the JSON download carries the comparison, which discloses the key");
      }
      // PNG: the clone must have its comparison section removed
      let asked = null, removed = false;
      p.node("#panel").cloneNode = () => ({ setAttribute() {},
        querySelector: s => { asked = s; return { remove() { removed = true; } }; } });
      if (!p.node("#png").onclick) fail(S, "no PNG button");
      else {
        p.node("#png").onclick();
        if (asked !== "#cmp-section" || !removed) fail(S, "the PNG carries the comparison, which discloses the key");
      }
      // a new run clears the previous record's comparison
      await p.specRun();
      if (p.panel().includes("uses the variable the paper recorded")) {
        fail(S, "a new record shows the previous record's comparison");
      }
    }
  }
  // 2. an answer that lands after a newer run started is dropped
  {
    const S = "stale";
    const p = await comparedPage({ enable: true, compareDelayMs: 200 });
    if (!p) fail(S, "no comparison section to drive");
    else {
      const inflight = p.node("#cmp-go").onclick();
      await sleep(20);
      await p.specRun();
      await inflight;
      await sleep(20);
      if (p.panel().includes("uses the variable the paper recorded")) {
        fail(S, "a comparison of the previous record rendered under a newer one");
      }
    }
  }
  // 3. a refusal
  {
    const S = "refusal";
    const p = await page({ enable: true, refusal: true });
    p.ask.onclick();
    await p.specRun();
    if (!/refused this pair, so there is nothing to place beside the paper/.test(p.panel())) {
      fail(S, "a refusal does not say there is nothing to compare");
    }
    if (p.panel().includes('id="cmp-go"')) fail(S, "a refusal offers a Compare button");
  }
  // 4. no bibliography loaded
  {
    const S = "no papers";
    const p = await page({ enable: true, noPapers: true });
    p.ask.onclick();
    await p.specRun();
    if (!/no paper to compare against/.test(p.panel())) fail(S, "an empty bibliography is not stated");
    if (p.panel().includes('id="cmp-go"')) fail(S, "an empty bibliography offers a Compare button");
  }
  // 5. route off
  {
    const S = "off";
    const p = await page({ enable: false });
    p.ask.onclick();
    await p.specRun();
    if (/compare with the paper/.test(p.panel())) fail(S, "the section shows with the route off: a dead control");
  }
  console.log(failed ? `RED: ${failed} problem(s)`
    : "GREEN: compare names the record by ticket, speaks in sentences, stays out of both downloads, never shows a stale comparison, and hides when it cannot help");
  process.exit(failed ? 1 : 0);
})();

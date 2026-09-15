// Headless render of every panel for every example under a DOM stub.
// Run by parse.py. Exits non-zero on any exception, or if a rendered panel
// contains "undefined" or "NaN" — the two ways a renamed artifact field fails
// silently in a browser. Usage: node render.js <site dir>
"use strict";
const fs = require("fs"), path = require("path");
const site = process.argv[2];
const html = fs.readFileSync(path.join(site, "index.html"), "utf8");
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);

const nodes = {};
function node(id) {
  if (!nodes[id]) nodes[id] = { id, innerHTML: "", value: "", onclick: null, dataset: {}, style: {}, scrollHeight: 10,
    getBoundingClientRect: () => ({ width: 10, height: 10 }), cloneNode: () => ({ setAttribute() {} }), textContent: "" };
  return nodes[id];
}
const byData = [];
const document = {
  querySelector: s => node(s),
  querySelectorAll: s => {
    if (s === "style") return [{ textContent: "" }];
    const m = /\[data-(\w+)\]/.exec(s); if (!m) return [];
    // one stub per rendered button, carrying its data-* value
    const attr = m[1], html = Object.values(nodes).map(n => n.innerHTML).join("");
    const re = new RegExp(`data-${attr}="([^"]+)"`, "g"); const out = [];
    for (const x of html.matchAll(re)) { const b = { dataset: { [attr]: x[1] }, onclick: null }; out.push(b); byData.push(b); }
    return out;
  },
  createElement: () => ({ click() {}, set href(v) {}, get href() { return ""; }, width: 0, height: 0,
    getContext: () => ({ scale() {}, fillRect() {}, drawImage() {} }), toBlob(cb) { cb(new global.Blob([""])); } }),
  createElementNS: () => ({ setAttribute() {}, appendChild() {}, textContent: "" }),
  documentElement: { outerHTML: "<html>", cloneNode: () => ({ appendChild() {}, querySelector: () => ({ appendChild() {}, remove() {} }), outerHTML: "<html>" }) },
  getElementById: () => null,
};
global.document = document;
global.window = { devicePixelRatio: 1 };
global.Blob = class { constructor(parts) { this.size = parts.join("").length; } };
global.URL = { createObjectURL: () => "blob:x", revokeObjectURL() {} };
global.alert = () => {};
global.Image = class { set src(v) { if (this.onload) this.onload(); } };
global.XMLSerializer = class { serializeToString() { return "<svg/>"; } };
global.fetch = async rel => ({ json: async () => JSON.parse(fs.readFileSync(path.join(site, rel), "utf8")) });

let failed = 0;
function check(label) {
  const p = node("#panel").innerHTML;
  if (!p.trim()) { console.error(`render: ${label}: empty panel`); failed++; }
  for (const bad of ["undefined", "NaN", "[object Object]"]) {
    if (p.includes(bad)) { console.error(`render: ${label}: panel contains "${bad}"`); failed++; }
  }
  // An ESCAPED entity reference is always a bug: `esc(xs.join(" &middot; "))`
  // escapes the separator's own ampersand, so the reader sees the literal text
  // "&middot;". Three panels shipped that way. Escape each value, then join.
  // A bare "&amp;" is NOT checked -- that is correct output for a real ampersand
  // in a venue name -- only an ampersand followed by an entity name.
  const ent = p.match(/&amp;(?:[a-zA-Z][a-zA-Z0-9]{1,9}|#\d{1,6});/);
  if (ent) { console.error(`render: ${label}: escaped entity ${ent[0]} renders as text`); failed++; }
  // "PLACEHOLDER" told the reader what the panel is NOT, in a word from the
  // build's own vocabulary. A stage that has not run says "NOT YET RUN"; one
  // that has says what it did. Guarded so the word cannot drift back in.
  if (/PLACEHOLDER/.test(p)) {
    console.error(`render: ${label}: panel says PLACEHOLDER; say what the stage did or "NOT YET RUN"`);
    failed++;
  }
  // Words from other fields that mean something else to the reader this page
  // is for: an endpoint is an outcome, transduction is a phage moving DNA, MCP
  // is nothing. Five reviewers converged on the first. The rendered panel is
  // what the reader sees, so that is what is scanned; a code comment may still
  // say endpoint. "harness" is not listed: the Metrics headline is quoted
  // verbatim from the scored record and contains it, and the quotation stays.
  const jargon = p.match(/\b(?:endpoint|transduction|MCP|prose resolver)\b/i);
  if (jargon) { console.error(`render: ${label}: panel says "${jargon[0]}" to the reader`); failed++; }
}
// The footer must say, under every committed panel, that the figures are
// committed. It was scoped to live panels and went empty everywhere else.
function checkFoot(label) {
  const f = node("#foot").innerHTML;
  if (!/site\/artifacts/.test(f)) { console.error(`render: ${label}: footer does not say where the figures come from`); failed++; }
}
(async () => {
  for (const s of scripts) new Function(s)();       // runs load().then(...)
  await new Promise(r => setTimeout(r, 300));
  const stages = [...node("#rail").innerHTML.matchAll(/data-s="([^"]+)"/g)].map(m => m[1]);
  const examples = [...node("#examples").innerHTML.matchAll(/data-ex="([^"]+)"/g)].map(m => m[1]);
  if (!stages.length) { console.error("render: rail is empty after load"); process.exit(1); }
  const clickData = (attr, val) => {
    document.querySelectorAll(`[data-${attr}]`);
    const b = byData.filter(x => x.dataset[attr] === val).pop();
    // handlers were attached to the stubs returned at draw time; re-run the
    // page's own attach by re-dispatching through the last set
    return b;
  };
  // Drive the page through its own onclick handlers: rebuild them per draw.
  const fire = (attr, val) => {
    const list = document.querySelectorAll(`[data-${attr}]`);
    // the page attached handlers to the objects it received; find them
    const target = byData.filter(x => x.dataset[attr] === val && x.onclick).pop();
    if (!target) throw new Error(`no handler for data-${attr}=${val}`);
    target.onclick();
  };
  // Handlers are attached at draw()/examples() time to the stubs returned then;
  // since querySelectorAll returns fresh stubs each call, re-attach by calling
  // the page's rail()/examples() is not possible from here. Instead the page
  // exposes nothing, so we re-invoke via a second evaluation of the handlers:
  // simplest robust approach — locate and call the functions by name.
  const fnames = ["rail", "examples", "draw"];
  let ok = true;
  for (const ex of examples.length ? examples : [null]) {
    if (ex !== null) {
      document.querySelectorAll("[data-ex]");
      const b = byData.filter(x => x.dataset.ex === ex && x.onclick).pop();
      if (b) b.onclick(); else { console.error(`render: no example handler ${ex}`); failed++; }
    }
    for (const st of stages) {
      document.querySelectorAll("[data-s]");
      const b = byData.filter(x => x.dataset.s === st && x.onclick).pop();
      if (b) { try { b.onclick(); } catch (e) { console.error(`render: ${st}/${ex}: ${e.message}`); failed++; continue; } }
      else { console.error(`render: no stage handler ${st}`); failed++; continue; }
      check(`${st}/example ${ex}`);
      if (st !== "metrics") checkFoot(`${st}/example ${ex}`);
    }
  }
  // With no server, the pipeline button is off and the page says why; both
  // are re-applied by draw(), so any panel is a fair time to look.
  if (node("#ask").disabled !== true) { console.error("render: ask button is enabled with no server"); failed++; }
  if (!/static/i.test(node("#served").textContent)) { console.error("render: nothing says the page is served statically"); failed++; }
  // typed request that matches nothing
  node("#q").value = "a request with no committed run";
  node("#run").onclick();
  check("typed/no-run");
  // Enter in the search box must be a Search, not nothing.
  let entered = false; const runOnce = node("#run").onclick;
  node("#run").onclick = () => { entered = true; runOnce(); };
  node("#q").onkeydown({ key: "Enter", preventDefault() {} });
  if (!entered) { console.error("render: Enter in the search box does nothing"); failed++; }
  // The unmatched query must not take the committed stages with it: this
  // ordering defect made Metrics, Score and Generate unreachable until reload.
  for (const st of ["metrics", "score", "generate"]) {
    document.querySelectorAll("[data-s]");
    const b = byData.filter(x => x.dataset.s === st && x.onclick).pop();
    if (b) b.onclick();
    const p = node("#panel").innerHTML;
    if (/NO COMMITTED RUN/.test(p)) { console.error(`render: typed/no-run hides the ${st} stage`); failed++; }
    if (st === "metrics" && !/Cohort bibliography/.test(p)) { console.error("render: typed/no-run: bibliography table missing"); failed++; }
  }
  // And the retriever still says so, with the query verbatim.
  document.querySelectorAll("[data-s]");
  const rb = byData.filter(x => x.dataset.s === "retriever" && x.onclick).pop();
  if (rb) rb.onclick();
  if (!/NO COMMITTED RUN/.test(node("#panel").innerHTML)) { console.error("render: typed/no-run: retriever does not say so"); failed++; }
  // download and png handlers, if present
  for (const id of ["#dl-src", "#png"]) if (node(id).onclick) { try { node(id).onclick(); } catch (e) { console.error(`render: ${id}: ${e.message}`); failed++; } }
  console.log(`render: ${stages.length} stage(s) x ${Math.max(examples.length, 1)} example(s) rendered${failed ? `, ${failed} problem(s)` : ""}`);
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error("render: " + (e.stack || e)); process.exit(1); });

// Headless render of every panel for every example under a DOM stub.
// Run by parse.py. Exits non-zero on any exception, or if a rendered panel
// contains "undefined" or "NaN" — the two ways a renamed artefact field fails
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
    }
  }
  // typed request that matches nothing
  node("#q").value = "a request with no committed run";
  node("#run").onclick();
  check("typed/no-run");
  // download and png handlers, if present
  for (const id of ["#dl-src", "#png"]) if (node(id).onclick) { try { node(id).onclick(); } catch (e) { console.error(`render: ${id}: ${e.message}`); failed++; } }
  console.log(`render: ${stages.length} stage(s) x ${Math.max(examples.length, 1)} example(s) rendered${failed ? `, ${failed} problem(s)` : ""}`);
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error("render: " + (e.stack || e)); process.exit(1); });

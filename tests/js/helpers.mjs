import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

export const uiDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../ui");

export const HOSTILE = [
  "<img src=x onerror=alert(1)>.txt",
  '"><script>alert(1)</script>.txt',
  "x' onmouseover='alert(1).txt",
  'x" autofocus onfocus="alert(1).txt',
  "<svg onload=alert(1)>.txt",
  "&lt;b&gt;already&amp;escaped.txt",
  "`${alert(1)}`.txt",
  '</div><div class="row">fake row.txt',
];

export const benign = (count) => Array.from({ length: count }, (_, i) => `benign-${i}.txt`);

export async function loadApp() {
  const html = fs.readFileSync(path.join(uiDir, "index.html"), "utf8");
  const dom = new JSDOM(html, {
    url: "http://localhost/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;

  if (window.document.readyState !== "complete") {
    await new Promise((resolve) => window.addEventListener("load", resolve));
  }

  window.CSS ??= { escape: (s) => String(s).replace(/[^\w-]/g, (ch) => `\\${ch}`) };
  window.matchMedia ??= () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  });
  window.pywebview = {
    api: new Proxy({}, { get: (_target, key) => (key === "then" ? undefined : async () => null) }),
  };

  const context = dom.getInternalVMContext();
  const sources = [...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map((m) => m[1]);
  for (const src of sources) {
    const code = fs.readFileSync(path.join(uiDir, src), "utf8");
    new vm.Script(code, { filename: src }).runInContext(context);
  }

  const evaluate = (code, vars = {}) => {
    window.__vars = JSON.stringify(vars);
    return new vm.Script(`(() => { const V = JSON.parse(__vars); ${code} })()`).runInContext(context);
  };

  return { dom, window, document: window.document, evaluate, sources };
}

export async function withApp(fn) {
  const app = await loadApp();
  try {
    return await fn(app);
  } finally {
    app.window.close();
  }
}

export function structure(root) {
  return [...root.querySelectorAll("*")].map(
    (el) => `${el.tagName.toLowerCase()}[${el.getAttributeNames().sort().join(",")}]`,
  );
}

export function assertSameStructure(hostile, plain, label) {
  const a = structure(hostile);
  const b = structure(plain);
  let at = a.findIndex((entry, i) => entry !== b[i]);
  if (at < 0 && a.length !== b.length) at = Math.min(a.length, b.length);
  assert.equal(
    at,
    -1,
    `${label}: hostile text changed the DOM structure (${a.length} nodes vs ${b.length}); ` +
      `first difference at node ${at}: ${a[at]} vs ${b[at]}`,
  );
}

export function mount(app) {
  const host = app.document.createElement("div");
  app.document.body.append(host);
  app.window.__host = host;
  return host;
}

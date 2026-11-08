import assert from "node:assert/strict";
import test from "node:test";

import { withApp } from "./helpers.mjs";

const RAW = "OSError(36, 'File name too long')";
const SENTENCE = "Something went wrong. Details are in the log.";

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function failWith(app, method) {
  app.evaluate(
    `window.logged = [];
     const nativeError = console.error;
     console.error = (...args) => { window.logged.push(args.map(String).join(' ')); };
     window.pywebview.api = {
       ${method}: async () => { throw new Error(V.raw); },
       save_settings: async () => {},
     };`,
    { raw: RAW },
  );
}

const logged = (app) => JSON.parse(app.evaluate("return JSON.stringify(window.logged);"));

test("scan: an unexpected failure shows a sentence and sends the detail to the log", async () => {
  await withApp(async (app) => {
    failWith(app, "scan");
    app.evaluate("document.getElementById('path-input').value = '/some/folder'; startScan();");
    await flush();

    const shown = app.document.getElementById("scan-path-error").textContent;
    assert.ok(shown.includes(SENTENCE));
    assert.ok(!shown.includes("36"));
    assert.ok(logged(app).some((line) => line.includes(RAW)));
  });
});

test("export: an unexpected failure shows a sentence and sends the detail to the log", async () => {
  await withApp(async (app) => {
    failWith(app, "export");
    app.evaluate(
      `State.reset(V.tree);
       document.querySelectorAll('.fmt-cell').forEach(cell =>
         cell.querySelector('.fmt-input').checked = cell.dataset.fmt === 'MD');
       document.getElementById('out-input').value = '/out';`,
      { tree: [
        { lvl: 0, type: "folder", name: "d", path: "/d", size: 0, mtime: 0 },
        { lvl: 1, type: "file", name: "a.txt", path: "/d/a.txt", size: 3, mtime: 0 },
      ] },
    );
    await app.evaluate("return Export.doExport();");

    const shown = app.document.getElementById("export-result").textContent;
    assert.equal(shown, SENTENCE);
    assert.ok(logged(app).some((line) => line.includes(RAW)));
  });
});

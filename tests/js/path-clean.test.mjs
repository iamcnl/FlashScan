import assert from "node:assert/strict";
import test from "node:test";

import { withApp } from "./helpers.mjs";

const clean = (app, raw) => app.evaluate("return cleanPath(V.raw);", { raw });

test("cleanPath: removes the quotes Explorer adds and the spaces around them", async () => {
  await withApp(async (app) => {
    assert.equal(clean(app, '"C:\\My Folder"'), "C:\\My Folder");
    assert.equal(clean(app, '  "C:\\My Folder"  '), "C:\\My Folder");
    assert.equal(clean(app, "  C:\\My Folder  "), "C:\\My Folder");
  });
});

test("cleanPath: a bare drive letter means the drive root, not the current folder on it", async () => {
  await withApp(async (app) => {
    assert.equal(clean(app, "D:"), "D:\\");
    assert.equal(clean(app, '"d:"'), "d:\\");
    assert.equal(clean(app, "D:\\"), "D:\\");
    assert.equal(clean(app, "D:folder"), "D:folder");
  });
});

test("cleanPath: leaves valid special paths and empty values alone", async () => {
  await withApp(async (app) => {
    assert.equal(clean(app, "\\\\?\\C:\\Folder"), "\\\\?\\C:\\Folder");
    assert.equal(clean(app, "\\\\server\\share"), "\\\\server\\share");
    assert.equal(clean(app, ""), "");
    assert.equal(clean(app, null), "");
  });
});

test("scan: the backend gets the cleaned path and the field shows it", async () => {
  await withApp(async (app) => {
    app.evaluate(
      `window.__sent = null;
       window.pywebview.api = { scan: async (params) => { window.__sent = params.path; return { busy: true }; } };
       document.getElementById('path-input').value = '  "D:"  ';
       startScan();`,
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    assert.equal(app.window.__sent, "D:\\");
    assert.equal(app.document.getElementById("path-input").value, "D:\\");
  });
});

test("export: the backend gets the cleaned output folder and the field shows it", async () => {
  await withApp(async (app) => {
    app.evaluate(
      `State.reset(V.tree);
       window.__sent = null;
       window.pywebview.api = { export: async (params) => { window.__sent = params.output_dir; return { success: false, error: 'x' }; } };
       document.querySelectorAll('.fmt-cell').forEach(cell =>
         cell.querySelector('.fmt-input').checked = cell.dataset.fmt === 'MD');
       document.getElementById('out-input').value = '"C:\\\\Out Folder"';`,
      { tree: [{ lvl: 0, type: "file", name: "a.txt", path: "/a.txt", size: 1, mtime: 0 }] },
    );
    await app.evaluate("return Export.doExport();");

    assert.equal(app.window.__sent, "C:\\Out Folder");
    assert.equal(app.document.getElementById("out-input").value, "C:\\Out Folder");
  });
});
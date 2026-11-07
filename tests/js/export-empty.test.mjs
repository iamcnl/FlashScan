import assert from "node:assert/strict";
import test from "node:test";

import { withApp } from "./helpers.mjs";

const TREE = [
  { lvl: 0, type: "folder", name: "drive", path: "/d", size: 0, mtime: 0 },
  { lvl: 1, type: "file", name: "a.txt", path: "/d/a.txt", size: 3, mtime: 0 },
  { lvl: 1, type: "file", name: "b.log", path: "/d/b.log", size: 4, mtime: 0 },
  { lvl: 1, type: "folder", name: "docs", path: "/d/docs", size: 0, mtime: 0 },
  { lvl: 2, type: "file", name: "n.md", path: "/d/docs/n.md", size: 6, mtime: 0 },
];

const WARNING = "nothing selected to export";

function load(app) {
  app.evaluate("State.reset(V.tree);", { tree: TREE });
}

function stats(app) {
  return JSON.parse(app.evaluate("return JSON.stringify(State.exportStats());"));
}

function summary(app) {
  app.evaluate("Export.updateSummary();");
  return app.document.getElementById("export-summary");
}

test("export stats: a fresh scan has something to export", async () => {
  await withApp(async (app) => {
    load(app);

    assert.deepEqual(stats(app), { count: 3, size: 13, nameOnly: 0, empty: false });
    assert.ok(!summary(app).textContent.includes(WARNING));
  });
});

test("export stats: deselect all leaves nothing to export and the summary says so", async () => {
  await withApp(async (app) => {
    load(app);
    app.evaluate("Tree.deselectAll();");

    assert.equal(stats(app).empty, true);
    assert.ok(summary(app).textContent.includes(WARNING));
  });
});

test("export stats: folder names only is a legitimate export", async () => {
  await withApp(async (app) => {
    load(app);
    app.evaluate("Tree.setAllFoldersNameOnly();");

    const { count, nameOnly, empty } = stats(app);
    assert.equal(count, 0);
    assert.ok(nameOnly > 0);
    assert.equal(empty, false);
    assert.ok(!summary(app).textContent.includes(WARNING));
  });
});

test("export stats: an extension filter that matches no selected file counts as empty", async () => {
  await withApp(async (app) => {
    load(app);
    assert.equal(stats(app).count, 3);

    app.evaluate("State.activeExts = new Set(['xyz']);");
    assert.equal(stats(app).empty, true);

    app.evaluate("State.activeExts = new Set(['txt', 'md']);");
    assert.deepEqual(stats(app), { count: 2, size: 9, nameOnly: 0, empty: false });

    app.evaluate("State.activeExts = null;");
    assert.equal(stats(app).count, 3);
  });
});

test("export: nothing selected is refused before the backend is called", async () => {
  await withApp(async (app) => {
    load(app);
    app.evaluate(
      `document.querySelectorAll('.fmt-cell').forEach(cell =>
         cell.classList.toggle('selected', cell.dataset.fmt === 'MD'));
       document.getElementById('out-input').value = '/out';
       window.exportCalls = 0;
       window.pywebview.api = { export: async () => { window.exportCalls++; return { async: true }; } };
       Tree.deselectAll();`,
    );
    await app.evaluate("return Export.doExport();");

    const result = app.document.getElementById("export-result");
    assert.equal(result.textContent, "Nothing selected to export.");
    assert.ok(result.classList.contains("error"));
    assert.equal(app.window.exportCalls, 0);
  });
});

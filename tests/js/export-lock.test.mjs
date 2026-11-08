import assert from "node:assert/strict";
import test from "node:test";

import { withApp } from "./helpers.mjs";

const TREE = [
  { lvl: 0, type: "folder", name: "drive", path: "/d", size: 0, mtime: 0 },
  { lvl: 1, type: "file", name: "a.txt", path: "/d/a.txt", size: 3, mtime: 0 },
];

const HINT = "Export in progress";

async function onExportScreen(fn) {
  await withApp(async (app) => {
    app.evaluate(
      `State.reset(V.tree);
       initSteps();
       Nav.unlock(2);
       Nav.go(2);
       document.querySelectorAll('.fmt-cell').forEach(cell =>
         cell.querySelector('.fmt-input').checked = cell.dataset.fmt === 'MD');
       document.getElementById('out-input').value = '/out';`,
      { tree: TREE },
    );
    await fn(app);
  });
}

const step = (app, n) => app.document.getElementById(`step-${n}`);
const back = (app) => app.document.getElementById("btn-back-1");
const current = (app) => app.evaluate("return Nav._current;");

function assertHeld(app) {
  assert.equal(back(app).disabled, true);
  for (const n of [0, 1]) {
    assert.equal(step(app, n).getAttribute("aria-disabled"), "true");
    assert.equal(step(app, n).title, HINT);
    assert.equal(step(app, n).classList.contains("clickable"), false);
  }
  assert.equal(step(app, 2).hasAttribute("aria-disabled"), false);
}

function assertFree(app) {
  assert.equal(back(app).disabled, false);
  for (const n of [0, 1, 2]) {
    assert.equal(step(app, n).hasAttribute("aria-disabled"), false);
    assert.equal(step(app, n).hasAttribute("title"), false);
  }
}

test("export lock: nothing leaves the export screen while an export runs", async () => {
  await onExportScreen((app) => {
    app.evaluate("Export._setRunning(true);");

    assertHeld(app);
    app.evaluate("Nav.go(1);");
    step(app, 0).click();
    back(app).click();
    assert.equal(current(app), 2);
  });
});

test("export lock: a successful export releases it", async () => {
  await onExportScreen((app) => {
    app.evaluate("Export._setRunning(true); Export.onDone({ success: true, saved: [], errors: [] });");

    assertFree(app);
    app.evaluate("Nav.go(1);");
    assert.equal(current(app), 1);
  });
});

test("export lock: a failed export releases it", async () => {
  await onExportScreen((app) => {
    app.evaluate("Export._setRunning(true); Export.onDone({ success: false, error: 'boom' });");

    assertFree(app);
    assert.equal(app.document.getElementById("export-result").textContent, "Error: boom");
  });
});

test("export lock: it is held after the backend accepts the export and released by onExportDone", async () => {
  await onExportScreen(async (app) => {
    app.evaluate("window.pywebview.api = { export: async () => ({ async: true }) };");
    await app.evaluate("return Export.doExport();");
    assertHeld(app);

    app.evaluate("onExportDone({ success: true, saved: [], errors: [] });");
    assertFree(app);
  });
});

test("export lock: a refused export does not hold the user", async () => {
  await onExportScreen(async (app) => {
    app.evaluate("window.pywebview.api = { export: async () => ({ success: false, error: 'nope' }) };");
    await app.evaluate("return Export.doExport();");

    assertFree(app);
  });
});

test("export lock: a failing call to the backend does not hold the user", async () => {
  await onExportScreen(async (app) => {
    app.evaluate("window.pywebview.api = { export: async () => { throw new Error('gone'); } };");
    await app.evaluate("return Export.doExport();");

    assertFree(app);
  });
});

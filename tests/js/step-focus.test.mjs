import assert from "node:assert/strict";
import test from "node:test";

import { withApp } from "./helpers.mjs";

const active = (app) => app.document.activeElement?.id;
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function freshApp(fn) {
  await withApp(async (app) => {
    app.window.dispatchEvent(new app.window.KeyboardEvent("keydown", { key: "Tab" }));
    app.evaluate("Tree.init(document.getElementById('tree')); initSteps(); Nav.unlock(2); Nav.go(0);");
    await fn(app);
  });
}

test("each step moves focus to where its work starts", async () => {
  await freshApp(async (app) => {
    app.evaluate("Nav.go(1);");
    assert.equal(active(app), "tree");

    app.evaluate("Nav.go(2);");
    assert.equal(active(app), "export-heading");

    app.evaluate("Nav.go(0);");
    assert.equal(active(app), "path-input");
  });
});

test("starting a new scan puts focus back in the path field", async () => {
  await freshApp(async (app) => {
    app.evaluate("Nav.go(2); Nav.reset();");
    assert.equal(active(app), "path-input");
  });
});

test("opening the step you are already on leaves focus alone", async () => {
  await freshApp(async (app) => {
    app.evaluate("Nav.go(1);");
    app.document.getElementById("search-input").focus();

    app.evaluate("Nav.go(1);");

    assert.equal(active(app), "search-input");
  });
});

test("the export heading can be focused by script but is not a tab stop", async () => {
  await freshApp(async (app) => {
    assert.equal(app.document.getElementById("export-heading").getAttribute("tabindex"), "-1");
  });
});

const RESULT = {
  tree: [
    { lvl: 0, type: "folder", name: "root", path: "/", size: 0, mtime: 0 },
    { lvl: 1, type: "file", name: "a.txt", path: "/a.txt", size: 1, mtime: 0 },
  ],
  file_count: 1, folder_count: 1, skipped: 0, unreadable_count: 0, links_skipped: 0,
  volume_label: "", scan_id: 1, depth: 5,
};

test("scan completion is announced in a region that is always rendered", async () => {
  await freshApp(async (app) => {
    const live = app.document.getElementById("tree-live");
    assert.equal(live.closest(".screen"), null);

    app.window.__result = RESULT;
    await app.evaluate("return applyScanResult(__result);");
    await wait(80);

    assert.equal(live.textContent, "Done — 1 files, 1 folders.");
  });
});

test("scanning the same folder twice announces it twice", async () => {
  await freshApp(async (app) => {
    const live = app.document.getElementById("tree-live");
    app.window.__result = RESULT;

    await app.evaluate("return applyScanResult(__result);");
    await wait(80);
    await app.evaluate("return applyScanResult(__result);");

    assert.equal(live.textContent, "");
    await wait(80);
    assert.equal(live.textContent, "Done — 1 files, 1 folders.");
  });
});
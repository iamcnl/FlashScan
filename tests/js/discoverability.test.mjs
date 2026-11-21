import assert from "node:assert/strict";
import test from "node:test";

import { withApp } from "./helpers.mjs";

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const note = (app) => app.document.getElementById("ext-note").textContent;

const file = (name) => ({ lvl: 1, type: "file", name, path: `/${name}`, size: 1, mtime: 0 });

async function scanned(app, names) {
  app.window.__tree = [{ lvl: 0, type: "folder", name: "root", path: "/", size: 0, mtime: 0 }, ...names.map(file)];
  app.evaluate("Tree.init(document.getElementById('tree'));");
  await app.evaluate("return Filters.init();");
  app.evaluate("State.treeData = __tree; Filters.updateCounts();");
}

test("unticking extensions explains the files they cannot hide", async () => {
  await withApp(async (app) => {
    await scanned(app, ["a.txt", "b.zzz", "README"]);
    assert.equal(note(app), "");

    app.evaluate("Filters.deselectNone();");
    assert.equal(note(app), "2 files have no extension or one not listed here, so these checkboxes don’t affect them.");

    app.evaluate("Filters.selectAll();");
    assert.equal(note(app), "");
  });
});

test("the note uses the singular for one file", async () => {
  await withApp(async (app) => {
    await scanned(app, ["a.txt", "README"]);
    app.evaluate("Filters.deselectNone();");

    assert.equal(note(app), "1 file has no extension or one not listed here, so these checkboxes don’t affect it.");
  });
});

test("there is no note when every file has a listed extension", async () => {
  await withApp(async (app) => {
    await scanned(app, ["a.txt", "b.txt"]);
    app.evaluate("Filters.deselectNone();");

    assert.equal(note(app), "");
  });
});

test("a single unticked extension is enough to show the note", async () => {
  await withApp(async (app) => {
    await scanned(app, ["a.txt", "README"]);
    app.evaluate("Filters._extState.txt = false; Filters._applyExtFilter();");

    assert.match(note(app), /^1 file has/);
  });
});

test("adding a custom extension takes its files out of the count", async () => {
  await withApp(async (app) => {
    await scanned(app, ["a.txt", "b.zzz", "README"]);
    app.evaluate("Filters.deselectNone();");
    assert.match(note(app), /^2 files have/);

    app.evaluate("Filters._addCustomExt('zzz');");
    await wait(60);

    assert.match(note(app), /^1 file has/);
  });
});

test("the note is read out when it appears", async () => {
  await withApp(async (app) => {
    const el = app.document.getElementById("ext-note");

    assert.equal(el.getAttribute("role"), "status");
    assert.equal(el.getAttribute("aria-live"), "polite");
  });
});

test("shortcuts are shown on the controls that have them", async () => {
  await withApp(async (app) => {
    const get = (id) => app.document.getElementById(id);

    assert.equal(get("search-input").placeholder, "search files… (Ctrl+F)");
    assert.equal(get("search-input").getAttribute("aria-keyshortcuts"), "Control+F");
    assert.equal(get("btn-search-clear").title, "Clear search (Esc)");
    for (const [id, name, key] of [
      ["btn-select-all", "Select all", "A"],
      ["btn-deselect-all", "Deselect all", "D"],
      ["btn-expand", "Expand all", "E"],
      ["btn-collapse", "Collapse all", "W"],
    ]) {
      assert.equal(get(id).title, `${name} (Ctrl+${key})`);
      assert.equal(get(id).getAttribute("aria-keyshortcuts"), `Control+${key}`);
    }
  });
});

test("the log button says where the log is shown", async () => {
  await withApp(async (app) => {
    const button = app.document.getElementById("btn-open-log");

    assert.equal(button.title, "Show log file in Explorer");
    assert.equal(button.getAttribute("aria-label"), "Show log file in Explorer");
  });
});

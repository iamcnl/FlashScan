import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { withApp } from "./helpers.mjs";

const fixture = JSON.parse(
  fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../selection_cases.json"), "utf8"),
);

const ROOT = "E:\\";
const winPath = (rel) => (rel ? ROOT + rel.replaceAll("/", "\\") : ROOT);
const levelOf = (rel) => (rel ? rel.split("/").length : 0);

function treeOf(entries) {
  return entries.map((e) => ({
    lvl: levelOf(e.path),
    type: e.type,
    name: e.path ? e.path.split("/").pop() : "E:",
    path: winPath(e.path),
    size: e.size ?? 0,
    mtime: 0,
  }));
}

function boot(app, entries) {
  app.evaluate("Tree.invalidate = () => {}; Tree.render = () => {}; State.reset(V.tree);", { tree: treeOf(entries) });
}

const stats = (app) => JSON.parse(app.evaluate("return JSON.stringify(State.exportStats());"));
const states = (app) => JSON.parse(app.evaluate("return JSON.stringify(State.folderStates);"));

const TREE = [
  { path: "", type: "folder" },
  { path: "top.txt", type: "file", size: 1 },
  { path: "a", type: "folder" },
  { path: "a/one.txt", type: "file", size: 2 },
  { path: "a/b", type: "folder" },
  { path: "a/b/two.txt", type: "file", size: 4 },
  { path: "c", type: "folder" },
  { path: "c/three.txt", type: "file", size: 8 },
];

test("re-ticking a file inside an excluded folder reopens every folder above it", async () => {
  await withApp((app) => {
    boot(app, TREE);
    app.evaluate("Tree._cycleFolderState(V.a); Tree._cycleFolderState(V.a);", { a: winPath("a") });
    assert.equal(states(app)[winPath("a/b")], "skip");

    app.evaluate("Tree._toggleFile(V.f, null);", { f: winPath("a/b/two.txt") });

    const s = states(app);
    assert.equal(s[winPath("a/b")], "full");
    assert.equal(s[winPath("a")], "partial");
    assert.equal(s[ROOT], "partial");
    assert.deepEqual(stats(app), { count: 3, size: 13, nameOnly: 0, empty: false });
  });
});

test("names only on a drive root hides everything below it", async () => {
  await withApp((app) => {
    boot(app, TREE);
    app.evaluate("State.setFolderState(V.root, 'name');", { root: ROOT });
    assert.deepEqual(stats(app), { count: 0, size: 0, nameOnly: 1, empty: false });

    app.evaluate("Tree.selectAll(); Tree.setAllFoldersNameOnly();");
    assert.deepEqual(stats(app), { count: 0, size: 0, nameOnly: 1, empty: false });
  });
});

test("deselect all on a drive root, then ticking one file, exports that file", async () => {
  await withApp((app) => {
    boot(app, TREE);
    app.evaluate("Tree.deselectAll();");
    assert.equal(stats(app).empty, true);

    app.evaluate("Tree._toggleFile(V.f, null);", { f: winPath("a/b/two.txt") });
    assert.deepEqual(stats(app), { count: 1, size: 4, nameOnly: 0, empty: false });
    assert.equal(states(app)[ROOT], "partial");

    app.evaluate("Tree._toggleFile(V.f, null);", { f: winPath("top.txt") });
    assert.deepEqual(stats(app), { count: 2, size: 5, nameOnly: 0, empty: false });
  });
});

test("unticking the only re-ticked file returns an excluded folder to excluded", async () => {
  await withApp((app) => {
    boot(app, TREE);
    app.evaluate("State.setFolderState(V.a, 'skip');", { a: winPath("a") });

    app.evaluate("Tree._toggleFile(V.f, null);", { f: winPath("a/one.txt") });
    assert.equal(states(app)[winPath("a")], "partial");

    app.evaluate("Tree._toggleFile(V.f, null);", { f: winPath("a/one.txt") });
    assert.equal(states(app)[winPath("a")], "skip");
    assert.equal(states(app)[winPath("a/b")], "skip");
    assert.deepEqual(stats(app), { count: 2, size: 9, nameOnly: 0, empty: false });
  });
});

test("a folder directly under a drive root finds its parent", async () => {
  await withApp((app) => {
    boot(app, TREE);
    assert.equal(app.evaluate("return State.parentPath(V.p);", { p: winPath("a") }), ROOT);
    assert.equal(app.evaluate("return State.parentPath(V.p);", { p: ROOT }), null);
  });
});

for (const c of fixture.cases) {
  test(`export stats match the exporter: ${c.name}`, async () => {
    await withApp((app) => {
      boot(app, fixture.tree);
      app.evaluate(
        `for (const [p, s] of Object.entries(V.states)) State.folderStates[p] = s;
         for (const p of V.deselected) State.selectedFiles.delete(p);
         State.hiddenExts = V.exts ? new Set(V.exts) : null;
         State._markDirty();`,
        {
          states: Object.fromEntries(Object.entries(c.states ?? {}).map(([k, v]) => [winPath(k), v])),
          deselected: (c.deselected ?? []).map(winPath),
          exts: c.hidden_exts ?? null,
        },
      );
      const got = stats(app);
      assert.equal(got.count, c.files);
      assert.equal(got.size, c.size);
      assert.equal(got.nameOnly, c.name_only);
    });
  });
}

test("dropping a file on the window is cancelled", async () => {
  await withApp((app) => {
    const result = app.evaluate(`
      const e = new Event('drop', { cancelable: true });
      window.dispatchEvent(e);
      const over = new Event('dragover', { cancelable: true });
      window.dispatchEvent(over);
      return JSON.stringify([e.defaultPrevented, over.defaultPrevented]);
    `);
    assert.equal(result, "[true,true]");
  });
});

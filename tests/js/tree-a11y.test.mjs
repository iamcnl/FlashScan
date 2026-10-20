import assert from "node:assert/strict";
import test from "node:test";

import { mount, withApp } from "./helpers.mjs";

const item = (lvl, type, name, path) => ({ lvl, type, name, path, size: type === "file" ? 2048 : 0, mtime: 1_700_000_000 });

const DATA = [
  item(0, "folder", "drive", "/drive"),
  item(1, "folder", "docs", "/drive/docs"),
  item(2, "file", "a.txt", "/drive/docs/a.txt"),
  item(2, "file", "b.txt", "/drive/docs/b.txt"),
  item(1, "folder", "empty", "/drive/empty"),
  item(1, "file", "top.txt", "/drive/top.txt"),
];

function setup(app) {
  const host = mount(app);
  app.evaluate("State.reset(V.data); Tree.init(__host); Tree.render();", { data: DATA });
  app.window.dispatchEvent(new app.window.KeyboardEvent("keydown", { key: "Tab" }));
  host.focus();
  return host;
}

function press(app, host, key, init = {}) {
  host.dispatchEvent(new app.window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init }));
}

const label = (el) => el.getAttribute("aria-label").split(",")[0];

function goTo(app, host, name) {
  for (let i = 0; i < 20 && label(active(host)) !== name; i++) press(app, host, "ArrowDown");
  assert.equal(label(active(host)), name);
}

const rows = (host) => [...host.querySelectorAll('[role="treeitem"]')];
const names = (host) => rows(host).map((r) => r.getAttribute("aria-label").split(",")[0]);
const active = (host) => host.querySelector(`#${host.getAttribute("aria-activedescendant")}`);

test("tree container is a labelled, focusable tree", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    assert.equal(host.getAttribute("role"), "tree");
    assert.ok(host.getAttribute("aria-label"));
    assert.equal(host.tabIndex, 0);
  });
});

test("every row is a treeitem with level, position and set size", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    const summary = rows(host).map((r) => [
      names(host)[rows(host).indexOf(r)],
      r.getAttribute("aria-level"),
      r.getAttribute("aria-posinset"),
      r.getAttribute("aria-setsize"),
    ]);
    assert.deepEqual(summary, [
      ["drive", "1", "1", "1"],
      ["docs", "2", "1", "3"],
      ["a.txt", "3", "1", "2"],
      ["b.txt", "3", "2", "2"],
      ["empty", "2", "2", "3"],
      ["top.txt", "2", "3", "3"],
    ]);
    assert.equal(new Set(rows(host).map((r) => r.id)).size, rows(host).length);
  });
});

test("folders expose aria-expanded, files expose aria-checked", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    const [, docs, a] = rows(host);
    assert.equal(docs.getAttribute("aria-expanded"), "true");
    assert.equal(a.getAttribute("aria-checked"), "true");
    assert.equal(a.hasAttribute("aria-expanded"), false);
    assert.equal(docs.hasAttribute("aria-checked"), false);
  });
});

test("decorative parts are hidden from assistive technology", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    for (const sel of [".row-arrow", ".ic-primary", ".ic-muted", ".fcb", ".pill"]) {
      for (const el of host.querySelectorAll(sel)) assert.equal(el.getAttribute("aria-hidden"), "true", sel);
    }
  });
});

test("tabbing into the tree activates the first row", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    assert.equal(app.document.activeElement, host);
    assert.equal(label(active(host)), "drive");
    assert.ok(active(host).classList.contains("row-focused"));
  });
});

test("arrow keys move aria-activedescendant to a rendered row", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    press(app, host, "ArrowDown");
    assert.equal(label(active(host)), "docs");
    press(app, host, "ArrowDown");
    assert.equal(label(active(host)), "a.txt");
    press(app, host, "ArrowUp");
    assert.equal(label(active(host)), "docs");
  });
});

test("Home and End jump to the first and last row", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    press(app, host, "End");
    assert.equal(active(host).getAttribute("aria-label").split(",")[0], "top.txt");
    press(app, host, "Home");
    assert.equal(active(host).getAttribute("aria-label").split(",")[0], "drive");
  });
});

test("Right opens a closed folder, then enters it; Left closes it, then goes to the parent", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    goTo(app, host, "docs");
    const docsId = host.getAttribute("aria-activedescendant");

    press(app, host, "ArrowLeft");
    assert.equal(active(host).getAttribute("aria-expanded"), "false");
    assert.equal(rows(host).length, 4);

    press(app, host, "ArrowRight");
    assert.equal(active(host).getAttribute("aria-expanded"), "true");
    assert.equal(host.getAttribute("aria-activedescendant"), docsId);

    press(app, host, "ArrowRight");
    assert.equal(active(host).getAttribute("aria-label").split(",")[0], "a.txt");

    press(app, host, "ArrowLeft");
    assert.equal(host.getAttribute("aria-activedescendant"), docsId);
  });
});

test("Left on a file moves to its parent folder", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    press(app, host, "End");
    press(app, host, "ArrowLeft");
    assert.equal(active(host).getAttribute("aria-label").split(",")[0], "drive");
  });
});

test("Right on an empty folder or a file does not move focus", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    goTo(app, host, "empty");
    const id = host.getAttribute("aria-activedescendant");
    press(app, host, "ArrowRight");
    assert.equal(host.getAttribute("aria-activedescendant"), id);

    goTo(app, host, "top.txt");
    const fileId = host.getAttribute("aria-activedescendant");
    press(app, host, "ArrowRight");
    assert.equal(host.getAttribute("aria-activedescendant"), fileId);
  });
});

test("Space toggles a file and announces the result", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    goTo(app, host, "a.txt");
    press(app, host, " ");

    assert.equal(active(host).getAttribute("aria-checked"), "false");
    assert.equal(app.document.getElementById("tree-live").textContent, "a.txt excluded");
    press(app, host, " ");
    assert.equal(active(host).getAttribute("aria-checked"), "true");
    assert.equal(app.document.getElementById("tree-live").textContent, "a.txt included");
  });
});

test("Space cycles a folder state and announces it", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    goTo(app, host, "docs");
    press(app, host, " ");

    assert.match(active(host).getAttribute("aria-label"), /^docs, folder, names only/);
    assert.equal(app.document.getElementById("tree-live").textContent, "docs: names only");
  });
});

test("Enter on a folder collapses it and announces it", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    goTo(app, host, "docs");
    press(app, host, "Enter");

    assert.equal(active(host).getAttribute("aria-expanded"), "false");
    assert.equal(app.document.getElementById("tree-live").textContent, "docs collapsed");
  });
});

test("navigation keys are left alone while another control has focus", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    const before = host.getAttribute("aria-activedescendant");
    const button = app.document.createElement("button");
    app.document.body.append(button);
    button.focus();
    assert.equal(app.document.activeElement, button);

    const event = new app.window.KeyboardEvent("keydown", { key: " ", bubbles: true, cancelable: true });
    button.dispatchEvent(event);
    assert.equal(event.defaultPrevented, false);

    const arrow = new app.window.KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true });
    button.dispatchEvent(arrow);
    assert.equal(arrow.defaultPrevented, false);
    assert.equal(host.getAttribute("aria-activedescendant"), before);
  });
});

test("modified arrow keys are not swallowed", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    const event = new app.window.KeyboardEvent("keydown", { key: "ArrowLeft", altKey: true, bubbles: true, cancelable: true });
    host.dispatchEvent(event);
    assert.equal(event.defaultPrevented, false);
  });
});

test("aria-activedescendant is cleared when the focused row is filtered out", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    press(app, host, "End");
    assert.ok(host.getAttribute("aria-activedescendant"));

    app.evaluate("State.searchQuery = 'a.txt'; Tree.invalidate(); Tree.render();");
    assert.equal(host.hasAttribute("aria-activedescendant"), false);
  });
});

test("set size and position follow the visible rows after filtering", async () => {
  await withApp(async (app) => {
    const host = setup(app);
    app.evaluate("State.searchQuery = 'b.txt'; Tree.invalidate(); Tree.render();");
    const b = rows(host).find((r) => r.getAttribute("aria-label").startsWith("b.txt"));
    assert.equal(b.getAttribute("aria-posinset"), "1");
    assert.equal(b.getAttribute("aria-setsize"), "1");
  });
});

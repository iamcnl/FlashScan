import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { HOSTILE, assertSameStructure, benign, mount, uiDir, withApp } from "./helpers.mjs";

const HOSTILE_FOLDER = "<img src=x onerror=alert(1)>\"'";
const HOSTILE_NOTE = '"><script>alert(1)</script>';
const HOSTILE_LABEL = "<img src=x onerror=alert(1)>\"'&";
const HOSTILE_OVERRIDE = '"><img src=x onerror=alert(1)>';
const HOSTILE_EXTS = HOSTILE.map((name) => name.toLowerCase());
const basename = (p) => p.replace(/.*[/\\]/, "");

function treeData(files, folder) {
  return [
    { lvl: 0, type: "folder", name: "drive", path: "/drive", size: 0, mtime: 0 },
    { lvl: 1, type: "folder", name: folder, path: `/drive/${folder}`, size: 0, mtime: 0 },
    ...files.map((name) => ({
      lvl: 2, type: "file", name, path: `/drive/${folder}/${name}`, size: 10, mtime: 1_700_000_000,
    })),
  ];
}

function renderTree(app, files, folder, note) {
  const host = mount(app);
  app.evaluate(
    `State.reset(V.data);
     State.folderNotes = { [V.folderPath]: V.note };
     Tree.init(__host);
     Tree.render();`,
    { data: treeData(files, folder), folderPath: `/drive/${folder}`, note },
  );
  return host;
}

// ── Tree rows ────────────────────────────────────────────────────

test("tree rows: hostile names, folder and note change only text, never structure", async () => {
  await withApp(async (hostileApp) => {
    await withApp(async (plainApp) => {
      const hostile = renderTree(hostileApp, HOSTILE, HOSTILE_FOLDER, HOSTILE_NOTE);
      const plain = renderTree(plainApp, benign(HOSTILE.length), "benign-folder", "benign note");

      assertSameStructure(hostile, plain, "tree");
    });
  });
});

test("tree rows: every name, path and note round-trips as plain text", async () => {
  await withApp(async (app) => {
    const host = renderTree(app, HOSTILE, HOSTILE_FOLDER, HOSTILE_NOTE);

    const fileRows = [...host.querySelectorAll('[data-type="file"]')];
    assert.deepEqual(
      fileRows.map((row) => row.querySelector(".row-name").textContent).sort(),
      [...HOSTILE].sort(),
    );
    assert.deepEqual(
      fileRows.map((row) => row.dataset.path).sort(),
      HOSTILE.map((name) => `/drive/${HOSTILE_FOLDER}/${name}`).sort(),
    );
    assert.deepEqual(
      [...host.querySelectorAll(".row-name.folder")].map((el) => el.textContent),
      ["drive", HOSTILE_FOLDER],
    );

    const noteButton = host.querySelector(".note-active");
    assert.equal(noteButton.getAttribute("title"), HOSTILE_NOTE);
    assert.equal(noteButton.dataset.noteBtn, `/drive/${HOSTILE_FOLDER}`);
  });
});

test("tree rows: no element carries an event-handler attribute", async () => {
  await withApp(async (app) => {
    const host = renderTree(app, HOSTILE, HOSTILE_FOLDER, HOSTILE_NOTE);

    const handlers = [...host.querySelectorAll("*")].flatMap((el) =>
      el.getAttributeNames().filter((name) => name.startsWith("on")),
    );
    assert.deepEqual(handlers, []);
    assert.equal(host.querySelectorAll("script, img, iframe, object, embed").length, 0);
  });
});

// ── Context menu ─────────────────────────────────────────────────

for (const type of ["file", "folder"]) {
  test(`context menu (${type}): hostile name only ever appears as header text`, async () => {
    const open = (app, name) => {
      app.evaluate(
        "ContextMenu.show(10, 10, V.path, V.type, { name: V.name, path: V.path, size: 1, mtime: 0 }, Tree);",
        { path: `/drive/${name}`, type, name },
      );
      return app.document.querySelector(".ctx-menu");
    };

    await withApp(async (hostileApp) => {
      await withApp(async (plainApp) => {
        const hostile = open(hostileApp, HOSTILE[0]);
        const plain = open(plainApp, "benign-0.txt");

        assertSameStructure(hostile, plain, `context menu (${type})`);
        const header = hostile.querySelector(".ctx-header");
        assert.equal(header.children.length, 0);
        assert.equal(header.textContent.slice(0, 12), HOSTILE[0].slice(0, 12));
      });
    });
  });
}

// ── Export panel ─────────────────────────────────────────────────

function renderSummary(app, label, overrides) {
  app.evaluate(
    `document.querySelectorAll('.fmt-cell').forEach(cell =>
       cell.classList.toggle('selected', ['MD', 'HTML'].includes(cell.dataset.fmt)));
     State.volumeLabel = V.label;
     Export._nameOverrides = V.overrides;
     Export.updateSummary();`,
    { label, overrides },
  );
  return app.document.getElementById("export-summary");
}

test("export summary: hostile drive label and file-name override change only text", async () => {
  await withApp(async (hostileApp) => {
    await withApp(async (plainApp) => {
      const hostile = renderSummary(hostileApp, HOSTILE_LABEL, { HTML: HOSTILE_OVERRIDE });
      const plain = renderSummary(plainApp, "benign-disk", { HTML: "benign override" });

      assertSameStructure(hostile, plain, "export summary");
    });
  });
});

test("export summary: file-name inputs hold exactly the stem the code computed", async () => {
  await withApp(async (app) => {
    const summary = renderSummary(app, HOSTILE_LABEL, { HTML: HOSTILE_OVERRIDE });

    const inputs = Object.fromEntries(
      [...summary.querySelectorAll(".summary-fname-input")].map((el) => [el.dataset.fmt, el.value]),
    );
    assert.equal(inputs.MD, app.evaluate("return Export._defaultStem('MD');"));
    assert.equal(inputs.HTML, HOSTILE_OVERRIDE);

    const row = [...summary.querySelectorAll(".summary-fname-row")].find((el) => el.dataset.fmt === "HTML");
    assert.equal(row.querySelector(".summary-fname-name").textContent, `${HOSTILE_OVERRIDE}.html`);
  });
});

test("export result: hostile saved paths and error text change only text", async () => {
  const saved = (names) => [names[0], names[3]].map((name) => `/out/${name}.md`);
  const errors = (names) => [names[4], names[7]];

  const finish = (app, names) => {
    app.evaluate("Export.onDone({ success: true, saved: V.saved, errors: V.errors });",
      { saved: saved(names), errors: errors(names) });
    return app.document.getElementById("export-result");
  };

  await withApp(async (hostileApp) => {
    await withApp(async (plainApp) => {
      const hostile = finish(hostileApp, HOSTILE);
      const plain = finish(plainApp, benign(HOSTILE.length));

      assertSameStructure(hostile, plain, "export result");
      assert.deepEqual(
        [...hostile.querySelectorAll(".export-file-link")].map((el) => el.textContent),
        saved(HOSTILE).map(basename),
      );
      assert.deepEqual(
        [...hostile.querySelectorAll(".export-file-link")].map((el) => el.dataset.path),
        saved(HOSTILE),
      );
      assert.equal(hostile.querySelector(".export-errors").textContent, errors(HOSTILE).join(""));
    });
  });
});

test("export failure message is plain text", async () => {
  await withApp(async (app) => {
    app.evaluate("Export.onDone({ success: false, error: V.error });", { error: HOSTILE[0] });

    const el = app.document.getElementById("export-result");
    assert.equal(el.children.length, 0);
    assert.equal(el.textContent, `Error: ${HOSTILE[0]}`);
  });
});

// ── Extension filter chips ───────────────────────────────────────

const customGroup = (app) => app.document.getElementById("grp-custom");

test("custom extensions restored from saved settings change only text", async () => {
  const render = (app, exts) => {
    app.evaluate("V.exts.forEach(ext => Filters._registerCustomExt(ext)); Filters._renderGroups();", { exts });
    return customGroup(app);
  };

  await withApp(async (hostileApp) => {
    await withApp(async (plainApp) => {
      const hostile = render(hostileApp, HOSTILE_EXTS);
      const plain = render(plainApp, benign(HOSTILE_EXTS.length));

      assertSameStructure(hostile, plain, "custom extensions (restored)");
      assert.deepEqual(
        [...hostile.querySelectorAll(".ext-item")].map((el) => el.dataset.ext),
        HOSTILE_EXTS,
      );
      assert.deepEqual(
        [...hostile.querySelectorAll(".ext-name")].map((el) => el.textContent),
        HOSTILE_EXTS.map((ext) => `.${ext}`),
      );
      assert.deepEqual(
        [...hostile.querySelectorAll(".ext-rm")].map((el) => el.dataset.rm),
        HOSTILE_EXTS,
      );
    });
  });
});

test("custom extensions typed in live change only text", async () => {
  const render = (app, exts) => {
    app.evaluate("Filters._renderGroups(); V.exts.forEach(ext => Filters._addCustomExt(ext));", { exts });
    return customGroup(app);
  };

  await withApp(async (hostileApp) => {
    await withApp(async (plainApp) => {
      const hostile = render(hostileApp, HOSTILE_EXTS);
      const plain = render(plainApp, benign(HOSTILE_EXTS.length));

      assertSameStructure(hostile, plain, "custom extensions (typed)");
      assert.deepEqual(
        [...hostile.querySelectorAll(".ext-item")].map((el) => el.dataset.ext).sort(),
        [...HOSTILE_EXTS].sort(),
      );
    });
  });
});

// ── Scan issues ──────────────────────────────────────────────────

test("scan issues: hostile paths and OS error text are plain text", async () => {
  const show = (app, path, reason) => {
    app.evaluate(
      `ScanIssues.show({
         unreadable: [{ kind: 'file', path: V.path, reason: V.reason }],
         unreadable_count: 1, beyond_depth: 0,
       });`,
      { path, reason },
    );
    return app.document.getElementById("scan-issues");
  };

  await withApp(async (hostileApp) => {
    await withApp(async (plainApp) => {
      const hostile = show(hostileApp, `/drive/${HOSTILE[0]}`, HOSTILE[1]);
      const plain = show(plainApp, "/drive/benign-0.txt", "benign-1.txt");

      assertSameStructure(hostile, plain, "scan issues");
      assert.equal(hostile.querySelector(".scan-issues-path").textContent, `/drive/${HOSTILE[0]}`);
      assert.equal(hostile.querySelector(".scan-issues-path").title, `/drive/${HOSTILE[0]}`);
      assert.equal(hostile.querySelector(".scan-issues-reason").textContent, HOSTILE[1]);
    });
  });
});

// ── The guard itself ─────────────────────────────────────────────

test("guard check: removing escapeHtml makes the structure comparison fail", async () => {
  await withApp(async (hostileApp) => {
    await withApp(async (plainApp) => {
      hostileApp.evaluate("escapeHtml = (value) => String(value ?? '');");

      const hostile = renderTree(hostileApp, HOSTILE, HOSTILE_FOLDER, HOSTILE_NOTE);
      const plain = renderTree(plainApp, benign(HOSTILE.length), "benign-folder", "benign note");

      assert.throws(() => assertSameStructure(hostile, plain, "tree"), /changed the DOM structure/);
    });
  });
});

test("guard check: every HTML-writing statement in the UI is accounted for", () => {
  const known = {
    "app.js": 1,
    "context_menu.js": 1,
    "export.js": 4,
    "filters.js": 5,
    "tree.js": 5,
  };
  const sink = /\.(?:innerHTML|outerHTML)\s*=(?!=)|insertAdjacentHTML\s*\(|document\.write\s*\(/g;

  const found = {};
  for (const file of fs.readdirSync(path.join(uiDir, "js")).filter((f) => f.endsWith(".js")).sort()) {
    const count = (fs.readFileSync(path.join(uiDir, "js", file), "utf8").match(sink) || []).length;
    if (count) found[file] = count;
  }

  assert.deepEqual(
    found,
    known,
    "HTML sink added or removed: cover it in escaping.test.mjs, then update `known` here",
  );
});

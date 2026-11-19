import assert from "node:assert/strict";
import test from "node:test";

import { withApp } from "./helpers.mjs";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const MISSING = { error: "It no longer exists. It may have been moved or deleted." };

async function showResult(app, handlers, saved = ["/out/report.md", "/out/page.html"]) {
  app.window.pywebview = { api: handlers };
  app.window.onExportDone({ success: true, saved, errors: [] });
  await tick();
  const $$ = (selector) => [...app.document.querySelectorAll(selector)];
  return {
    open: (i = 0) => $$("#export-result .export-file-open")[i],
    link: (i = 0) => $$("#export-result .export-file-link")[i],
    reveal: (i = 0) => $$("#export-result .export-file-reveal")[i],
    notes: () => $$("#export-result .export-file-note"),
  };
}

const click = async (el) => {
  el.click();
  await tick();
  await tick();
};

test("opening a file that was moved or deleted says so", async () => {
  await withApp(async (app) => {
    const ui = await showResult(app, { open_path: async () => MISSING });
    await click(ui.open());

    assert.equal(ui.notes().length, 1);
    assert.equal(
      ui.notes()[0].textContent,
      "Could not open report.md. It no longer exists. It may have been moved or deleted.",
    );
    assert.equal(ui.notes()[0].getAttribute("role"), "alert");
    assert.equal(ui.notes()[0].nextElementSibling.className, "export-new-scan-row");
  });
});

test("the file name link reports the same failure", async () => {
  await withApp(async (app) => {
    const ui = await showResult(app, { open_path: async () => MISSING });
    await click(ui.link(1));

    assert.match(ui.notes()[0].textContent, /^Could not open page\.html\./);
  });
});

test("showing a missing file in its folder says so", async () => {
  await withApp(async (app) => {
    const ui = await showResult(app, { reveal_in_explorer: async () => MISSING });
    await click(ui.reveal());

    assert.match(ui.notes()[0].textContent, /^Could not show report\.md in its folder\. It no longer exists/);
  });
});

test("repeated failures keep a single note showing the latest one", async () => {
  await withApp(async (app) => {
    const ui = await showResult(app, { open_path: async () => MISSING });
    await click(ui.open(0));
    await click(ui.open(1));

    assert.equal(ui.notes().length, 1);
    assert.match(ui.notes()[0].textContent, /page\.html/);
  });
});

test("a later success clears the note", async () => {
  await withApp(async (app) => {
    let outcome = MISSING;
    const ui = await showResult(app, { open_path: async () => outcome });
    await click(ui.open());
    assert.equal(ui.notes().length, 1);

    outcome = { ok: true };
    await click(ui.open());
    assert.equal(ui.notes().length, 0);
  });
});

test("a declined launch prompt is not an error", async () => {
  await withApp(async (app) => {
    const ui = await showResult(app, { open_path: async () => ({ cancelled: true }) });
    await click(ui.open());

    assert.equal(ui.notes().length, 0);
  });
});

test("a failing call is reported with its message", async () => {
  await withApp(async (app) => {
    const ui = await showResult(app, { open_path: async () => { throw new Error("boom"); } });
    await click(ui.open());

    assert.match(ui.notes()[0].textContent, /^Could not open report\.md\. .*boom/);
  });
});

test("a hostile file name stays text in the note", async () => {
  await withApp(async (app) => {
    const ui = await showResult(app, { open_path: async () => MISSING }, ["/out/<img src=x onerror=alert(1)>.md"]);
    await click(ui.open());

    assert.equal(ui.notes()[0].querySelector("img"), null);
    assert.match(ui.notes()[0].textContent, /<img src=x onerror=alert\(1\)>\.md/);
  });
});

async function useMenu(app, handlers, action) {
  app.window.pywebview = { api: handlers };
  app.evaluate(
    `ContextMenu.show(10, 10, "/d/notes.txt", "file", { name: "notes.txt", path: "/d/notes.txt" }, Tree);`,
  );
  const item = app.document.querySelector(`.ctx-item[data-action=${action}]`);
  item.click();
  await tick();
  await tick();
  return app.document.getElementById("ctx-toast");
}

test("the context menu reports a file that is gone", async () => {
  await withApp(async (app) => {
    const toast = await useMenu(app, { open_path: async () => MISSING }, "open");

    assert.equal(toast.textContent, "Could not open notes.txt. It no longer exists. It may have been moved or deleted.");
    assert.equal(toast.classList.contains("visible"), true);
    assert.equal(toast.getAttribute("role"), "status");
  });
});

test("the context menu reports a failed show in folder and failed properties", async () => {
  await withApp(async (app) => {
    const folder = await useMenu(app, { reveal_in_explorer: async () => MISSING }, "explorer");
    assert.match(folder.textContent, /^Could not show notes\.txt in its folder\./);

    const props = await useMenu(app, { open_properties: async () => MISSING }, "props");
    assert.match(props.textContent, /^Could not show properties of notes\.txt\./);
  });
});

test("the context menu says nothing when the file opens", async () => {
  await withApp(async (app) => {
    const toast = await useMenu(app, { open_path: async () => ({ ok: true }) }, "open");
    assert.equal(toast, null);
  });
});

test("copy path and copy name do not depend on the file still existing", async () => {
  await withApp(async (app) => {
    const copied = [];
    Object.defineProperty(app.window.navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (text) => copied.push(text) },
    });
    const handlers = { open_path: async () => MISSING };

    await useMenu(app, handlers, "copy-path");
    await useMenu(app, handlers, "copy-name");

    assert.deepEqual(copied, ["/d/notes.txt", "notes.txt"]);
    assert.equal(app.document.getElementById("ctx-toast").textContent, "Copied to clipboard");
  });
});
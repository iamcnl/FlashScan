import assert from "node:assert/strict";
import test from "node:test";

import { withApp } from "./helpers.mjs";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const toastOf = (app) => app.document.getElementById("ctx-toast");
const press = (app) => app.window.dispatchEvent(new app.window.KeyboardEvent("keydown", { key: "Tab" }));

async function clickLink(app, api) {
  app.window.pywebview = { api };
  const link = app.document.createElement("button");
  link.dataset.link = "site";
  app.document.body.append(link);
  link.click();
  await tick();
  await tick();
}

test("a link that cannot be opened says so", async () => {
  await withApp(async (app) => {
    await clickLink(app, { open_external: async () => ({ error: "No web browser could be opened." }) });

    assert.equal(toastOf(app).textContent, "Could not open the link. No web browser could be opened.");
  });
});

test("a link that throws or has no backend gives the generic message", async () => {
  await withApp(async (app) => {
    await clickLink(app, { open_external: async () => { throw new Error("boom"); } });
    assert.equal(toastOf(app).textContent, "Something went wrong. Details are in the log.");
  });
  await withApp(async (app) => {
    await clickLink(app, { open_external: async () => null });
    assert.equal(toastOf(app).textContent, "Something went wrong. Details are in the log.");
  });
});

test("a link that opens shows nothing", async () => {
  await withApp(async (app) => {
    await clickLink(app, { open_external: async () => ({ ok: true }) });

    assert.equal(toastOf(app), null);
  });
});

test("the log icon reports a missing log file and a thrown error", async () => {
  await withApp(async (app) => {
    app.window.pywebview = { api: { open_log_folder: async () => ({ error: "No log file is available." }) } };
    app.document.getElementById("btn-open-log").click();
    await tick();
    await tick();
    assert.equal(toastOf(app).textContent, "Could not open the log folder. No log file is available.");

    app.window.pywebview = { api: { open_log_folder: async () => { throw new Error("boom"); } } };
    app.document.getElementById("btn-open-log").click();
    await tick();
    await tick();
    assert.equal(toastOf(app).textContent, "Something went wrong. Details are in the log.");
  });
});

test("a toast can carry one action, and the next toast drops it", async () => {
  await withApp(async (app) => {
    app.window.__ran = 0;
    app.evaluate("ContextMenu.toast('Saved state reset', 5000, { label: 'undo', run: () => { __ran++; } });");
    const toast = toastOf(app);
    const button = toast.querySelector("button.ctx-toast-action");

    assert.equal(button.textContent, "undo");
    assert.equal(toast.classList.contains("has-action"), true);

    button.click();
    assert.equal(app.window.__ran, 1);
    assert.equal(toast.classList.contains("visible"), false);

    app.evaluate("ContextMenu.toast('Copied to clipboard');");
    assert.equal(toast.querySelector("button"), null);
    assert.equal(toast.classList.contains("has-action"), false);
  });
});

function showNote(app, clipped, mode, tooltip) {
  const label = app.document.getElementById("profile-note-text");
  Object.defineProperty(label, "scrollWidth", { configurable: true, value: clipped ? 200 : 50 });
  Object.defineProperty(label, "clientWidth", { configurable: true, value: 100 });
  app.window.__args = [mode, tooltip];
  app.evaluate("ProfileNote._show(__args[0], 'short', 'undo', 10000, __args[1]);");
}

test("a reset note that does not fit appears as a toast with undo", async () => {
  await withApp(async (app) => {
    app.window.__undone = 0;
    app.evaluate("ProfileNote.undo = () => { __undone++; };");
    showNote(app, true, "reset", "saved state reset for this drive");

    const toast = toastOf(app);
    assert.equal(toast.firstChild.textContent, "saved state reset for this drive");
    toast.querySelector("button").click();
    assert.equal(app.window.__undone, 1);
    app.evaluate("ProfileNote.hide();");
  });
});

test("an undo offered by a toast does nothing once the note is gone", async () => {
  await withApp(async (app) => {
    app.window.__undone = 0;
    app.evaluate("ProfileNote.undo = () => { __undone++; };");
    showNote(app, true, "reset", "saved state reset for this drive");
    app.evaluate("ProfileNote.hide();");

    toastOf(app).querySelector("button").click();

    assert.equal(app.window.__undone, 0);
  });
});

test("other clipped notes are plain toasts, and notes that fit need none", async () => {
  await withApp(async (app) => {
    showNote(app, true, "info", "nothing saved for this drive yet");
    assert.equal(toastOf(app).textContent, "nothing saved for this drive yet");
    assert.equal(toastOf(app).querySelector("button"), null);
    app.evaluate("ProfileNote.hide();");
  });
  await withApp(async (app) => {
    showNote(app, false, "reset", "saved state reset for this drive");
    assert.equal(toastOf(app), null);
    app.evaluate("ProfileNote.hide();");
  });
});

async function runExport(app, reply, outValue = "/out") {
  press(app);
  app.window.__reply = reply;
  app.evaluate(
    `State.reset(V.tree);
     window.pywebview.api = { export: async () => __reply };
     document.querySelectorAll('.fmt-cell').forEach(cell =>
       cell.querySelector('.fmt-input').checked = cell.dataset.fmt === 'MD');
     document.getElementById('out-input').value = V.out;`,
    { tree: [{ lvl: 0, type: "file", name: "a.txt", path: "/a.txt", size: 1, mtime: 0 }], out: outValue },
  );
  await app.evaluate("return Export.doExport();");
}

const outField = (app) => app.document.getElementById("out-input");

test("a refused output folder marks the field and points at the message", async () => {
  await withApp(async (app) => {
    await runExport(app, { success: false, error: "Output folder does not exist.", field: "output_dir" });

    assert.equal(outField(app).getAttribute("aria-invalid"), "true");
    assert.equal(outField(app).getAttribute("aria-describedby"), "export-result");
    assert.equal(app.document.activeElement, outField(app));
    assert.match(app.document.getElementById("export-result").textContent, /Output folder does not exist/);
  });
});

test("an error about something else leaves the field alone", async () => {
  await withApp(async (app) => {
    await runExport(app, { success: false, error: "Scan data is out of date. Run the scan again." });

    assert.equal(outField(app).hasAttribute("aria-invalid"), false);
  });
});

test("an empty output folder is marked too", async () => {
  await withApp(async (app) => {
    await runExport(app, { async: true }, "");

    assert.equal(outField(app).getAttribute("aria-invalid"), "true");
  });
});

test("the mark clears on the next export attempt and when the field is cleared by script", async () => {
  await withApp(async (app) => {
    await runExport(app, { success: false, error: "x", field: "output_dir" });
    await runExport(app, { success: false, error: "Selection is missing." });
    assert.equal(outField(app).hasAttribute("aria-invalid"), false);

    app.evaluate("Export.setOutputInvalid(true); Export.setOutputInvalid(false);");
    assert.equal(outField(app).hasAttribute("aria-describedby"), false);
  });
});
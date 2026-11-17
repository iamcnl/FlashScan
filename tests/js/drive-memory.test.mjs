import assert from "node:assert/strict";
import test from "node:test";

import { withApp } from "./helpers.mjs";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const NOW = Date.now() / 1000;

const DRIVES = [
  { volumeId: "serial:4F2A91C3", label: "Backup USB", notes: 4, folders: 5, excluded: 0, used: NOW },
  { volumeId: "serial:00AA11BB", label: "", notes: 1, folders: 0, excluded: 3, used: NOW - 21 * 86400 },
];

async function openSettings(app, { drives = DRIVES, calls = [] } = {}) {
  let stored = [...drives];
  app.window.pywebview = {
    api: {
      get_profiles: async () => stored,
      delete_profile: async (id) => {
        calls.push(["delete", id]);
        stored = stored.filter((d) => d.volumeId !== id);
      },
      clear_profiles: async () => {
        calls.push(["clear"]);
        stored = [];
      },
      save_settings: () => {},
    },
  };
  app.document.getElementById("btn-open-settings").click();
  await tick();
  const $ = (id) => app.document.getElementById(id);
  return { tab: $("settings-tab-drives"), general: $("settings-panel-general"), panel: $("settings-panel-drives"), $ };
}

const confirmDialog = (app) => app.document.querySelector("[role=alertdialog]");
const confirmWith = async (app, selector) => {
  confirmDialog(app).querySelector(selector).click();
  await tick();
  await tick();
};

test("General is shown first and the tabs switch panels", async () => {
  await withApp(async (app) => {
    const { tab, general, panel, $ } = await openSettings(app);
    assert.equal(general.hidden, false);
    assert.equal(panel.hidden, true);
    assert.equal($("settings-tab-general").getAttribute("aria-selected"), "true");

    tab.click();
    assert.equal(general.hidden, true);
    assert.equal(panel.hidden, false);
    assert.equal(tab.getAttribute("aria-selected"), "true");
    assert.equal(tab.tabIndex, 0);
    assert.equal($("settings-tab-general").tabIndex, -1);
  });
});

test("arrow keys move between the tabs", async () => {
  await withApp(async (app) => {
    const { tab, general, panel, $ } = await openSettings(app);
    const press = (key) => app.window.dispatchEvent(
      new app.window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
    );
    $("settings-tab-general").focus();

    press("ArrowRight");
    assert.equal(app.document.activeElement, tab);
    assert.equal(panel.hidden, false);

    press("ArrowLeft");
    assert.equal(app.document.activeElement, $("settings-tab-general"));
    assert.equal(general.hidden, false);
  });
});

test("the tab shows how many drives are remembered", async () => {
  await withApp(async (app) => {
    const { tab } = await openSettings(app);
    assert.equal(tab.textContent.trim(), "Drive memory 2");
  });
});

test("each drive is listed with its name, contents and last use", async () => {
  await withApp(async (app) => {
    const { panel } = await openSettings(app);
    const rows = [...panel.querySelectorAll(".drive-item")];

    assert.equal(rows.length, 2);
    assert.equal(rows[0].querySelector(".drive-name").textContent, "Backup USB");
    assert.equal(rows[0].querySelector(".drive-meta").textContent, "4 notes \u00B7 5 folder states \u00B7 scanned today");
    assert.equal(rows[1].querySelector(".drive-name").textContent, "Unnamed drive (ID 00AA11BB)");
    assert.equal(rows[1].querySelector(".drive-meta").textContent, "1 note \u00B7 3 excluded files \u00B7 scanned 3 weeks ago");
  });
});

test("each drive has an icon-only forget button with a name and a hover label", async () => {
  await withApp(async (app) => {
    const { panel } = await openSettings(app);
    const buttons = [...panel.querySelectorAll(".drive-forget")];

    assert.equal(buttons.length, 2);
    assert.equal(buttons[0].textContent, "");
    assert.equal(buttons[0].getAttribute("aria-label"), "Forget Backup USB");
    assert.equal(buttons[1].getAttribute("aria-label"), "Forget Unnamed drive (ID 00AA11BB)");
    assert.equal(buttons[0].dataset.tip, "Forget this drive");
    assert.equal(buttons[0].querySelector("svg").getAttribute("aria-hidden"), "true");
  });
});

test("the button for all drives says forget, not clear", async () => {
  await withApp(async (app) => {
    const { panel } = await openSettings(app);
    const button = panel.querySelector(".modal-actions .btn");
    assert.equal(button.textContent, "Forget all\u2026");

    button.click();
    await tick();
    assert.match(confirmDialog(app).textContent, /Forget all drives\?/);
    assert.equal(confirmDialog(app).querySelector(".btn-danger").textContent, "Forget all");
  });
});

test("a hostile drive label is shown as text", async () => {
  await withApp(async (app) => {
    const hostile = { volumeId: "serial:1", label: "<img src=x onerror=alert(1)>", notes: 1, folders: 0, excluded: 0, used: NOW };
    const { panel } = await openSettings(app, { drives: [hostile] });

    assert.equal(panel.querySelector("img"), null);
    assert.equal(panel.querySelector(".drive-name").textContent, hostile.label);
  });
});

test("with nothing saved the list is replaced by a message", async () => {
  await withApp(async (app) => {
    const { tab, panel } = await openSettings(app, { drives: [] });
    assert.equal(tab.textContent.trim(), "Drive memory");
    assert.equal(panel.querySelector(".drive-list").hidden, true);
    assert.equal(panel.querySelector(".modal-actions").hidden, true);
    assert.match(panel.textContent, /No drives remembered yet/);
  });
});

test("an unreadable list is shown as nothing saved", async () => {
  await withApp(async (app) => {
    app.window.pywebview = { api: { get_profiles: async () => { throw new Error("boom"); }, save_settings() {} } };
    app.document.getElementById("btn-open-settings").click();
    await tick();
    const panel = app.document.getElementById("settings-panel-drives");
    assert.equal(panel.querySelector(".drive-list").hidden, true);
  });
});

test("forgetting one drive asks first and removes only that drive", async () => {
  await withApp(async (app) => {
    const calls = [];
    const { panel } = await openSettings(app, { calls });
    panel.querySelectorAll(".drive-forget")[0].click();
    await tick();

    assert.match(confirmDialog(app).textContent, /Forget Backup USB\?/);
    await confirmWith(app, ".btn-danger");

    assert.deepEqual(calls, [["delete", "serial:4F2A91C3"]]);
    assert.equal(panel.querySelectorAll(".drive-item").length, 1);
    assert.equal(app.document.getElementById("settings-tab-drives").textContent.trim(), "Drive memory 1");
  });
});

test("cancelling keeps the drive", async () => {
  await withApp(async (app) => {
    const calls = [];
    const { panel } = await openSettings(app, { calls });
    panel.querySelectorAll(".drive-forget")[0].click();
    await tick();
    await confirmWith(app, ".btn-secondary");

    assert.deepEqual(calls, []);
    assert.equal(panel.querySelectorAll(".drive-item").length, 2);
  });
});

test("clearing all asks first and empties the list", async () => {
  await withApp(async (app) => {
    const calls = [];
    const { panel } = await openSettings(app, { calls });
    panel.querySelector(".modal-actions .btn").click();
    await tick();

    assert.match(confirmDialog(app).textContent, /all 2 drives/);
    await confirmWith(app, ".btn-danger");

    assert.deepEqual(calls, [["clear"]]);
    assert.equal(panel.querySelector(".drive-list").hidden, true);
    assert.match(panel.textContent, /No drives remembered yet/);
  });
});

const openDrive = (app, id) => app.evaluate(
  `Object.defineProperty(Persist, "active", { get: () => true });
   Object.defineProperty(Persist, "volumeId", { get: () => ${JSON.stringify(id)} });
   window.resets = 0;
   Persist.reset = () => { window.resets += 1; return {}; };
   Tree.invalidate = () => {};
   Tree.render = () => {};`,
);

test("forgetting the open drive resets it so its state is not written back", async () => {
  await withApp(async (app) => {
    const { panel } = await openSettings(app);
    openDrive(app, "serial:4F2A91C3");
    panel.querySelectorAll(".drive-forget")[0].click();
    await tick();

    assert.match(confirmDialog(app).textContent, /reset as well/);
    await confirmWith(app, ".btn-danger");
    assert.equal(app.window.resets, 1);
  });
});

test("forgetting another drive leaves the open one alone", async () => {
  await withApp(async (app) => {
    const { panel } = await openSettings(app);
    openDrive(app, "serial:4F2A91C3");
    panel.querySelectorAll(".drive-forget")[1].click();
    await tick();

    assert.doesNotMatch(confirmDialog(app).textContent, /reset as well/);
    await confirmWith(app, ".btn-danger");
    assert.equal(app.window.resets, 0);
  });
});

test("clearing all also resets the open drive", async () => {
  await withApp(async (app) => {
    const { panel } = await openSettings(app);
    openDrive(app, "serial:4F2A91C3");
    panel.querySelector(".modal-actions .btn").click();
    await tick();
    await confirmWith(app, ".btn-danger");

    assert.equal(app.window.resets, 1);
  });
});

test("last use is described in days, weeks and months", async () => {
  await withApp(async (app) => {
    const ago = (days) => app.evaluate(
      `return SettingsDialog._ago(${NOW} - ${days} * 86400, ${NOW * 1000});`,
    );
    assert.equal(ago(0), "today");
    assert.equal(ago(1), "yesterday");
    assert.equal(ago(5), "5 days ago");
    assert.equal(ago(21), "3 weeks ago");
    assert.equal(ago(95), "3 months ago");
    assert.equal(ago(-2), "today");
  });
});

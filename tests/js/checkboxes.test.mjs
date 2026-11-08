import assert from "node:assert/strict";
import test from "node:test";

import { withApp } from "./helpers.mjs";

async function booted(fn) {
  await withApp(async (app) => {
    app.evaluate(
      `window.saved = [];
       window.pywebview.api = { save_settings: async (s) => { window.saved.push(s); } };
       Tree.invalidate = () => {};
       Tree.render = () => {};
       Filters._scheduleRender = () => {};
       Object.values(ALL_EXTENSIONS).forEach(exts => exts.forEach(e => { Filters._extState[e] = true; }));
       initCheckbox('cb-hidden', 'inclHidden');
       initCheckbox('cb-system', 'inclSystem');
       initFmtGrid();
       Export.init();
       Filters._renderGroups();`,
    );
    await fn(app);
  });
}

const $ = (app, selector) => app.document.querySelector(selector);
const formats = (app) => JSON.parse(app.evaluate("return JSON.stringify(Export._selectedFormats());"));
const saved = (app) => JSON.parse(app.evaluate("return JSON.stringify(window.saved);"));
const group = (app, name) => $(app, `[data-gcb="${name}"]`);
const ext = (app, name, inGroup) =>
  [...app.document.querySelectorAll(`[data-ecb="${name}"]`)][inGroup ?? 0];

test("checkboxes: every custom box is drawn from a real, tabbable checkbox", async () => {
  await booted((app) => {
    const boxes = [...app.document.querySelectorAll(".cb, .gcb, .ecb")];
    assert.ok(boxes.length > 100);
    for (const box of boxes) {
      const input = box.previousElementSibling;
      assert.ok(input?.matches('input[type="checkbox"]'), `${box.className} has no checkbox in front of it`);
      assert.equal(input.tabIndex, 0);
    }
    for (const tile of app.document.querySelectorAll(".fmt-cell")) {
      assert.equal(tile.querySelector(".fmt-input").type, "checkbox");
    }
  });
});

test("scan options: toggling the box or its label flips the setting once and saves it", async () => {
  await booted((app) => {
    const box = $(app, "#cb-hidden");
    assert.equal(box.checked, false);

    box.click();
    assert.equal(box.checked, true);
    assert.equal(app.evaluate("return State.settings.inclHidden;"), true);

    box.closest("label").click();
    assert.equal(box.checked, false);
    assert.deepEqual(saved(app), [{ inclHidden: true }, { inclHidden: false }]);

    app.evaluate("setCheckbox('cb-system', true);");
    assert.equal($(app, "#cb-system").checked, true);
  });
});

test("export options: they restore from settings, save on change and feed the export", async () => {
  await booted((app) => {
    app.evaluate("Export.applyOptions({ exportIncludeSize: false });");
    assert.deepEqual(JSON.parse(app.evaluate("return JSON.stringify(Export._advOptions());")), {
      include_size: false,
      include_date: true,
    });

    $(app, "#chk-include-date").click();
    assert.deepEqual(saved(app), [{ exportIncludeDate: false }]);
    assert.equal(app.evaluate("return Export._advOptions().include_date;"), false);
  });
});

test("format tiles: the input is the state and the tile styling follows it", async () => {
  await booted((app) => {
    const tile = (fmt) => $(app, `.fmt-cell[data-fmt="${fmt}"]`);
    assert.ok(tile("MD").classList.contains("selected"));
    assert.deepEqual(formats(app), ["MD"]);

    tile("HTML").querySelector(".fmt-input").click();
    assert.ok(tile("HTML").classList.contains("selected"));
    assert.ok(tile("HTML").querySelector(".fmt-dot").classList.contains("on"));
    assert.deepEqual(formats(app), ["MD", "HTML"]);
    assert.deepEqual(saved(app).at(-1), { lastFormats: ["MD", "HTML"] });

    tile("MD").querySelector(".fmt-input").click();
    assert.equal(tile("MD").classList.contains("selected"), false);
    assert.deepEqual(formats(app), ["HTML"]);
  });
});

test("extension filter: a group box is tri-state and a partial group switches fully on", async () => {
  await booted((app) => {
    const images = group(app, "Images");
    const body = app.document.getElementById(images.closest(".grp").querySelector(".grp-arrow").getAttribute("aria-controls"));
    assert.equal(images.checked, true);
    assert.equal(images.indeterminate, false);

    ext(app, "jpg").click();
    assert.equal(app.evaluate("return Filters._extState.jpg;"), false);
    assert.equal(images.checked, false);
    assert.equal(images.indeterminate, true);

    images.click();
    assert.equal(images.indeterminate, false);
    assert.equal(images.checked, true);
    assert.equal(ext(app, "jpg").checked, true);
    assert.equal(body.classList.contains("open"), false, "ticking a group box must not open the group");

    images.click();
    assert.equal(ext(app, "png").checked, false);
    assert.equal(app.evaluate("return Filters._extState.png;"), false);
  });
});

test("extension filter: an extension listed in two groups stays in step in both", async () => {
  await booted((app) => {
    assert.equal(app.document.querySelectorAll('[data-ecb="ts"]').length, 2);

    ext(app, "ts", 0).click();
    assert.equal(ext(app, "ts", 0).checked, false);
    assert.equal(ext(app, "ts", 1).checked, false);
    assert.equal(group(app, "Video").indeterminate, true);
    assert.equal(group(app, "Code").indeterminate, true);

    ext(app, "ts", 1).click();
    assert.equal(ext(app, "ts", 0).checked, true);
    assert.equal(ext(app, "ts", 1).checked, true);
    assert.equal(group(app, "Video").indeterminate, false);
    assert.equal(group(app, "Code").indeterminate, false);
  });
});

test("extension filter: select all and none reset every box", async () => {
  await booted((app) => {
    ext(app, "jpg").click();
    app.evaluate("Filters.deselectNone();");
    assert.ok([...app.document.querySelectorAll("[data-ecb], [data-gcb]")].every((el) => !el.checked));

    app.evaluate("Filters.selectAll();");
    assert.ok([...app.document.querySelectorAll("[data-ecb], [data-gcb]")].every((el) => el.checked));
    assert.ok([...app.document.querySelectorAll("[data-gcb]")].every((el) => !el.indeterminate));
  });
});

test("extension filter: groups open from a keyboard-operable button and custom extensions can be removed", async () => {
  await booted((app) => {
    const header = $(app, '[data-group="Fonts"]');
    const arrow = header.querySelector(".grp-arrow");
    const body = app.document.getElementById(arrow.getAttribute("aria-controls"));
    assert.equal(arrow.tagName, "BUTTON");
    assert.equal(arrow.getAttribute("aria-expanded"), "false");

    arrow.click();
    assert.equal(arrow.getAttribute("aria-expanded"), "true");
    assert.ok(body.classList.contains("open"));
    arrow.click();
    assert.equal(arrow.getAttribute("aria-expanded"), "false");

    app.evaluate("Filters._addCustomExt('xyz');");
    const remove = $(app, '[data-ext="xyz"] .ext-rm');
    assert.equal(remove.tagName, "BUTTON");
    assert.equal(remove.getAttribute("aria-label"), "Remove .xyz");
    remove.click();
    assert.equal($(app, '[data-ext="xyz"]'), null);
  });
});

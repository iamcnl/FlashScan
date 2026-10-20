import assert from "node:assert/strict";
import test from "node:test";

import { mount, withApp } from "./helpers.mjs";

const STAMP = new Date(2024, 2, 5, 12, 0).getTime() / 1000;
const LAYOUT = /^(?:%[dmY]|[^%\x00-\x1f]){3,32}$/;

const formatWith = (app, mode) =>
  app.evaluate(`DateFmt.setMode(V.mode); return DateFmt.format(V.ts);`, { mode, ts: STAMP });

test("fixed formats are zero-padded and an empty timestamp stays empty", async () => {
  await withApp(async (app) => {
    assert.equal(formatWith(app, "dmy"), "05. 03. 2024");
    assert.equal(formatWith(app, "mdy"), "03/05/2024");
    assert.equal(formatWith(app, "iso"), "2024-03-05");
    assert.equal(app.evaluate(`return DateFmt.format(0)`), "");
  });
});

test("an unknown saved mode falls back to the system default", async () => {
  await withApp(async (app) => {
    assert.equal(app.evaluate(`DateFmt.setMode("nonsense"); return DateFmt.mode`), "system");
    assert.equal(app.evaluate(`DateFmt.setMode(undefined); return DateFmt.mode`), "system");
  });
});

test("the system format follows the browser locale", async () => {
  await withApp(async (app) => {
    app.evaluate(`DateFmt._systemPattern = null; DateFmt.setMode("system");`);
    assert.equal(app.evaluate(`return navigator.language`), "en-US");
    assert.equal(app.evaluate(`return DateFmt.pattern()`), "%m/%d/%Y");
  });
});

test("locale layouts keep each locale's order and separators", async () => {
  await withApp(async (app) => {
    const pattern = (locale) => app.evaluate(`return DateFmt.patternForLocale(V.locale)`, { locale });

    assert.equal(pattern("cs-CZ"), "%d. %m. %Y");
    assert.equal(pattern("de-DE"), "%d.%m.%Y");
    assert.equal(pattern("en-GB"), "%d/%m/%Y");
    assert.equal(pattern("en-US"), "%m/%d/%Y");
    assert.equal(pattern("ja-JP"), "%Y/%m/%d");
    assert.equal(pattern("sv-SE"), "%Y-%m-%d");
  });
});

test("every locale layout is one Python's strftime can reproduce", async () => {
  await withApp(async (app) => {
    const locales = [
      "en-US", "en-GB", "cs-CZ", "de-DE", "fr-FR", "ja-JP", "ko-KR", "zh-CN",
      "hu-HU", "lt-LT", "ar-EG", "fa-IR", "th-TH", "he-IL", "ru-RU", "sv-SE",
    ];
    for (const locale of locales) {
      const pattern = app.evaluate(`return DateFmt.patternForLocale(V.locale)`, { locale });
      assert.match(pattern, LAYOUT, locale);
      for (const directive of ["%d", "%m", "%Y"]) {
        assert.equal(pattern.split(directive).length - 1, 1, `${locale}: ${directive} in ${pattern}`);
      }
    }
  });
});

test("an unusable locale falls back to ISO", async () => {
  await withApp(async (app) => {
    assert.equal(app.evaluate(`return DateFmt.patternForLocale("not a locale!!")`), "%Y-%m-%d");
    assert.equal(app.evaluate(`return DateFmt.patternForLocale(undefined)`), "%Y-%m-%d");
  });
});

function openSettings(app) {
  app.document.getElementById("btn-open-settings").click();
  return app.document.getElementById("settings-date-format");
}

test("settings dialog saves the chosen format and updates the preview", async () => {
  await withApp(async (app) => {
    const saved = [];
    app.window.pywebview = { api: { save_settings: (data) => saved.push(data) } };

    const select = openSettings(app);
    assert.equal(select.value, "system");

    select.value = "iso";
    select.dispatchEvent(new app.window.Event("change"));

    assert.equal(app.evaluate(`return DateFmt.mode`), "iso");
    assert.equal(JSON.stringify(saved), JSON.stringify([{ dateFormat: "iso" }]));
    assert.match(app.document.querySelector(".modal-text").textContent, /\d{4}-\d{2}-\d{2}/);
  });
});

test("settings dialog closes with the button, Escape and a click outside", async () => {
  await withApp(async (app) => {
    const isOpen = () => app.document.getElementById("settings-date-format") !== null;

    openSettings(app);
    app.document.querySelector(".modal .btn").click();
    assert.equal(isOpen(), false);

    openSettings(app);
    app.window.dispatchEvent(new app.window.KeyboardEvent("keydown", { key: "Escape" }));
    assert.equal(isOpen(), false);

    openSettings(app);
    app.document.querySelector(".modal-backdrop").dispatchEvent(
      new app.window.MouseEvent("mousedown", { bubbles: true }),
    );
    assert.equal(isOpen(), false);
  });
});

test("opening settings twice shows one dialog", async () => {
  await withApp(async (app) => {
    openSettings(app);
    openSettings(app);
    assert.equal(app.document.querySelectorAll(".modal").length, 1);
  });
});

test("changing the format redraws the dates in the file list", async () => {
  await withApp(async (app) => {
    app.window.pywebview = { api: { save_settings() {} } };
    const host = mount(app);
    app.evaluate(
      `State.reset(V.data); Tree.init(__host); Tree.render();`,
      {
        data: [
          { lvl: 0, type: "folder", name: "drive", path: "/drive", size: 10, mtime: 0 },
          { lvl: 1, type: "file", name: "a.txt", path: "/drive/a.txt", size: 10, mtime: STAMP },
        ],
      },
    );

    const select = openSettings(app);
    select.value = "iso";
    select.dispatchEvent(new app.window.Event("change"));

    assert.match(host.textContent, /2024-03-05/);
  });
});

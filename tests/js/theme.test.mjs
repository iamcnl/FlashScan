import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import { uiDir, withApp } from "./helpers.mjs";

const BOOT = fs.readFileSync(path.join(uiDir, "js", "boot.js"), "utf8");

const systemIs = (app, dark) => {
  app.window.matchMedia = () => ({ matches: dark, addEventListener() {}, removeEventListener() {} });
};
const isDark = (app) => app.document.documentElement.dataset.theme === "dark";
const moonShown = (app) => app.document.getElementById("icon-moon").style.display === "";

test("light and dark ignore the system setting", async () => {
  await withApp(async (app) => {
    systemIs(app, true);
    app.evaluate(`Theme.set("light");`);
    assert.equal(isDark(app), false);

    systemIs(app, false);
    app.evaluate(`Theme.set("dark");`);
    assert.equal(isDark(app), true);
    assert.equal(moonShown(app), true);
  });
});

test("system follows the operating system and its live changes", async () => {
  await withApp(async (app) => {
    systemIs(app, true);
    app.evaluate(`Theme.set("system");`);
    assert.equal(isDark(app), true);

    systemIs(app, false);
    app.evaluate(`Theme._onSystemChange();`);
    assert.equal(isDark(app), false);
    assert.equal(moonShown(app), false);
  });
});

test("a system change is ignored while the theme is set explicitly", async () => {
  await withApp(async (app) => {
    app.evaluate(`Theme.set("light");`);
    systemIs(app, true);
    app.evaluate(`Theme._onSystemChange();`);
    assert.equal(isDark(app), false);
  });
});

test("an unknown saved theme falls back to light", async () => {
  await withApp(async (app) => {
    assert.equal(app.evaluate(`Theme.set("nonsense"); return Theme.mode;`), "light");
    assert.equal(app.evaluate(`Theme.set(undefined); return Theme.mode;`), "light");
  });
});

test("the title bar button switches the shown theme and saves an explicit choice", async () => {
  await withApp(async (app) => {
    const saved = [];
    app.window.pywebview = { api: { save_settings: (data) => saved.push(data) } };
    systemIs(app, true);
    app.evaluate(`Theme.set("system");`);

    app.document.getElementById("btn-theme-toggle").click();
    assert.equal(isDark(app), false);
    assert.equal(app.evaluate(`return Theme.mode;`), "light");

    app.document.getElementById("btn-theme-toggle").click();
    assert.equal(isDark(app), true);
    assert.equal(JSON.stringify(saved), JSON.stringify([{ theme: "light" }, { theme: "dark" }]));
  });
});

test("the settings dialog offers the three modes and saves the choice", async () => {
  await withApp(async (app) => {
    const saved = [];
    app.window.pywebview = { api: { save_settings: (data) => saved.push(data) } };
    systemIs(app, true);

    app.document.getElementById("btn-open-settings").click();
    const select = app.document.getElementById("settings-theme");
    assert.deepEqual([...select.options].map((o) => o.value), ["light", "dark", "system"]);
    assert.equal(select.value, "light");

    select.value = "system";
    select.dispatchEvent(new app.window.Event("change"));

    assert.equal(isDark(app), true);
    assert.equal(JSON.stringify(saved), JSON.stringify([{ theme: "system" }]));
  });
});

test("the stored mode is applied by the script in the head", async () => {
  await withApp(async (app) => {
    const run = (mode, dark) => {
      systemIs(app, dark);
      delete app.document.documentElement.dataset.theme;
      app.window.localStorage.setItem("flashscan-theme", mode);
      app.evaluate(BOOT);
      return isDark(app);
    };
    assert.equal(run("dark", false), true);
    assert.equal(run("light", true), false);
    assert.equal(run("system", true), true);
    assert.equal(run("system", false), false);
  });
});

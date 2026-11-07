import assert from "node:assert/strict";
import test from "node:test";

import { withApp } from "./helpers.mjs";

const HINT = "Scan a folder first";

async function freshApp(fn) {
  await withApp(async (app) => {
    app.evaluate("initSteps(); Nav.go(0);");
    await fn(app);
  });
}

const step = (app, n) => app.document.getElementById(`step-${n}`);

function press(app, n, key) {
  app.evaluate(
    `document.getElementById('step-' + V.n).dispatchEvent(
       new KeyboardEvent('keydown', { key: V.key, bubbles: true, cancelable: true }));`,
    { n, key },
  );
}

const current = (app) => app.evaluate("return Nav._current;");

test("steps: before a scan only the first step is reachable", async () => {
  await freshApp((app) => {
    assert.equal(step(app, 0).hasAttribute("aria-disabled"), false);
    for (const n of [1, 2]) {
      assert.equal(step(app, n).getAttribute("aria-disabled"), "true");
      assert.equal(step(app, n).title, HINT);
    }
  });
});

test("steps: they are keyboard-reachable buttons and the active one is marked current", async () => {
  await freshApp((app) => {
    for (const n of [0, 1, 2]) {
      assert.equal(step(app, n).getAttribute("role"), "button");
      assert.equal(step(app, n).getAttribute("tabindex"), "0");
    }
    assert.equal(step(app, 0).getAttribute("aria-current"), "step");
    assert.equal(step(app, 1).hasAttribute("aria-current"), false);
  });
});

test("steps: clicking or pressing a locked step does nothing", async () => {
  await freshApp((app) => {
    step(app, 2).click();
    press(app, 2, "Enter");
    press(app, 1, " ");

    assert.equal(current(app), 0);
    assert.ok(!app.document.querySelectorAll(".screen")[2].classList.contains("active"));
  });
});

test("steps: a scan unlocks them and clears the hint", async () => {
  await freshApp((app) => {
    app.evaluate("Nav.unlock(2); Nav.go(1);");

    for (const n of [0, 1, 2]) {
      assert.equal(step(app, n).hasAttribute("aria-disabled"), false);
      assert.equal(step(app, n).hasAttribute("title"), false);
    }
    assert.equal(step(app, 1).getAttribute("aria-current"), "step");
    assert.equal(step(app, 0).hasAttribute("aria-current"), false);
  });
});

test("steps: unlocking alone is enough to update them", async () => {
  await freshApp((app) => {
    app.evaluate("Nav.unlock(2);");

    assert.equal(step(app, 2).hasAttribute("aria-disabled"), false);
    assert.equal(current(app), 0);
  });
});

test("steps: an unlocked step opens with a click or with Enter and Space", async () => {
  await freshApp((app) => {
    app.evaluate("Nav.unlock(2);");

    step(app, 1).click();
    assert.equal(current(app), 1);
    press(app, 2, "Enter");
    assert.equal(current(app), 2);
    press(app, 0, " ");
    assert.equal(current(app), 0);
    press(app, 1, "a");
    assert.equal(current(app), 0);
  });
});

test("steps: starting a new scan locks them again", async () => {
  await freshApp((app) => {
    app.evaluate("Nav.unlock(2); Nav.go(2); Nav.reset();");

    assert.equal(current(app), 0);
    for (const n of [1, 2]) {
      assert.equal(step(app, n).getAttribute("aria-disabled"), "true");
      assert.equal(step(app, n).title, HINT);
    }
  });
});

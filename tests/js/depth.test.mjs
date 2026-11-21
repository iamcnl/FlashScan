import assert from "node:assert/strict";
import test from "node:test";

import { withApp } from "./helpers.mjs";

const parse = (app, raw) => app.evaluate("return parseDepth(V.raw);", { raw });

test("parseDepth: accepts plain whole numbers from 1 to 50", async () => {
  await withApp(async (app) => {
    assert.equal(parse(app, "1"), 1);
    assert.equal(parse(app, "50"), 50);
    assert.equal(parse(app, " 12 "), 12);
    assert.equal(parse(app, "007"), 7);
  });
});

test("parseDepth: rejects what parseInt used to bend into a number", async () => {
  await withApp(async (app) => {
    for (const raw of ["1e1", "5.5", "10abc", "-3", "0", "51", "abc", "", "  ", null, undefined]) {
      assert.equal(parse(app, raw), null, `${raw}`);
    }
  });
});

async function scanWith(app, depth) {
  app.window.__sent = [];
  app.evaluate(
    `window.pywebview.api = { scan: async (params) => { __sent.push(params.depth); return { busy: true }; } };
     document.getElementById('path-input').value = 'D:\\\\';
     document.getElementById('depth-input').value = V.depth;
     startScan();`,
    { depth },
  );
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test("scan: a depth that is not a whole number is refused before the backend is called", async () => {
  for (const depth of ["5.5", "1e1", "10abc"]) {
    await withApp(async (app) => {
      await scanWith(app, depth);

      assert.deepEqual(app.window.__sent, [], depth);
      assert.match(app.document.getElementById("scan-path-error").textContent, /Depth must be a whole number between 1 and 50\./);
      assert.equal(app.document.getElementById("depth-input").getAttribute("aria-invalid"), "true");
    });
  }
});

test("scan: a valid depth is sent as a number", async () => {
  await withApp(async (app) => {
    await scanWith(app, "12");

    assert.deepEqual(app.window.__sent, [12]);
  });
});

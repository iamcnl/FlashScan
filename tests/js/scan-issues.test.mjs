import assert from "node:assert/strict";
import test from "node:test";

import { HOSTILE, assertSameStructure, withApp } from "./helpers.mjs";

const NONE = { unreadable: [], unreadable_count: 0, links: [], links_skipped: 0, beyond_depth: 0 };

function show(app, result) {
  app.evaluate("ScanIssues.show(V);", { ...NONE, ...result });
  return app.document.getElementById("scan-issues");
}

const text = (box) => box.querySelector("#scan-issues-text").textContent;
const rows = (box) => [...box.querySelectorAll("#scan-issues-list li")];
const hidden = (box) => box.style.display === "none";

test("links: the banner counts them and lists path and target", async () => {
  await withApp(async (app) => {
    const box = show(app, {
      links: [
        { path: "/d/alias", kind: "folder", target: "/d/real" },
        { path: "/d/copy.txt", kind: "file", target: "../x.txt" },
      ],
      links_skipped: 2,
    });

    assert.equal(hidden(box), false);
    assert.equal(text(box), "2 links not followed");
    const [first, second] = rows(box);
    assert.equal(first.querySelector(".scan-issues-kind").textContent, "folder link not followed");
    assert.equal(first.querySelector(".scan-issues-path").textContent, "/d/alias");
    assert.equal(first.querySelector(".scan-issues-reason").textContent, "\u2192 /d/real");
    assert.equal(second.querySelector(".scan-issues-kind").textContent, "file link not followed");
    assert.notEqual(box.querySelector("#scan-issues-toggle").style.display, "none");
  });
});

test("links: a single link is singular and a link without a target has no arrow", async () => {
  await withApp(async (app) => {
    const box = show(app, { links: [{ path: "/d/j", kind: "folder", target: "" }], links_skipped: 1 });

    assert.equal(text(box), "1 link not followed");
    assert.equal(rows(box)[0].querySelector(".scan-issues-reason").textContent, "");
  });
});

test("links: entries missing from the capped lists are summarised together", async () => {
  await withApp(async (app) => {
    const box = show(app, {
      unreadable: [{ kind: "file", path: "/d/a", reason: "Permission denied" }],
      unreadable_count: 3,
      links: [
        { path: "/d/l1", kind: "file", target: "t" },
        { path: "/d/l2", kind: "file", target: "t" },
      ],
      links_skipped: 5,
    });

    const items = rows(box);
    assert.equal(items.length, 4);
    assert.equal(items.at(-1).textContent, "\u2026 and 5 more");
  });
});

test("links: they join the other issues in one line", async () => {
  await withApp(async (app) => {
    const box = show(app, {
      unreadable: [{ kind: "file", path: "/d/a", reason: "x" }],
      unreadable_count: 1,
      links: [{ path: "/d/l", kind: "file", target: "t" }],
      links_skipped: 1,
      beyond_depth: 2,
      depth: 3,
    });

    assert.equal(
      text(box),
      "1 item couldn\u2019t be read \u00B7 1 link not followed \u00B7 " +
        "2 folders below the depth limit (3) weren\u2019t scanned",
    );
  });
});

test("links: a scan without any issue hides the banner again", async () => {
  await withApp(async (app) => {
    show(app, { links: [{ path: "/d/l", kind: "file", target: "t" }], links_skipped: 1 });
    const box = show(app, {});

    assert.equal(hidden(box), true);
  });
});

test("links: hostile paths and targets are plain text", async () => {
  const link = (path, target) => ({ links: [{ path, kind: "folder", target }], links_skipped: 1 });

  await withApp(async (hostileApp) => {
    await withApp(async (plainApp) => {
      const hostile = show(hostileApp, link(`/d/${HOSTILE[0]}`, `/d/${HOSTILE[1]}`));
      const plain = show(plainApp, link("/d/benign-0.txt", "/d/benign-1.txt"));

      assertSameStructure(hostile, plain, "link rows");
      const row = rows(hostile)[0];
      assert.equal(row.querySelector(".scan-issues-path").textContent, `/d/${HOSTILE[0]}`);
      assert.equal(row.querySelector(".scan-issues-reason").textContent, `\u2192 /d/${HOSTILE[1]}`);
    });
  });
});

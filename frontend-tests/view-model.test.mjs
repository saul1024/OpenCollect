import assert from "node:assert/strict";

import {
  createViewState,
  createBatchImportPlan,
  extractUrls,
  getAvailableTags,
  getCollectionView,
  getMediaAspectRatio,
  parseTags,
  normalizeImportDataFile,
  sortNotes
} from "../public/view-model.js";
import { readCookie, withRequestSecurity } from "../public/request-security.js";

const notes = [
  note({
    id: "video-1",
    type: "video",
    platform: "xiaohongshu",
    title: "vivo手机 5大隐藏功能",
    content: "不懂就问有问必答",
    author: "有信",
    tags: ["数码", "vivo"],
    collectedAt: "2026-06-02T02:22:47Z",
    sourceCreatedAt: "2023-04-29T17:11:23Z"
  }),
  note({
    id: "food-1",
    type: "normal",
    platform: "rednote",
    title: "牛肉蘸料再发一遍",
    content: "我要向全世界安利这个做法 🔥",
    author: "米其林三星吃货",
    tags: ["美食", "做法"],
    collectedAt: "2026-06-01T10:00:00Z",
    sourceCreatedAt: "2024-01-02T08:00:00Z"
  }),
  note({
    id: "dessert-1",
    type: "normal",
    platform: "xiaohongshu",
    title: "黑芝麻糊",
    content: "这是我吃过最好吃的配方",
    author: "Blue",
    tags: ["美食", "甜品"],
    collectedAt: "2026-05-30T10:00:00Z",
    sourceCreatedAt: ""
  })
];

assert.deepEqual(parseTags("#美食 美食，甜品[话题]、#vivo#  "), ["美食", "甜品", "vivo"]);
assert.deepEqual(getAvailableTags(notes), ["美食", "数码", "甜品", "做法", "vivo"]);

{
  const view = getCollectionView(notes, createViewState({ query: "  vivo  " }));
  assert.equal(view.visible, 1);
  assert.equal(view.items[0].id, "video-1");
}

{
  const view = getCollectionView(notes, createViewState({ query: "世界 🔥" }));
  assert.equal(view.visible, 1);
  assert.equal(view.items[0].id, "food-1");
}

{
  const view = getCollectionView(notes, createViewState({ query: "blue", tag: "美食", type: "normal", platform: "xiaohongshu" }));
  assert.equal(view.visible, 1);
  assert.equal(view.items[0].id, "dessert-1");
}

{
  const view = getCollectionView(notes, createViewState({ type: "video" }));
  assert.deepEqual(view.items.map((item) => item.id), ["video-1"]);
}

{
  const view = getCollectionView(notes, createViewState({ tag: "美食" }));
  assert.deepEqual(view.items.map((item) => item.id), ["food-1", "dessert-1"]);
}

assert.deepEqual(sortNotes(notes, "collected-asc").map((item) => item.id), ["dessert-1", "food-1", "video-1"]);
assert.deepEqual(sortNotes(notes, "source-desc").map((item) => item.id), ["food-1", "video-1", "dessert-1"]);

assert.equal(getMediaAspectRatio(note({ images: [{ width: 1200, height: 1600 }] })), 0.75);
assert.equal(getMediaAspectRatio(note({ type: "video", video: { width: 720, height: 1280 } })), 0.72);
assert.equal(getMediaAspectRatio(note({ images: [{ width: 3000, height: 1000 }] })), 1.35);
assert.equal(getMediaAspectRatio(note({ images: [] })), 0.75);

assert.deepEqual(
  extractUrls(`复制打开 https://xhslink.com/a， 也可以换行
https://www.xiaohongshu.com/explore/note-2?xsec_token=abc. 普通文案 https://xhslink.com/c！`),
  ["https://xhslink.com/a", "https://www.xiaohongshu.com/explore/note-2?xsec_token=abc", "https://xhslink.com/c"]
);

{
  const plan = createBatchImportPlan("https://xhslink.com/a https://xhslink.com/a https://xhslink.com/b", { limit: 20 });
  assert.equal(plan.totalExtracted, 3);
  assert.equal(plan.total, 3);
  assert.equal(plan.queued, 2);
  assert.deepEqual(plan.results.map((item) => item.status), ["pending", "duplicate-input", "pending"]);
}

{
  const plan = createBatchImportPlan(Array.from({ length: 22 }, (_, index) => `https://xhslink.com/${index}`).join("\n"), { limit: 20 });
  assert.equal(plan.totalExtracted, 22);
  assert.equal(plan.total, 20);
  assert.equal(plan.overflow, 2);
}

{
  const dataFile = normalizeImportDataFile({
    schemaVersion: 1,
    revision: 12,
    updatedAt: "2026-06-02T00:00:00Z",
    collections: [{ id: "import-1" }]
  });
  assert.equal(dataFile.schemaVersion, 1);
  assert.equal(dataFile.revision, 12);
  assert.deepEqual(dataFile.collections.map((item) => item.id), ["import-1"]);
  assert.throws(() => normalizeImportDataFile({ schemaVersion: 2, collections: [] }), /不支持/);
  assert.throws(() => normalizeImportDataFile({ schemaVersion: 1 }), /不支持/);
}

{
  const view = getCollectionView(notes, createViewState({ query: "不存在" }));
  assert.equal(view.visible, 0);
  assert.equal(view.total, 3);
  assert.equal(view.hasFilters, true);
}

{
  const view = getCollectionView(notes, createViewState({ query: "" }));
  assert.equal(view.visible, 3);
  assert.equal(view.hasFilters, false);
}

assert.equal(readCookie("opencollect_csrf", "a=1; opencollect_csrf=signed-token; b=2"), "signed-token");
assert.equal(withRequestSecurity({ method: "GET" }, "opencollect_csrf=signed-token").headers, undefined);
{
  const options = withRequestSecurity(
    { method: "POST", headers: { "content-type": "application/json" } },
    "a=1; opencollect_csrf=signed-token"
  );
  assert.equal(options.headers.get("X-CSRF-Token"), "signed-token");
  assert.equal(options.headers.get("content-type"), "application/json");
}

function note(overrides) {
  return {
    id: "",
    platform: "xiaohongshu",
    sourceUrl: "https://www.xiaohongshu.com/explore/mock",
    type: "normal",
    title: "",
    content: "",
    author: { name: "" },
    tags: [],
    collectedAt: "",
    sourceCreatedAt: "",
    createdAt: "",
    updatedAt: "",
    ...overrides,
    author: { name: overrides.author || "" }
  };
}

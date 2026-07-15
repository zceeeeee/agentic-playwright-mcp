import assert from "node:assert/strict";
import test from "node:test";
import { collectCommandHistory, navigateCommandHistory } from "../src/utils/commandHistory.js";

test("command history contains user tasks without adjacent optimistic duplicates", () => {
  assert.deepEqual(collectCommandHistory([
    { role: "user", content: "第一个任务" },
    { role: "user", content: "第一个任务" },
    { role: "assistant", content: "完成" },
    { role: "user", content: "第二个任务" }
  ]), ["第一个任务", "第二个任务"]);
});

test("up and down browse commands and restore the unfinished draft", () => {
  const history = ["第一个任务", "第二个任务"];
  const latest = navigateCommandHistory(history, "正在输入", null, "", "previous");
  assert.deepEqual(latest, { value: "第二个任务", index: 1, draft: "正在输入" });

  const older = navigateCommandHistory(history, latest.value, latest.index, latest.draft, "previous");
  assert.equal(older.value, "第一个任务");
  assert.equal(older.index, 0);

  const newer = navigateCommandHistory(history, older.value, older.index, older.draft, "next");
  assert.equal(newer.value, "第二个任务");
  const restored = navigateCommandHistory(history, newer.value, newer.index, newer.draft, "next");
  assert.deepEqual(restored, { value: "正在输入", index: null, draft: "正在输入" });
});

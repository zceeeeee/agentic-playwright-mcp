import assert from "node:assert/strict";
import test from "node:test";
import { getEnterKeyAction } from "../src/utils/keyboard.js";

test("Enter submits while Ctrl+Enter inserts a line break", () => {
  assert.equal(getEnterKeyAction("Enter", false), "submit");
  assert.equal(getEnterKeyAction("Enter", true), "newline");
  assert.equal(getEnterKeyAction("a", false), "none");
});

test("IME composition does not submit prematurely", () => {
  assert.equal(getEnterKeyAction("Enter", false, true), "none");
});

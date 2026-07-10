import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  getCompactShapeForSkin,
  getDefaultAppearancePreferences,
  readAppearancePreferences,
  validateSkinId,
  writeAppearancePreferences
} from "../electron/appearance.js";

test("appearance defaults to classic and validates skin ids", () => {
  assert.deepEqual(getDefaultAppearancePreferences(), { version: 1, skinId: "classic" });
  assert.equal(validateSkinId("animated-cat"), "animated-cat");
  assert.equal(validateSkinId("maltese"), "maltese");
  assert.equal(validateSkinId("unknown"), "classic");
});

test("appearance preferences persist and recover from invalid files", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "desktop-appearance-"));
  const file = path.join(directory, "ui-preferences.json");
  try {
    assert.equal(readAppearancePreferences(file).skinId, "classic");
    writeAppearancePreferences(file, { version: 1, skinId: "animated-cat" });
    assert.equal(readAppearancePreferences(file).skinId, "animated-cat");
    writeAppearancePreferences(file, { version: 1, skinId: "classic" });
    assert.equal(readAppearancePreferences(file).skinId, "classic");
    fs.writeFileSync(file, "not-json", "utf8");
    assert.equal(readAppearancePreferences(file).skinId, "classic");
    fs.writeFileSync(file, JSON.stringify({ version: 1, skinId: "invalid" }), "utf8");
    assert.equal(readAppearancePreferences(file).skinId, "classic");
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("classic is circular while animated skins keep the full compact rectangle", () => {
  const classic = getCompactShapeForSkin("classic", 80);
  const animated = getCompactShapeForSkin("animated-cat", 80);
  const maltese = getCompactShapeForSkin("maltese", 80);
  assert.ok(classic.length > 1);
  assert.ok(classic.some((rect) => rect.width < 80));
  assert.deepEqual(animated, [{ x: 0, y: 0, width: 80, height: 80 }]);
  assert.deepEqual(maltese, [{ x: 0, y: 0, width: 80, height: 80 }]);
});

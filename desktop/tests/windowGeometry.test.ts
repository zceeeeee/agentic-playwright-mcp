import assert from "node:assert/strict";
import test from "node:test";
import {
  DEFAULT_CHAT_SIZE,
  MIN_CHAT_HEIGHT,
  MIN_CHAT_WIDTH,
  clampChatBounds,
  parseChatSize,
  resizeChatBoundsBy
} from "../electron/windowGeometry.js";

test("chat size defaults and enforces minimum dimensions", () => {
  assert.deepEqual(parseChatSize(null), DEFAULT_CHAT_SIZE);
  assert.deepEqual(parseChatSize({ width: 100, height: 100 }), {
    width: MIN_CHAT_WIDTH,
    height: MIN_CHAT_HEIGHT
  });
  assert.deepEqual(parseChatSize({ width: 720.4, height: 640.6 }), {
    width: 720,
    height: 641
  });
});

test("incremental resizing keeps the opposite edge stable", () => {
  const area = { x: 0, y: 0, width: 1600, height: 1000 };
  const current = { x: 300, y: 200, width: 500, height: 600 };
  assert.deepEqual(
    resizeChatBoundsBy(current, "nw", 50, 80, area),
    { x: 350, y: 280, width: 450, height: 520 }
  );
  assert.deepEqual(
    resizeChatBoundsBy(current, "se", -300, -300, area),
    { x: 300, y: 200, width: MIN_CHAT_WIDTH, height: MIN_CHAT_HEIGHT }
  );
});

test("chat bounds remain inside the active display work area", () => {
  const area = { x: 100, y: 50, width: 1200, height: 800 };
  assert.deepEqual(
    clampChatBounds({ x: -500, y: -500, width: 2000, height: 1600 }, area),
    area
  );
  assert.deepEqual(
    clampChatBounds({ x: 1200, y: 700, width: 400, height: 500 }, area),
    { x: 900, y: 350, width: 400, height: 500 }
  );
});

import assert from "node:assert/strict";
import test from "node:test";
import {
  apiConnectionTestReducer,
  initialApiConnectionTestState
} from "../src/utils/apiConnectionTestState.js";

test("connection state transitions through testing and success", () => {
  const testing = apiConnectionTestReducer(
    initialApiConnectionTestState,
    { type: "start" }
  );
  assert.deepEqual(testing, { status: "testing", message: "", elapsedMs: 0 });

  const success = apiConnectionTestReducer(testing, {
    type: "succeed",
    message: "连接成功，模型可用",
    elapsedMs: 25
  });
  assert.deepEqual(success, {
    status: "success",
    message: "连接成功，模型可用",
    elapsedMs: 25
  });
});

test("connection state stores normalized failures", () => {
  const failed = apiConnectionTestReducer(
    { status: "testing", message: "", elapsedMs: 0 },
    { type: "fail", message: "API Key 认证失败", elapsedMs: 18 }
  );

  assert.deepEqual(failed, {
    status: "error",
    message: "API Key 认证失败",
    elapsedMs: 18
  });
});

test("editing API settings clears a stale result", () => {
  const cleared = apiConnectionTestReducer(
    { status: "success", message: "连接成功，模型可用", elapsedMs: 25 },
    { type: "edit" }
  );

  assert.deepEqual(cleared, initialApiConnectionTestState);
});

test("editing does not interrupt an active connection test", () => {
  const testing = { status: "testing", message: "", elapsedMs: 0 } as const;

  assert.equal(apiConnectionTestReducer(testing, { type: "edit" }), testing);
});

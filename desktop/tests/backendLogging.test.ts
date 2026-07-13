import assert from "node:assert/strict";
import { PassThrough } from "node:stream";
import test from "node:test";
import { forwardUtf8Logs, withUtf8PythonEnvironment } from "../electron/backendLogging.js";

test("Python backend environment always uses UTF-8 for redirected output", () => {
  const env = withUtf8PythonEnvironment({ PYTHONUTF8: "0", PYTHONIOENCODING: "gbk" });

  assert.equal(env.PYTHONUTF8, "1");
  assert.equal(env.PYTHONIOENCODING, "utf-8");
});

test("backend log decoding preserves Chinese split across buffer boundaries", async () => {
  const stream = new PassThrough();
  const messages: string[] = [];
  forwardUtf8Logs(stream, (message) => messages.push(message));

  const encoded = Buffer.from("任务执行成功\n", "utf8");
  stream.write(encoded.subarray(0, 2));
  stream.end(encoded.subarray(2));
  await new Promise<void>((resolve) => stream.on("end", resolve));

  assert.equal(messages.join(""), "任务执行成功");
  assert.ok(messages.every((message) => !message.includes("�")));
});

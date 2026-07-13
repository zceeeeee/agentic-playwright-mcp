import type { Readable } from "node:stream";

export function withUtf8PythonEnvironment(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  return {
    ...env,
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8"
  };
}

export function forwardUtf8Logs(stream: Readable, emit: (message: string) => void): void {
  stream.setEncoding("utf8");
  stream.on("data", (chunk: string) => {
    const message = chunk.trim();
    if (message) emit(message);
  });
}

import { copyFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(desktopRoot, "..");
const source = resolve(
  repositoryRoot,
  "tools/wx-cli/node_modules/@jackwener/wx-cli-win32-x64/bin/wx.exe"
);
const destination = resolve(desktopRoot, "resources/tools/wx-cli/wx.exe");

if (!existsSync(source)) {
  throw new Error(
    "wx-cli 0.3.0 is not installed. Run: npm.cmd install --prefix tools/wx-cli"
  );
}

await mkdir(dirname(destination), { recursive: true });
await copyFile(source, destination);
process.stdout.write(`Prepared wx-cli resource: ${destination}\n`);

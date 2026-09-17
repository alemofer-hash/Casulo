import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const sourceRoot = fileURLToPath(new URL("../src/", import.meta.url));
const tauriRoot = fileURLToPath(new URL("../src-tauri/", import.meta.url));
const allowed = new Set([".ts", ".tsx", ".js", ".mjs", ".css", ".html", ".json", ".rs", ".toml"]);
const generatedDirectories = new Set(["gen", "target", "target-msvc", "node_modules", "dist"]);
const findings = [];

async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const target = join(directory, entry.name);
    if (entry.isDirectory() && !generatedDirectories.has(entry.name)) await walk(target);
    else if (allowed.has(extname(entry.name))) {
      const text = await readFile(target, "utf8");
      const path = relative(root, target);
      for (const [label, expression] of [
        ["timer-based product simulation", /\bset(?:Timeout|Interval)\s*\(/],
        ["remote runtime URL", /https?:\/\/(?!schema\.tauri\.app|127\.0\.0\.1:1420|ipc\.localhost)/],
        ["network primitive", /\b(?:fetch|WebSocket|EventSource)\s*\(/],
        ["shell plugin", /tauri[_-]plugin[_-]shell|@tauri-apps\/plugin-shell/],
        ["filesystem plugin", /tauri[_-]plugin[_-]fs|@tauri-apps\/plugin-fs/],
      ]) if (expression.test(text)) findings.push({ path, label });
    }
  }
}

await walk(sourceRoot);
await walk(tauriRoot);
assert.deepEqual(findings, [], JSON.stringify(findings, null, 2));
console.log(JSON.stringify({ status: "PASS", source_network: false, shell_plugin: false, fs_plugin: false, timer_simulation: false }, null, 2));

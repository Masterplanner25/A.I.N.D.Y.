import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Every backend path prefix the client calls must be forwarded by the dev proxy. Otherwise the request goes to Vite,
// which answers with the SPA's HTML, and the caller sees a generic failure. That happened on 2026-11-09: the watcher
// key card called /watcher/keys, and /watcher was not proxied.
const ROOT = join(__dirname, "..", "..");

function proxiedPrefixes() {
  const config = readFileSync(join(ROOT, "vite.config.ts"), "utf-8");
  const block = config.slice(config.indexOf("proxy: {"));
  const prefixes = new Set();
  for (const m of block.matchAll(/^\s*"(\/[a-z_-]+)":\s*\{/gm)) prefixes.add(m[1]);
  return prefixes;
}

function calledPrefixes() {
  const dir = join(ROOT, "src", "api");
  const found = new Map();
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".js"))) {
    const text = readFileSync(join(dir, file), "utf-8");
    for (const m of text.matchAll(/(?:authRequest|request|adminRequest|taggedRequest)\(\s*[`"'](\/[a-z_-]+)/g)) {
      found.set(m[1], file);
    }
  }
  return found;
}

describe("dev proxy", () => {
  it("forwards every path prefix the client calls", () => {
    const proxied = proxiedPrefixes();
    const missing = [...calledPrefixes()].filter(([prefix]) => !proxied.has(prefix));
    expect(missing).toEqual([]);
  });

  it("finds the prefixes it checks", () => {
    const called = calledPrefixes();
    expect(called.has("/watcher")).toBe(true);
    expect(called.has("/auth")).toBe(true);
    expect(proxiedPrefixes().has("/watcher")).toBe(true);
  });
});

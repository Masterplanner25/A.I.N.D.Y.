/**
 * Which /apps/* paths the client calls — written to docs/verification/client_routes.json for the
 * inventory (`scripts/inventory.py`), which marks every route no client code reaches.
 *
 * It has to be read here, not by Python: most paths come from ui-kit's `ROUTES`, built at runtime
 * and corrected by `_routes.js`. Two sources, both from the code:
 *   - every `ROUTES.X.Y` the client source mentions, resolved (a function is called with ":p");
 *   - every literal "/apps/..." path in the source, `${…}` replaced by ":p".
 *
 * Out of date → this fails. Regenerate: `UPDATE_CLIENT_ROUTES=1 npx vitest run client-routes-manifest`.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { ROUTES } from "../api/_routes.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "..");
const MANIFEST = path.resolve(HERE, "../../../docs/verification/client_routes.json");

function sourceFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "test" ? [] : sourceFiles(full);
    return /\.(js|jsx)$/.test(entry.name) ? [full] : [];
  });
}

const clean = (p) => p.split("?")[0].replace(/\$\{[^}]*\}/g, ":p").replace(/\/+$/, "") || "/";

function resolve(value) {
  if (typeof value === "string") return value;
  if (typeof value === "function") {
    const args = Array.from({ length: Math.max(value.length, 1) }, () => ":p");
    const out = value(...args);
    return typeof out === "string" ? out : null;
  }
  return null;
}

function clientPaths() {
  const found = new Set();
  for (const file of sourceFiles(SRC)) {
    const text = fs.readFileSync(file, "utf8");
    for (const [, group, key] of text.matchAll(/ROUTES\.([A-Z_]+)\.([A-Z_0-9]+)/g)) {
      const value = resolve(ROUTES[group]?.[key]);
      if (value && value.startsWith("/apps/")) found.add(clean(value));
    }
    for (const [, literal] of text.matchAll(/[`"'](\/apps\/[^`"'\s]*)/g)) {
      found.add(clean(literal));
    }
  }
  return [...found].sort();
}

describe("client routes manifest", () => {
  it("lists every /apps path the client calls, and is up to date", () => {
    const paths = clientPaths();
    const body = `${JSON.stringify({ generated_by: "client/src/test/client-routes-manifest.test.js", paths }, null, 2)}\n`;
    if (process.env.UPDATE_CLIENT_ROUTES) {
      fs.writeFileSync(MANIFEST, body);
    }
    expect(paths.length).toBeGreaterThan(100);
    const committed = fs.existsSync(MANIFEST) ? fs.readFileSync(MANIFEST, "utf8") : "";
    expect(committed.replace(/\r\n/g, "\n"), "client_routes.json is stale: rerun with UPDATE_CLIENT_ROUTES=1").toBe(body);
  });
});

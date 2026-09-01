import { readFileSync } from "fs";
import path from "path";
import { extname } from "path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const pkg = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf-8"));
const rootDir = process.cwd();
const platformComponentPaths = [
  "./src/components/platform/AgentConsole.jsx",
  "./src/components/platform/FlowEngineConsole.jsx",
  "./src/components/platform/ObservabilityDashboard.jsx",
  "./src/components/platform/HealthDashboard.jsx",
  "./src/components/platform/ExecutionConsole.jsx",
  "./src/components/platform/AgentApprovalInbox.jsx",
  "./src/components/platform/AgentRegistry.jsx",
  "./src/components/platform/RippleTraceViewer.jsx",
];

function platformHtmlFallback() {
  return {
    name: "platform-html-fallback",
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const method = req.method?.toUpperCase();
        const originalUrl = req.url ?? "/";

        if (method !== "GET" && method !== "HEAD") {
          next();
          return;
        }

        const [pathname] = originalUrl.split("?");
        const isPlatformRoute =
          pathname === "/platform" || pathname.startsWith("/platform/");
        const hasExtension = extname(pathname) !== "";

        // `/platform` is BOTH the SPA mount and the backend's operator API namespace
        // (51 routes: /platform/flows/runs, /platform/observability/*, /platform/admin/*).
        // This middleware runs before Vite's proxy, so rewriting every extension-less
        // /platform GET to platform.html also swallowed every platform API call — the
        // panels received the SPA's HTML with a 200 instead of JSON. FlowRunsPanel then
        // did `runs.runs.reduce(...)` on a string and crashed the console.
        //
        // Only a real browser navigation asks for HTML; fetch/XHR sends `*/*` or
        // application/json. Gate on that, and let everything else fall through to the
        // "/platform" proxy entry below.
        const accept = String(req.headers.accept || "");
        const wantsHtml = accept.includes("text/html");

        if (!isPlatformRoute || hasExtension || !wantsHtml) {
          next();
          return;
        }

        req.url = "/platform.html";
        next();
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const buildTarget = mode === "app" || mode === "platform" ? mode : "all";

  // Vite 8 bundles with Rolldown, which rejects Rollup's object form of
  // `manualChunks` outright — "Invalid type: Expected Function but received Object",
  // then `TypeError: manualChunks is not a function`. Rolldown deprecates both
  // `manualChunks` and its first replacement `advancedChunks` in favour of
  // `output.codeSplitting`, so the grouping is expressed there rather than migrating
  // onto a second deprecated API.
  //
  // `includeDependenciesRecursively` restores the semantics the object form had:
  // Rollup pulled each listed module's private dependency subtree into the chunk
  // with it. Matching on module id alone would capture only the eight platform
  // component files themselves and scatter everything they import.
  //
  // Path separators are written `[\\/]` because these run against native module ids,
  // which are backslash-separated on Windows.
  const toPathPattern = (p: string) =>
    p.replace("./", "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\//g, "[\\\\/]");
  const platformComponentPattern = new RegExp(
    `(${platformComponentPaths.map(toPathPattern).join("|")})$`,
  );

  const codeSplittingGroups = [
    {
      name: "vendor-react",
      test: /node_modules[\\/](react|react-dom|react-router-dom)[\\/]/,
      includeDependenciesRecursively: true,
    },
    {
      name: "vendor-charts",
      test: /node_modules[\\/](recharts|victory-vendor|d3(-[a-z0-9]+)?)[\\/]/,
      includeDependenciesRecursively: true,
    },
    {
      name: "vendor-ui",
      test: /node_modules[\\/](@radix-ui[\\/]react-(slot|tooltip)|lucide-react|clsx|class-variance-authority|tailwind-merge)[\\/]/,
      includeDependenciesRecursively: true,
    },
    ...(buildTarget === "app"
      ? []
      : [
          {
            name: "chunk-platform",
            test: platformComponentPattern,
            includeDependenciesRecursively: true,
          },
        ]),
  ];

  const input =
    buildTarget === "app"
      ? {
          app: path.resolve(rootDir, "index.html"),
        }
      : buildTarget === "platform"
        ? {
            platform: path.resolve(rootDir, "platform.html"),
          }
        : {
            app: path.resolve(rootDir, "index.html"),
            platform: path.resolve(rootDir, "platform.html"),
          };

  return {
    plugins: [react(), platformHtmlFallback()],
    define: {
      __APP_VERSION__: JSON.stringify(pkg.version),
    },

    resolve: {
      alias: {
        "@": path.resolve(rootDir, "src"),
      },
    },

    build: {
      sourcemap: mode === "development",
      chunkSizeWarningLimit: 500,
      target: ["chrome90", "firefox88", "safari14", "edge90"],
      outDir: "dist",
      rollupOptions: {
        input,
        output: {
          codeSplitting: { groups: codeSplittingGroups },
          entryFileNames: (chunkInfo) =>
            chunkInfo.name === "platform"
              ? "platform/assets/[name]-[hash].js"
              : "assets/[name]-[hash].js",
          chunkFileNames: (chunkInfo) => {
            const moduleIds = chunkInfo.moduleIds ?? [];
            const isPlatformChunk = moduleIds.some((moduleId) => {
              const normalizedModuleId = moduleId.replaceAll("\\", "/");
              return normalizedModuleId.includes("/src/platform.tsx") ||
                platformComponentPaths.some((platformPath) =>
                  normalizedModuleId.endsWith(platformPath.replace("./", "/")),
                );
            });

            return isPlatformChunk
              ? "platform/assets/[name]-[hash].js"
              : "assets/[name]-[hash].js";
          },
          assetFileNames: "assets/[name]-[hash][extname]",
        },
      },
    },

    server: {
      proxy: {
        // Dev proxy: the client (via @aindy/ui-kit) calls the backend's route namespaces
        // relatively (empty API base), so forward them all to the local API — no /api-base
        // env needed in dev.
        //
        // /api is forwarded VERBATIM. It previously stripped the prefix, which broke the only
        // route it applies to: the backend serves `/api/version` at that literal path and has
        // no `/version`, so `/api/version` (ui-kit's ROUTES.PLATFORM.VERSION) 404'd in dev
        // while working in prod. No backend route lives at a stripped `/api/*` path, so there
        // is nothing for the rewrite to serve.
        "/api": { target: "http://localhost:8000", changeOrigin: true },
        "/auth": { target: "http://localhost:8000", changeOrigin: true },
        "/apps": { target: "http://localhost:8000", changeOrigin: true },
        // `/platform` is BOTH the SPA mount and the backend's operator API namespace
        // (51 routes). The split has to happen here rather than in a plugin middleware:
        // Vite installs the proxy ahead of plugin middlewares, so the proxy sees these
        // requests first and a middleware-only rule never gets a say.
        //
        // `bypass` returning a path hands the request back to Vite's static/HTML
        // pipeline; returning undefined proxies it. Only a real browser navigation
        // asks for text/html — fetch/XHR sends */* or application/json — so document
        // requests render the SPA and every API call is forwarded verbatim.
        "/platform": {
          target: "http://localhost:8000",
          changeOrigin: true,
          bypass(req) {
            const method = req.method?.toUpperCase();
            if (method !== "GET" && method !== "HEAD") return undefined;
            const [pathname] = (req.url ?? "/").split("?");
            // `/platform.html` and `/platform/assets/*` start with the proxy prefix, so
            // without this the SPA document and its bundles would be forwarded to the
            // API and 404. Returning the path serves it from Vite instead of proxying —
            // this also catches the rewrite platformHtmlFallback performs upstream.
            if (extname(pathname) !== "") return req.url;
            if (!String(req.headers.accept || "").includes("text/html")) return undefined;
            return "/platform.html";
          },
        },
        "/health": { target: "http://localhost:8000", changeOrigin: true },
        "/openapi.json": { target: "http://localhost:8000", changeOrigin: true },
      },
    },

    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.js"],
      css: false,
      exclude: ["e2e/**", "node_modules/**", "dist/**"],
    },
  };
});

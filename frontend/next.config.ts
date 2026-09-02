import type { NextConfig } from "next";

/**
 * Deliberately empty of routing.
 *
 * The backend proxy used to live here as a `rewrites()` entry reading
 * `BACKEND_ORIGIN`, on the assumption that `rewrites()` is evaluated by the
 * running server. It is not: Next resolves it during `next build` and writes
 * the destination into `.next/routes-manifest.json`, which is what `next start`
 * routes from (`next/dist/server/lib/router-utils/filesystem.js` builds its
 * route table from `routesManifest.rewrites`). A container built without
 * BACKEND_ORIGIN in its *build* environment therefore baked in
 * `http://localhost:8000` and proxied every API call to itself, which is what
 * broke `docker compose up`.
 *
 * The proxy is now `src/app/api/[...path]/route.ts`, a route handler, which is
 * evaluated per request and so actually reads the running container's
 * environment. Nothing about the backend's address is decided at build time.
 */
const nextConfig: NextConfig = {};

export default nextConfig;

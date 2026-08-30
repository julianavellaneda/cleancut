import type { NextConfig } from "next";

/**
 * Where the backend is, from the Next server's point of view.
 *
 * Deliberately *not* a NEXT_PUBLIC_ variable: a public one is inlined into the
 * bundle at build time, which is exactly the problem this rewrite exists to
 * solve. `rewrites()` is evaluated by the running server, so one built image
 * can be pointed at any backend by an environment variable at start time -
 * `docker run -e BACKEND_ORIGIN=...` rather than a rebuild.
 *
 * `||` rather than `??`: `start.sh` sources the root .env with `set -a`, so a
 * blank line there arrives as an empty string, not as absent.
 */
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN || "http://localhost:8000";

const nextConfig: NextConfig = {
  // The browser calls a relative `/api`, so every request is same-origin and
  // the backend's CORS list never comes into it. The cost is one extra hop for
  // audio streaming and export downloads; on a loopback tool that is nothing,
  // and anyone who wants the direct call can still set NEXT_PUBLIC_API_URL to
  // the backend and bypass this entirely.
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_ORIGIN}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;

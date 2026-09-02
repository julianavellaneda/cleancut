/**
 * The backend proxy, as a route handler rather than a rewrite.
 *
 * The browser calls a relative `/api`, so every request is same-origin and the
 * backend's CORS list never comes into it. Where the backend actually is has to
 * be a *runtime* decision: one published image should be pointable at any
 * backend by an environment variable at start time, rather than pinned to
 * whichever origin happened to build it.
 *
 * This used to be `rewrites()` in next.config.ts, which does not work. Next
 * evaluates `rewrites()` during `next build` and writes the resolved
 * destination into `.next/routes-manifest.json`; `next start` reads the
 * manifest, not the config (see
 * `next/dist/server/lib/router-utils/filesystem.js`, which builds its route
 * table from `routesManifest.rewrites`). So a Compose build with no
 * BACKEND_ORIGIN in its build environment baked in `http://localhost:8000` -
 * which, inside the frontend container, is the frontend itself. Every API call
 * in `docker compose up` failed.
 *
 * A route handler is evaluated per request, so `process.env.BACKEND_ORIGIN` is
 * read from the running container's environment, which is what was intended
 * all along.
 *
 * `NEXT_PUBLIC_API_URL` is unaffected and still wins when set: that is the
 * direct cross-origin call, which needs `CORS_ORIGINS` to name the frontend and
 * skips this hop entirely.
 */

// Read the origin per request, never at module scope: a module-level constant
// would be captured when the route module is first loaded, which is close
// enough to build time to reintroduce the bug this file exists to fix.
export const dynamic = "force-dynamic";
// The Node runtime, for streaming request bodies. Uploads are capped at 500 MB
// by default and audio playback is a range request over the whole media file;
// neither may be buffered into memory on the way through.
export const runtime = "nodejs";

/**
 * Where the backend is, from the Next server's point of view.
 *
 * `||` rather than `??`: `start.sh` sources the root .env with `set -a`, so a
 * variable left blank there arrives as an empty string, not as absent, and
 * `??` would take `""` and proxy every request to a base of nothing.
 */
function backendOrigin(): string {
  return process.env.BACKEND_ORIGIN || "http://localhost:8000";
}

/**
 * Headers that describe *this* connection rather than the message, and so must
 * not be relayed onto the next one.
 *
 * `content-length` is in here for a different reason than the rest: the body is
 * re-framed as a stream, so the original length no longer describes what we are
 * sending. `host` would name the frontend to the backend. `connection` and
 * friends are hop-by-hop by definition (RFC 9110 §7.6.1).
 */
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

function forwardable(headers: Headers): Headers {
  const out = new Headers();
  headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) out.set(key, value);
  });
  return out;
}

/**
 * Relay one request to the backend and stream the answer back.
 *
 * Everything that makes media work travels in headers, so they are passed
 * through rather than reconstructed: `Range` and `Content-Range` for waveform
 * seeking and scrubbing, `Content-Disposition` for the export download's
 * filename, `Content-Type` for both.
 */
async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await context.params;
  const { search } = new URL(request.url);
  const target = `${backendOrigin()}/api/${path.map(encodeURIComponent).join("/")}${search}`;

  // GET and HEAD have no body to forward, and passing `null` with `duplex`
  // set makes undici reject the request.
  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  let response: Response;
  try {
    response = await fetch(target, {
      method: request.method,
      headers: forwardable(request.headers),
      body: hasBody ? request.body : undefined,
      // Required by undici whenever a stream is the body: it says we are
      // finished sending before we start reading, which is ordinary
      // request/response and not full duplex.
      ...(hasBody ? { duplex: "half" } : {}),
      // A redirect is the backend's answer to relay, not something to resolve
      // server-side on the client's behalf.
      redirect: "manual",
    } as RequestInit);
  } catch (error) {
    // The backend being unreachable is a gateway failure, not a 500 from this
    // server. 502 is what tells the difference apart in a log.
    return Response.json(
      { detail: `Cannot reach the backend at ${backendOrigin()}: ${String(error)}` },
      { status: 502 },
    );
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: forwardable(response.headers),
  });
}

export {
  proxy as GET,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
  proxy as HEAD,
  proxy as OPTIONS,
};

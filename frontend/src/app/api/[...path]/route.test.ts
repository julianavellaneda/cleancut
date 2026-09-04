/**
 * The backend proxy's contract.
 *
 * The case that matters is `reads BACKEND_ORIGIN per request`. This proxy
 * exists because its predecessor - a `rewrites()` entry in next.config.ts -
 * resolved the origin once, at build time, and baked `http://localhost:8000`
 * into every container image. A test that only checked "it proxies somewhere"
 * would have passed against the broken version too, so the assertion here is
 * specifically that the origin can move *between two calls to the same loaded
 * module* and the target moves with it.
 *
 * The rest pin what media playback and downloads actually depend on: Range
 * survives out, Content-Range and Content-Disposition survive back, and the
 * headers that describe a connection rather than a message are not relayed
 * onto the next one.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DELETE, GET, POST } from "./route";

type FetchInit = RequestInit & { duplex?: string };

type FetchArgs = [input: string | URL, init?: FetchInit];

function mockFetch(
  init: { status?: number; headers?: Record<string, string>; body?: unknown } = {},
) {
  // The parameters are declared only so the call record is typed; nothing here
  // reads them, `target` and `sentInit` do.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const spy = vi.fn(async (..._args: FetchArgs) => ({
    status: init.status ?? 200,
    statusText: "OK",
    headers: new Headers(init.headers ?? {}),
    body: init.body ?? null,
  }));
  vi.stubGlobal("fetch", spy);
  return spy;
}

function target(spy: ReturnType<typeof mockFetch>, call = 0): string {
  return String(spy.mock.calls[call][0]);
}

function sentInit(spy: ReturnType<typeof mockFetch>, call = 0): FetchInit {
  return spy.mock.calls[call][1] ?? {};
}

/** The route's second argument: Next 16 hands params as a promise. */
function ctx(...path: string[]) {
  return { params: Promise.resolve({ path }) };
}

const ORIGINAL_ORIGIN = process.env.BACKEND_ORIGIN;

beforeEach(() => {
  delete process.env.BACKEND_ORIGIN;
});

afterEach(() => {
  vi.unstubAllGlobals();
  if (ORIGINAL_ORIGIN === undefined) delete process.env.BACKEND_ORIGIN;
  else process.env.BACKEND_ORIGIN = ORIGINAL_ORIGIN;
});

describe("the backend proxy", () => {
  it("reads BACKEND_ORIGIN per request, not once at module load", async () => {
    const spy = mockFetch();

    process.env.BACKEND_ORIGIN = "http://backend:8000";
    await GET(new Request("http://localhost:3000/api/jobs"), ctx("jobs"));

    // Same loaded module, different environment. A build-time constant - the
    // bug this file replaces - would ignore this and keep the first origin.
    process.env.BACKEND_ORIGIN = "http://elsewhere:9000";
    await GET(new Request("http://localhost:3000/api/jobs"), ctx("jobs"));

    expect(target(spy, 0)).toBe("http://backend:8000/api/jobs");
    expect(target(spy, 1)).toBe("http://elsewhere:9000/api/jobs");
  });

  it("falls back to localhost:8000 when the origin is unset or blank", async () => {
    const spy = mockFetch();

    await GET(new Request("http://localhost:3000/api/jobs"), ctx("jobs"));

    // `start.sh` sources the root .env with `set -a`, so a blank line there
    // arrives as "" rather than as absent. `??` would take it and proxy to a
    // base of nothing; `||` is what makes the fallback cover both.
    process.env.BACKEND_ORIGIN = "";
    await GET(new Request("http://localhost:3000/api/jobs"), ctx("jobs"));

    expect(target(spy, 0)).toBe("http://localhost:8000/api/jobs");
    expect(target(spy, 1)).toBe("http://localhost:8000/api/jobs");
  });

  it("preserves the nested path and the query string", async () => {
    const spy = mockFetch();

    await GET(
      new Request("http://localhost:3000/api/jobs/abc/violations?labels=Filler+Word&from_status=accepted"),
      ctx("jobs", "abc", "violations"),
    );

    expect(target(spy)).toBe(
      "http://localhost:8000/api/jobs/abc/violations?labels=Filler+Word&from_status=accepted",
    );
  });

  it("forwards Range and returns Content-Range, so seeking works", async () => {
    const spy = mockFetch({
      status: 206,
      headers: { "content-range": "bytes 0-1023/8192", "accept-ranges": "bytes" },
    });

    const response = await GET(
      new Request("http://localhost:3000/api/jobs/abc/audio", {
        headers: { Range: "bytes=0-1023" },
      }),
      ctx("jobs", "abc", "audio"),
    );

    expect(new Headers(sentInit(spy).headers).get("range")).toBe("bytes=0-1023");
    expect(response.status).toBe(206);
    expect(response.headers.get("content-range")).toBe("bytes 0-1023/8192");
    expect(response.headers.get("accept-ranges")).toBe("bytes");
  });

  it("returns Content-Disposition, so an export downloads under its own name", async () => {
    mockFetch({
      headers: { "content-disposition": 'attachment; filename="abc_edited.mp3"' },
    });

    const response = await GET(
      new Request("http://localhost:3000/api/jobs/abc/export/download"),
      ctx("jobs", "abc", "export", "download"),
    );

    expect(response.headers.get("content-disposition")).toBe(
      'attachment; filename="abc_edited.mp3"',
    );
  });

  it("strips hop-by-hop headers rather than relaying them onto the next connection", async () => {
    const spy = mockFetch();

    await GET(
      new Request("http://localhost:3000/api/jobs", {
        headers: {
          host: "localhost:3000",
          connection: "keep-alive",
          "x-admin-token": "secret",
        },
      }),
      ctx("jobs"),
    );

    const sent = new Headers(sentInit(spy).headers);
    expect(sent.get("host")).toBeNull();
    expect(sent.get("connection")).toBeNull();
    // Application headers still travel: the admin routes are gated on this one.
    expect(sent.get("x-admin-token")).toBe("secret");
  });

  it("streams a request body through instead of buffering it", async () => {
    const spy = mockFetch({ status: 202 });

    const upload = new Request("http://localhost:3000/api/jobs", {
      method: "POST",
      body: "pretend-multipart",
    });
    await POST(upload, ctx("jobs"));

    const init = sentInit(spy);
    expect(init.method).toBe("POST");
    // `duplex: "half"` is required by undici whenever a stream is the body.
    // Without it the request is rejected outright, so an upload never lands.
    expect(init.duplex).toBe("half");
    expect(init.body).not.toBeUndefined();
  });

  it("sends no body or duplex on GET, which undici rejects", async () => {
    const spy = mockFetch();

    await GET(new Request("http://localhost:3000/api/jobs"), ctx("jobs"));

    const init = sentInit(spy);
    expect(init.body).toBeUndefined();
    expect(init.duplex).toBeUndefined();
  });

  it("relays the backend's status rather than flattening it", async () => {
    mockFetch({ status: 409 });

    const response = await DELETE(
      new Request("http://localhost:3000/api/jobs/abc", { method: "DELETE" }),
      ctx("jobs", "abc"),
    );

    expect(response.status).toBe(409);
  });

  it("answers 502 when the backend is unreachable, not 500", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("ECONNREFUSED");
      }),
    );

    const response = await GET(new Request("http://localhost:3000/api/jobs"), ctx("jobs"));

    // The distinction is worth a status code: 500 says this server broke,
    // 502 says the thing behind it did not answer.
    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toMatchObject({
      detail: expect.stringContaining("Cannot reach the backend"),
    });
  });
});

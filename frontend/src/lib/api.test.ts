/**
 * The API client's request shapes, checked against a stubbed fetch.
 *
 * These read as trivial until one of them is wrong: `bulkUpdateViolations`
 * builds the query string that decides *which rows a sweep moves*, and getting
 * `from_status` wrong there is the difference between undoing a Clean All and
 * resetting every decision in the job. The transcript case is here for the
 * opposite reason - its 404 is a normal outcome that must not surface as an
 * error, since any job processed before transcripts were persisted returns one.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";

type FetchArgs = [input: string | URL, init?: RequestInit];

function mockFetch(body: unknown, init: { status?: number } = {}) {
  const status = init.status ?? 200;
  // The parameter is declared only so the call record is typed; nothing reads
  // it here, `firstCall` does.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const spy = vi.fn(async (..._args: FetchArgs) => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }));
  vi.stubGlobal("fetch", spy);
  return spy;
}

function firstCall(spy: ReturnType<typeof mockFetch>): FetchArgs {
  return spy.mock.calls[0];
}

function calledUrl(spy: ReturnType<typeof mockFetch>): URL {
  return new URL(String(firstCall(spy)[0]));
}

function calledBody(spy: ReturnType<typeof mockFetch>): unknown {
  return JSON.parse(String(firstCall(spy)[1]?.body));
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("bulkUpdateViolations", () => {
  it("sends no filters at all for a plain sweep", async () => {
    const spy = mockFetch({ message: "Updated 3 violations", updated: 3 });

    await api.bulkUpdateViolations("job-1", { status: "accepted" });

    const url = calledUrl(spy);
    expect(url.pathname).toBe("/api/jobs/job-1/violations/bulk-update");
    expect(url.search).toBe("");
    expect(calledBody(spy)).toEqual({ status: "accepted" });
  });

  it("repeats the label param once per label", async () => {
    const spy = mockFetch({ message: "ok", updated: 0 });

    await api.bulkUpdateViolations("job-1", { status: "accepted" }, ["Filler Word", "Dead Air"]);

    expect(calledUrl(spy).searchParams.getAll("labels")).toEqual(["Filler Word", "Dead Air"]);
  });

  it("sends the undo as ids plus the status they are coming from", async () => {
    const spy = mockFetch({ message: "ok", updated: 2 });

    await api.bulkUpdateViolations(
      "job-1", { status: "pending", ids: ["a", "b"] }, undefined, ["accepted"]
    );

    const url = calledUrl(spy);
    expect(url.searchParams.getAll("from_status")).toEqual(["accepted"]);
    expect(url.searchParams.getAll("labels")).toEqual([]);
    expect(calledBody(spy)).toEqual({ status: "pending", ids: ["a", "b"] });
  });

  it("raises the server's detail rather than a generic failure", async () => {
    mockFetch({ detail: "Status must be 'pending', 'accepted', or 'rejected'" }, { status: 400 });

    await expect(api.bulkUpdateViolations("job-1", { status: "banana" }))
      .rejects.toThrow(/must be 'pending'/);
  });
});

describe("getTranscript", () => {
  it("reads a 404 as 'this job has none' rather than an error", async () => {
    mockFetch({ detail: "No transcript" }, { status: 404 });

    await expect(api.getTranscript("job-1")).resolves.toBeNull();
  });

  it("still throws on a real failure", async () => {
    mockFetch({ detail: "boom" }, { status: 500 });

    await expect(api.getTranscript("job-1")).rejects.toThrow("boom");
  });
});

describe("reanalyzeJob", () => {
  it("posts the prompt to the job's own endpoint", async () => {
    const spy = mockFetch({ job_id: "job-1", prompt: "find guarantees", preset: null, status: "analyzing" });

    await api.reanalyzeJob("job-1", { prompt: "find guarantees" });

    expect(calledUrl(spy).pathname).toBe("/api/jobs/job-1/reanalyze");
    expect(calledBody(spy)).toEqual({ prompt: "find guarantees" });
  });

  it("surfaces the server's reason for refusing", async () => {
    mockFetch({ detail: "This job has no stored transcript to re-analyze." }, { status: 409 });

    await expect(api.reanalyzeJob("job-1", { prompt: "x" }))
      .rejects.toThrow(/no stored transcript/);
  });
});

"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ArrowLeftGlyph } from "@/components/icons";
import { AdminStats, api, getAdminToken, setAdminToken } from "@/lib/api";
import { cn } from "@/lib/utils";

type OperationId = "database" | "storage" | "all";

/**
 * The three destructive routes, as data.
 *
 * `verb` exists only for the confirmation button: "Yes, wipe everything" says
 * what is about to happen where "Yes" or "Confirm" would not, and a reader who
 * opened the wrong dialog can tell from that button alone.
 */
const OPERATIONS: {
  id: OperationId;
  name: string;
  description: string;
  verb: string;
  button: string;
}[] = [
  {
    id: "database",
    name: "Reset database",
    description: "Clear all job records and suggestions",
    verb: "reset it",
    button: "Reset",
  },
  {
    id: "storage",
    name: "Clear storage",
    description: "Delete all uploaded and exported media files",
    verb: "delete them",
    button: "Clear",
  },
  {
    id: "all",
    name: "System wipe",
    description: "Reset the database and clear storage together",
    verb: "wipe everything",
    button: "Wipe",
  },
];

type OperationState = { running?: boolean; result?: string; ok?: boolean };

export default function AdminDashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState(false);
  const [token, setToken] = useState("");
  const [opState, setOpState] = useState<Record<string, OperationState>>({});
  const [confirming, setConfirming] = useState<OperationId | null>(null);

  // Closes over nothing reactive - the API client and two setters - so the
  // mount effect below can honestly list it.
  const loadStats = useCallback(async () => {
    setStatsLoading(true);
    setStatsError(false);
    try {
      setStats(await api.getAdminStats());
    } catch {
      setStatsError(true);
    } finally {
      setStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  // Read on mount rather than in the initial state so the server render and the
  // first client render agree; localStorage does not exist on the server.
  useEffect(() => {
    setToken(getAdminToken());
  }, []);

  async function runOperation(id: OperationId) {
    setConfirming(null);
    setOpState((s) => ({ ...s, [id]: { running: true } }));
    try {
      const result =
        id === "database"
          ? await api.resetDatabase()
          : id === "storage"
            ? await api.clearStorage()
            : await api.resetAll();
      setOpState((s) => ({ ...s, [id]: { result: result.message, ok: true } }));
      await loadStats();
    } catch (err) {
      setOpState((s) => ({
        ...s,
        [id]: { result: err instanceof Error ? err.message : "Reset failed", ok: false },
      }));
    }
  }

  const confirmingOp = OPERATIONS.find((o) => o.id === confirming) ?? null;

  /*
   * One request feeds all three cards, so they share its loading state - and a
   * failure is reported *once*, on a row across the grid, rather than three
   * times with three retry buttons for the one request they would all repeat.
   * Storage carries its unit separately: the number is set in the display face
   * and "MB" in it at 30px would read as part of the figure.
   */
  const cards: { label: string; value: string; unit?: string }[] = [
    { label: "Jobs", value: String(stats?.total_jobs ?? 0) },
    { label: "Suggestions", value: String(stats?.total_violations ?? 0) },
    {
      label: "Storage",
      value: (
        (stats?.total_uploads_size_mb ?? 0) + (stats?.total_exports_size_mb ?? 0)
      ).toFixed(1),
      unit: "MB",
    },
  ];

  return (
    <div className="mx-auto flex w-full max-w-[760px] flex-col gap-9 px-8 pt-14 pb-20">
      <header className="flex items-start justify-between gap-6">
        <div>
          <Link
            href="/"
            className="mb-4.5 inline-flex items-center gap-1.5 text-[13px] text-muted no-underline transition-colors hover:text-acc"
          >
            <ArrowLeftGlyph size={13} />
            Back to CleanCut
          </Link>
          <h1 className="mb-2 font-heading text-[34px] leading-tight">Maintenance</h1>
          <p className="m-0 max-w-[52ch] text-[15px] text-muted text-pretty">
            Housekeeping for this local instance. Statistics are always readable; the reset
            actions need the admin token configured on the server.
          </p>
        </div>
        <ThemeToggle className="mt-1 flex-none" />
      </header>

      {statsError ? (
        <div className="flex items-center justify-between gap-4 rounded-lg bg-surface px-5 py-4.5 text-[13px] text-danger-700">
          Couldn&rsquo;t load the statistics.
          <button
            type="button"
            onClick={loadStats}
            className="rounded-full border border-divider px-3.5 py-1.5 text-[13px] text-acc transition-colors hover:bg-surface2"
          >
            Retry
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          {cards.map((card) => (
            <div
              key={card.label}
              className="flex min-h-[104px] flex-col justify-between rounded-lg bg-surface px-5 py-4.5"
            >
              <div className="text-xs text-muted">{card.label}</div>
              {statsLoading ? (
                <div
                  aria-hidden
                  className="h-[30px] w-3/5 animate-cc-pulse rounded-full bg-surface2"
                />
              ) : (
                <div className="font-heading text-[30px] leading-none">
                  {card.value}
                  {card.unit && <span className="ml-1 text-sm text-muted">{card.unit}</span>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Destructive actions need the server's ADMIN_TOKEN. A server with none
          configured refuses them outright (503) rather than accepting anything,
          so this stays a field on a working dashboard rather than a login wall
          in front of the stats. */}
      <div className="flex max-w-[420px] flex-col gap-1.5">
        <label htmlFor="admin-token" className="text-xs text-muted">
          Admin token
        </label>
        <input
          id="admin-token"
          type="password"
          value={token}
          placeholder="Paste the ADMIN_TOKEN from the server config"
          onChange={(e) => {
            setToken(e.target.value);
            setAdminToken(e.target.value);
          }}
          className="rounded-full border border-divider bg-surface px-4 py-2.5 text-sm text-text focus-visible:border-acc"
        />
        <span className="text-xs text-muted">
          Sent as <code className="font-mono">X-Admin-Token</code> with each destructive action
          and kept only in this browser.
        </span>
      </div>

      <section className="flex flex-col gap-2.5">
        <h2 className="m-0 mb-1 flex items-center gap-2.5 font-heading text-[22px]">
          Irreversible actions
          <span className="rounded-full bg-danger-100 px-2.5 py-[3px] font-sans text-[11px] uppercase tracking-[0.08em] text-danger-700">
            no undo
          </span>
        </h2>
        {OPERATIONS.map((op) => {
          const state = opState[op.id] ?? {};
          return (
            <div
              key={op.id}
              // A result line belongs to the action that produced it, not to a
              // banner at the top of the page - three rows that each report
              // separately need to be separately addressable to say so.
              role="group"
              aria-label={op.name}
              className="grid grid-cols-[1fr_auto] items-center gap-4 rounded-lg bg-surface px-5 py-4"
            >
              <div>
                <div className="text-[15px] font-semibold">{op.name}</div>
                <div className="text-[13px] text-muted">{op.description}</div>
                {state.result && (
                  <div
                    className={cn(
                      "mt-2 rounded-sm px-3 py-1.5 text-xs [overflow-wrap:anywhere]",
                      state.ok
                        ? "bg-acc2-100 text-acc2-700"
                        : "bg-danger-100 text-danger-700"
                    )}
                  >
                    {state.result}
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={() => setConfirming(op.id)}
                disabled={state.running}
                className="inline-flex items-center gap-2 rounded-full border border-danger px-4 py-2 text-[13px] font-semibold text-danger-700 transition-colors hover:bg-danger-100 disabled:opacity-60 disabled:hover:bg-transparent"
              >
                {state.running && (
                  <span
                    aria-hidden
                    className="size-[11px] animate-cc-spin rounded-full border-2 border-current border-t-transparent"
                  />
                )}
                {op.button}
              </button>
            </div>
          );
        })}
      </section>

      {confirmingOp && (
        <ConfirmDialog
          title={`${confirmingOp.name}?`}
          body={`${confirmingOp.description}. This cannot be undone — there is no backup and no recycle bin on this instance.`}
          confirmLabel={`Yes, ${confirmingOp.verb}`}
          onConfirm={() => runOperation(confirmingOp.id)}
          onCancel={() => setConfirming(null)}
        />
      )}
    </div>
  );
}

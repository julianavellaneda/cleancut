"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, AdminStats, getAdminToken, setAdminToken } from "@/lib/api";

export default function AdminDashboard() {
  const router = useRouter();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [token, setToken] = useState("");

  useEffect(() => { loadStats(); }, []);

  // Read on mount rather than in the initial state so the server render and the
  // first client render agree; localStorage does not exist on the server.
  useEffect(() => { setToken(getAdminToken()); }, []);

  async function loadStats() {
    setLoading(true);
    try {
      const s = await api.getAdminStats();
      setStats(s);
    } catch {
      setError("Failed to load stats");
    } finally {
      setLoading(false);
    }
  }

  async function handleReset(type: 'database' | 'storage' | 'all') {
    if (!window.confirm(`Reset ${type}? Action is final.`)) return;
    setResetting(true);
    try {
      let result;
      if (type === 'database') result = await api.resetDatabase();
      else if (type === 'storage') result = await api.clearStorage();
      else result = await api.resetAll();
      setMessage(result.message);
      await loadStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="container max-w-4xl mx-auto py-12 px-6 space-y-12">
      <header className="flex items-center justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold">Admin Dashboard</h1>
          <p className="text-sm text-muted-foreground">System maintenance and data management.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => router.push("/")}>Exit Admin</Button>
      </header>

      {/* Destructive actions need the server's ADMIN_TOKEN. A server with none
          configured refuses them outright (503) rather than accepting anything,
          so this stays a field on a working dashboard rather than a login wall
          in front of the stats. */}
      <div className="rounded-md border p-4 space-y-2">
        <label htmlFor="admin-token" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Admin token
        </label>
        <div className="flex gap-2">
          <input
            id="admin-token"
            type="password"
            value={token}
            placeholder="The ADMIN_TOKEN configured on the server"
            onChange={(e) => {
              setToken(e.target.value);
              setAdminToken(e.target.value);
              setError(null);
            }}
            className="flex-1 rounded-md border bg-background px-3 py-2 text-sm"
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Sent as <code className="font-mono">X-Admin-Token</code> on reset requests. Stored in this
          browser only.
        </p>
      </div>

      {error && <div className="p-4 bg-destructive/10 text-destructive text-sm rounded-md font-medium">{error}</div>}
      {message && <div className="p-4 bg-primary/10 text-primary text-sm rounded-md font-medium">{message}</div>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {[
          { label: "Jobs", value: stats?.total_jobs },
          { label: "Markers", value: stats?.total_violations },
          { label: "Storage", value: `${((stats?.total_uploads_size_mb || 0) + (stats?.total_exports_size_mb || 0)).toFixed(1)} MB` }
        ].map(s => (
          <Card key={s.label}>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">{s.label}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{loading ? "..." : s.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="border-destructive/20">
        <CardHeader>
          <CardTitle className="text-destructive">Danger Zone</CardTitle>
          <CardDescription>Destructive actions that wipe system data.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {[
            { id: 'database', title: "Reset Database", desc: "Clear all job records and markers." },
            { id: 'storage', title: "Clear Storage", desc: "Purge all media files from volume." },
            { id: 'all', title: "System Wipe", desc: "Full factory reset of all data." }
          ].map(op => (
            <div key={op.id} className="flex items-center justify-between p-4 border rounded-md hover:bg-muted/30 transition-all">
              <div>
                <div className="text-sm font-semibold">{op.title}</div>
                <div className="text-xs text-muted-foreground">{op.desc}</div>
              </div>
              <Button variant="destructive" size="sm" onClick={() => handleReset(op.id as 'database' | 'storage' | 'all')} disabled={resetting}>Run</Button>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, AdminStats } from "@/lib/api";

export default function AdminDashboard() {
  const router = useRouter();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    loadStats();
  }, []);

  async function loadStats() {
    setLoading(true);
    try {
      const s = await api.getAdminStats();
      setStats(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load stats");
    } finally {
      setLoading(false);
    }
  }

  async function handleReset(type: 'database' | 'storage' | 'all') {
    const confirmation = window.confirm(
      `Are you sure you want to reset ${type}? This action cannot be undone.`
    );
    
    if (!confirmation) return;

    setResetting(true);
    setError(null);
    setMessage(null);

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
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold mb-2">Admin Dashboard</h1>
            <p className="text-muted-foreground">
              Manage application data and system storage
            </p>
          </div>
          <Button variant="outline" onClick={() => router.push("/")}>
            Back to App
          </Button>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-destructive/10 text-destructive rounded-lg">
            {error}
          </div>
        )}

        {message && (
          <div className="mb-6 p-4 bg-green-500/10 text-green-600 dark:text-green-400 rounded-lg">
            {message}
          </div>
        )}

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Jobs
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {loading ? "..." : stats?.total_jobs}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Violations
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {loading ? "..." : stats?.total_violations}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Storage Used
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {loading ? "..." : `${((stats?.total_uploads_size_mb || 0) + (stats?.total_exports_size_mb || 0)).toFixed(2)} MB`}
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                {stats?.files_count} files in uploads/exports
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Status Breakdown */}
        {stats && Object.keys(stats.jobs_by_status).length > 0 && (
          <Card className="mb-8">
            <CardHeader>
              <CardTitle>Job Status Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-4">
                {Object.entries(stats.jobs_by_status).map(([status, count]) => (
                  <div key={status} className="flex items-center gap-2 px-3 py-1 bg-muted rounded-full text-sm">
                    <span className="font-semibold capitalize">{status}:</span>
                    <span>{count}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Actions */}
        <Card border-destructive>
          <CardHeader>
            <CardTitle className="text-destructive">Danger Zone</CardTitle>
            <CardDescription>
              These actions are destructive and cannot be undone.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-col md:flex-row md:items-center justify-between p-4 border rounded-lg gap-4">
              <div>
                <div className="font-semibold">Reset Database</div>
                <div className="text-sm text-muted-foreground">
                  Delete all jobs and violation records. Audio files will remain.
                </div>
              </div>
              <Button 
                variant="destructive" 
                onClick={() => handleReset('database')}
                disabled={resetting}
              >
                Reset Database
              </Button>
            </div>

            <div className="flex flex-col md:flex-row md:items-center justify-between p-4 border rounded-lg gap-4">
              <div>
                <div className="font-semibold">Clear Storage</div>
                <div className="text-sm text-muted-foreground">
                  Delete all uploaded and exported audio files. Database records will remain (but audio won't play).
                </div>
              </div>
              <Button 
                variant="destructive" 
                onClick={() => handleReset('storage')}
                disabled={resetting}
              >
                Clear Storage
              </Button>
            </div>

            <div className="flex flex-col md:flex-row md:items-center justify-between p-4 border rounded-lg gap-4 bg-destructive/5">
              <div>
                <div className="font-semibold">Reset Everything</div>
                <div className="text-sm text-muted-foreground">
                  Wipe all database records and all storage files. Fresh start.
                </div>
              </div>
              <Button 
                variant="destructive" 
                className="font-bold"
                onClick={() => handleReset('all')}
                disabled={resetting}
              >
                SYSTEM RESET
              </Button>
            </div>
          </CardContent>
        </Card>

        <div className="mt-8 text-center text-xs text-muted-foreground">
          Note: This dashboard is currently not authenticated. Adding authentication is required for production.
        </div>
      </div>
    </div>
  );
}

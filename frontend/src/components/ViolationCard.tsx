"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Violation } from "@/lib/api";

interface ViolationCardProps {
  violation: Violation;
  onAccept: () => void;
  onReject: () => void;
  onPlayClip: () => void;
  isUpdating: boolean;
}

export function ViolationCard({
  violation,
  onAccept,
  onReject,
  onPlayClip,
  isUpdating,
}: ViolationCardProps) {
  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  function getSeverityBadge(severity: string | null) {
    const variant = severity?.toLowerCase() === "high"
      ? "destructive"
      : severity?.toLowerCase() === "medium"
      ? "default"
      : "secondary";

    return (
      <Badge variant={variant}>
        {severity?.toUpperCase() || "UNKNOWN"}
      </Badge>
    );
  }

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Selected Violation</CardTitle>
          {getSeverityBadge(violation.severity)}
        </div>
      </CardHeader>

      <CardContent className="flex-1 flex flex-col space-y-4">
        {/* Rule Info */}
        <div>
          <div className="text-sm text-muted-foreground mb-1">Rule Violated</div>
          <div className="font-medium">{violation.rule_violated || "Unknown"}</div>
        </div>

        {/* Time */}
        <div>
          <div className="text-sm text-muted-foreground mb-1">Timestamp</div>
          <div className="font-mono">
            {formatTime(violation.start_time)} - {formatTime(violation.end_time)}
          </div>
        </div>

        {/* Quoted Text */}
        <div>
          <div className="text-sm text-muted-foreground mb-1">Flagged Text</div>
          <div className="p-3 bg-muted/50 rounded-lg text-sm italic">
            &ldquo;{violation.text}&rdquo;
          </div>
        </div>

        {/* AI Reasoning */}
        {violation.reasoning && (
          <div>
            <div className="text-sm text-muted-foreground mb-1">
              AI Reasoning
            </div>
            <div className="p-3 bg-blue-50 dark:bg-blue-950/30 rounded-lg text-sm">
              💡 {violation.reasoning}
            </div>
          </div>
        )}

        {/* Status */}
        {violation.status !== "pending" && (
          <div>
            <div className="text-sm text-muted-foreground mb-1">Status</div>
            <Badge
              variant={violation.status === "accepted" ? "default" : "secondary"}
              className={
                violation.status === "accepted"
                  ? "bg-green-600"
                  : ""
              }
            >
              {violation.status === "accepted" ? "✓ Accepted" : "✗ Rejected"}
            </Badge>
          </div>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Actions */}
        <div className="space-y-3 pt-4 border-t">
          <Button
            variant="outline"
            className="w-full"
            onClick={onPlayClip}
          >
            ▶ Play Clip
          </Button>

          {violation.status === "pending" && (
            <div className="flex gap-2">
              <Button
                variant="default"
                className="flex-1 bg-green-600 hover:bg-green-700"
                onClick={onAccept}
                disabled={isUpdating}
              >
                ✓ Accept
              </Button>
              <Button
                variant="outline"
                className="flex-1"
                onClick={onReject}
                disabled={isUpdating}
              >
                ✗ Reject
              </Button>
            </div>
          )}

          {violation.status !== "pending" && (
            <Button
              variant="ghost"
              className="w-full text-muted-foreground"
              onClick={violation.status === "accepted" ? onReject : onAccept}
              disabled={isUpdating}
            >
              {violation.status === "accepted" ? "Undo (Reject)" : "Undo (Accept)"}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

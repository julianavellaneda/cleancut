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

  function getActionBadge(action: string | null) {
    const variant = action?.toLowerCase() === "cut"
      ? "destructive"
      : "secondary";

    return (
      <Badge variant={variant} className="uppercase">
        {action || "CUT"}
      </Badge>
    );
  }

  return (
    <Card className="h-full flex flex-col border-none shadow-none bg-transparent">
      <CardHeader className="pb-3 px-0">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">Edit Details</CardTitle>
          {getActionBadge(violation.action)}
        </div>
      </CardHeader>

      <CardContent className="flex-1 flex flex-col space-y-4 px-0">
        {/* Label Info */}
        <div>
          <div className="text-xs text-muted-foreground mb-1 uppercase tracking-wider font-semibold">Label</div>
          <div className="font-medium text-base">{violation.label || "Suggested Edit"}</div>
        </div>

        {/* Time */}
        <div>
          <div className="text-xs text-muted-foreground mb-1 uppercase tracking-wider font-semibold">Timestamp</div>
          <div className="font-mono text-sm">
            {formatTime(violation.start_time)} - {formatTime(violation.end_time)}
          </div>
        </div>

        {/* Quoted Text */}
        <div>
          <div className="text-xs text-muted-foreground mb-1 uppercase tracking-wider font-semibold">Segment Content</div>
          <div className="p-4 bg-muted/50 rounded-lg text-sm italic leading-relaxed">
            &ldquo;{violation.text}&rdquo;
          </div>
        </div>

        {/* Reasoning */}
        {violation.reasoning && (
          <div>
            <div className="text-xs text-muted-foreground mb-1 uppercase tracking-wider font-semibold">
              Reasoning
            </div>
            <div className="p-4 bg-blue-50 dark:bg-blue-950/30 rounded-lg text-sm border border-blue-100 dark:border-blue-900/50">
              💡 {violation.reasoning}
            </div>
          </div>
        )}

        {/* Status */}
        {violation.status !== "pending" && (
          <div>
            <div className="text-xs text-muted-foreground mb-1 uppercase tracking-wider font-semibold">Status</div>
            <Badge
              variant={violation.status === "accepted" ? "default" : "secondary"}
              className={
                violation.status === "accepted"
                  ? "bg-green-600 hover:bg-green-600"
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
        <div className="space-y-3 pt-6 border-t">
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
              size="sm"
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

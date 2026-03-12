"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Violation } from "@/lib/api";
import { cn } from "@/lib/utils";

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
      <Badge variant={variant} className="uppercase font-semibold">
        {action || "CUT"}
      </Badge>
    );
  }

  return (
    <Card className="h-full flex flex-col border shadow-sm">
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xl font-bold">
            {violation.label || "Suggested Edit"}
          </CardTitle>
          {getActionBadge(violation.action)}
        </div>
      </CardHeader>

      <CardContent className="flex-1 flex flex-col space-y-6">
        {/* Time & Text */}
        <div className="space-y-1">
          <div className="text-xs text-muted-foreground font-mono">
            {formatTime(violation.start_time)} — {formatTime(violation.end_time)}
          </div>
          <div className="text-sm italic leading-relaxed text-muted-foreground p-4 bg-muted/50 rounded-md">
            &ldquo;{violation.text}&rdquo;
          </div>
        </div>

        {/* Reasoning */}
        {violation.reasoning && (
          <div className="space-y-1">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Reasoning</div>
            <div className="text-sm p-4 bg-primary/5 rounded-md border text-foreground/80">
              {violation.reasoning}
            </div>
          </div>
        )}

        {/* Status */}
        {violation.status !== "pending" && (
          <div className="flex items-center gap-2">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Status:</div>
            <Badge
              variant={violation.status === "accepted" ? "default" : "outline"}
              className="px-2 py-0"
            >
              {violation.status === "accepted" ? "Accepted" : "Rejected"}
            </Badge>
          </div>
        )}

        {/* Actions */}
        <div className="pt-6 border-t mt-auto space-y-3">
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
                className="flex-1"
                onClick={onAccept}
                disabled={isUpdating}
              >
                Accept
              </Button>
              <Button
                variant="outline"
                className="flex-1 text-destructive hover:bg-destructive/5"
                onClick={onReject}
                disabled={isUpdating}
              >
                Reject
              </Button>
            </div>
          )}

          {violation.status !== "pending" && (
            <Button
              variant="ghost"
              size="sm"
              className="w-full text-xs text-muted-foreground"
              onClick={violation.status === "accepted" ? onReject : onAccept}
              disabled={isUpdating}
            >
              Undo Status
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

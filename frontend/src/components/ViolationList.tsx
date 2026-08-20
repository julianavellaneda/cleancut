"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Violation } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Labels produced by the deterministic scrubber - safe to bulk-accept. */
export const SCRUB_LABELS = ["Filler Word", "Dead Air"];

interface ViolationListProps {
  violations: Violation[];
  selectedViolation: Violation | null;
  onSelect: (violation: Violation) => void;
  onCleanAll: () => void;
  isCleaning: boolean;
}

export function ViolationList({
  violations,
  selectedViolation,
  onSelect,
  onCleanAll,
  isCleaning,
}: ViolationListProps) {
  const pendingScrubCount = violations.filter(
    (v) => v.status === "pending" && v.label && SCRUB_LABELS.includes(v.label)
  ).length;

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
      <Badge variant={variant} className="text-[10px] h-4 px-1 leading-none">
        {action || "CUT"}
      </Badge>
    );
  }

  function getSeverityPill(severity: string | null) {
    if (!severity) return null;
    const level = severity.toLowerCase();
    const variant =
      level === "high" ? "destructive" :
      level === "medium" ? "default" :
      "secondary";
    return (
      <Badge variant={variant} className="text-[10px] h-4 px-1 leading-none uppercase">
        {severity}
      </Badge>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b space-y-3">
        <h3 className="font-semibold text-sm">
          Suggested Edits ({violations.length})
        </h3>
        {pendingScrubCount > 0 && (
          <Button
            size="sm"
            variant="secondary"
            className="w-full text-xs"
            onClick={onCleanAll}
            disabled={isCleaning}
            title="Accept every pending filler word and dead-air edit"
          >
            {isCleaning
              ? "Cleaning..."
              : `Clean All (${pendingScrubCount})`}
          </Button>
        )}
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {violations.length === 0 ? (
            <div className="p-4 text-center text-muted-foreground text-sm">
              No edits suggested
            </div>
          ) : (
            violations.map((v) => (
              <div
                key={v.id}
                className={cn(
                  "p-3 rounded-md cursor-pointer transition-colors border",
                  selectedViolation?.id === v.id
                    ? "bg-accent border-accent-foreground/20"
                    : "border-transparent hover:bg-muted"
                )}
                onClick={() => onSelect(v)}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-muted-foreground font-mono">
                    {formatTime(v.start_time)}
                  </span>
                  <div className="flex items-center gap-1.5">
                    {v.status !== "pending" && (
                      <span className="text-[10px] font-medium text-muted-foreground">
                        {v.status === "accepted" ? "✓" : "✗"}
                      </span>
                    )}
                    {getSeverityPill(v.severity)}
                    {getActionBadge(v.action)}
                  </div>
                </div>
                <div className="text-xs font-medium truncate">
                  {v.label || "Suggested Edit"}
                </div>
                <div className="text-[10px] text-muted-foreground line-clamp-1 mt-1 italic">
                  &ldquo;{v.text}&rdquo;
                </div>
              </div>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

"use client";

import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Violation } from "@/lib/api";

interface ViolationListProps {
  violations: Violation[];
  selectedViolation: Violation | null;
  onSelect: (violation: Violation) => void;
}

export function ViolationList({
  violations,
  selectedViolation,
  onSelect,
}: ViolationListProps) {
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
      <Badge variant={variant} className="text-xs">
        {severity?.toUpperCase() || "?"}
      </Badge>
    );
  }

  function getStatusIcon(status: string) {
    switch (status) {
      case "accepted":
        return "✓";
      case "rejected":
        return "✗";
      default:
        return "";
    }
  }

  return (
    <div className="h-full flex flex-col">
      <div className="p-4 border-b">
        <h3 className="font-semibold">
          Violations ({violations.length})
        </h3>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {violations.length === 0 ? (
            <div className="p-4 text-center text-muted-foreground">
              No violations found
            </div>
          ) : (
            violations.map((v) => (
              <div
                key={v.id}
                className={`p-3 rounded-lg cursor-pointer transition-colors ${
                  selectedViolation?.id === v.id
                    ? "bg-primary/10 border border-primary"
                    : "hover:bg-muted/50"
                } ${v.status === "rejected" ? "opacity-50" : ""}`}
                onClick={() => onSelect(v)}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-mono text-muted-foreground">
                    {formatTime(v.start_time)}
                  </span>
                  <div className="flex items-center gap-2">
                    {v.status !== "pending" && (
                      <span
                        className={`text-sm ${
                          v.status === "accepted"
                            ? "text-green-600"
                            : "text-muted-foreground"
                        }`}
                      >
                        {getStatusIcon(v.status)}
                      </span>
                    )}
                    {getSeverityBadge(v.severity)}
                  </div>
                </div>
                <div className="text-sm font-medium truncate">
                  {v.rule_violated || "Unknown Rule"}
                </div>
                <div className="text-xs text-muted-foreground truncate mt-1">
                  {v.text.substring(0, 50)}...
                </div>
              </div>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

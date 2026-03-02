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

  function getActionBadge(action: string | null) {
    const variant = action?.toLowerCase() === "cut"
      ? "destructive"
      : "secondary";

    return (
      <Badge variant={variant} className="text-[10px] h-4 px-1 leading-none uppercase">
        {action || "CUT"}
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
        <h3 className="font-semibold text-sm">
          Suggested Edits ({violations.length})
        </h3>
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
                className={`p-3 rounded-lg cursor-pointer transition-colors border ${
                  selectedViolation?.id === v.id
                    ? "bg-primary/5 border-primary"
                    : "border-transparent hover:bg-muted/50"
                } ${v.status === "rejected" ? "opacity-40 grayscale" : ""}`}
                onClick={() => onSelect(v)}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] font-mono text-muted-foreground">
                    {formatTime(v.start_time)}
                  </span>
                  <div className="flex items-center gap-1.5">
                    {v.status !== "pending" && (
                      <span
                        className={`text-xs font-bold ${
                          v.status === "accepted"
                            ? "text-green-600"
                            : "text-muted-foreground"
                        }`}
                      >
                        {getStatusIcon(v.status)}
                      </span>
                    )}
                    {getActionBadge(v.action)}
                  </div>
                </div>
                <div className="text-xs font-semibold truncate">
                  {v.label || "Suggested Edit"}
                </div>
                <div className="text-[10px] text-muted-foreground line-clamp-1 mt-1 italic">
                  "{v.text}"
                </div>
              </div>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}

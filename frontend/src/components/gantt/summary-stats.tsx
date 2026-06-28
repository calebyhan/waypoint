"use client";

import { Card, CardContent } from "@/components/ui/card";
import type { GanttTask } from "./gantt-types";

interface SummaryStatsProps {
  tasks: GanttTask[];
}

export function SummaryStats({ tasks }: SummaryStatsProps) {
  const total = tasks.length;
  const done = tasks.filter((t) => t.status === "done").length;
  const inReview = tasks.filter((t) => t.status === "in_review").length;
  const open = tasks.filter((t) => t.status === "open").length;
  const unassigned = tasks.filter((t) => !t.assignee).length;
  const overdue = tasks.filter((t) => {
    if (!t.end_date || t.status === "done") return false;
    return new Date(t.end_date) < new Date();
  }).length;
  const progressPct = total > 0 ? Math.round((done / total) * 100) : 0;

  const stats = [
    { label: "Total", value: total, color: "text-foreground" },
    { label: "Done", value: done, color: "text-emerald-500" },
    { label: "In Review", value: inReview, color: "text-blue-500" },
    { label: "Open", value: open, color: "text-muted-foreground" },
    { label: "Overdue", value: overdue, color: overdue > 0 ? "text-red-500" : "text-muted-foreground" },
    { label: "Unassigned", value: unassigned, color: unassigned > 0 ? "text-amber-500" : "text-muted-foreground" },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
      {stats.map((stat) => (
        <Card key={stat.label}>
          <CardContent className="px-4 py-3">
            <p className="text-xs text-muted-foreground">{stat.label}</p>
            <p className={`text-2xl font-bold ${stat.color}`}>{stat.value}</p>
          </CardContent>
        </Card>
      ))}
      <Card>
        <CardContent className="px-4 py-3">
          <p className="text-xs text-muted-foreground">Progress</p>
          <div className="flex items-baseline gap-1">
            <p className="text-2xl font-bold text-foreground">{progressPct}%</p>
          </div>
          <div className="mt-1 h-1.5 w-full rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

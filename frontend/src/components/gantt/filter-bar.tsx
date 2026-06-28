"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import type { GanttTask, GanttEpic } from "./gantt-types";
import type { ZoomLevel } from "./gantt-utils";

interface FilterBarProps {
  tasks: GanttTask[];
  epics: GanttEpic[];
  zoom: ZoomLevel;
  onZoomChange: (zoom: ZoomLevel) => void;
  filterAssignee: string;
  onFilterAssignee: (v: string) => void;
  filterEpic: string;
  onFilterEpic: (v: string) => void;
  filterStatus: string;
  onFilterStatus: (v: string) => void;
  filterPriority: string;
  onFilterPriority: (v: string) => void;
}

const ALL = "__all__";

export function FilterBar({
  tasks,
  epics,
  zoom,
  onZoomChange,
  filterAssignee,
  onFilterAssignee,
  filterEpic,
  onFilterEpic,
  filterStatus,
  onFilterStatus,
  filterPriority,
  onFilterPriority,
}: FilterBarProps) {
  const assignees = Array.from(new Set(tasks.map((t) => t.assignee).filter(Boolean) as string[])).sort();

  const hasFilters = filterAssignee || filterEpic || filterStatus || filterPriority;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select value={zoom} onValueChange={(v) => onZoomChange(v as ZoomLevel)}>
        <SelectTrigger className="w-28 h-8 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="week">Week</SelectItem>
          <SelectItem value="2week">2 Weeks</SelectItem>
          <SelectItem value="month">Month</SelectItem>
          <SelectItem value="quarter">Quarter</SelectItem>
        </SelectContent>
      </Select>

      <div className="h-4 w-px bg-border" />

      <Select value={filterAssignee || ALL} onValueChange={(v) => onFilterAssignee(v === ALL ? "" : v ?? "")}>
        <SelectTrigger className="w-32 h-8 text-xs">
          <SelectValue placeholder="Assignee" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All assignees</SelectItem>
          {assignees.map((a) => (
            <SelectItem key={a} value={a}>{a}</SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={filterEpic || ALL} onValueChange={(v) => onFilterEpic(v === ALL ? "" : v ?? "")}>
        <SelectTrigger className="w-36 h-8 text-xs">
          <SelectValue placeholder="Epic" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All epics</SelectItem>
          {epics.map((e) => (
            <SelectItem key={e.id} value={e.id}>{e.title}</SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={filterStatus || ALL} onValueChange={(v) => onFilterStatus(v === ALL ? "" : v ?? "")}>
        <SelectTrigger className="w-28 h-8 text-xs">
          <SelectValue placeholder="Status" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All status</SelectItem>
          <SelectItem value="open">Open</SelectItem>
          <SelectItem value="in_review">In Review</SelectItem>
          <SelectItem value="done">Done</SelectItem>
        </SelectContent>
      </Select>

      <Select value={filterPriority || ALL} onValueChange={(v) => onFilterPriority(v === ALL ? "" : v ?? "")}>
        <SelectTrigger className="w-28 h-8 text-xs">
          <SelectValue placeholder="Priority" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All priority</SelectItem>
          <SelectItem value="p0">P0</SelectItem>
          <SelectItem value="p1">P1</SelectItem>
          <SelectItem value="p2">P2</SelectItem>
        </SelectContent>
      </Select>

      {hasFilters && (
        <Button
          variant="ghost"
          size="sm"
          className="h-8 text-xs"
          onClick={() => {
            onFilterAssignee("");
            onFilterEpic("");
            onFilterStatus("");
            onFilterPriority("");
          }}
        >
          Clear filters
        </Button>
      )}
    </div>
  );
}

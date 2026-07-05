"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ExternalLink, X } from "lucide-react";
import type { GanttTask, GanttEpic } from "./gantt-types";

const PRIORITY_COLORS: Record<string, string> = {
  p0: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  p1: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  p2: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
};

const STATUS_ITEMS: Record<string, string> = {
  open: "Open",
  in_review: "In Review",
  done: "Done",
};

interface TaskDetailPanelProps {
  task: GanttTask;
  epic?: GanttEpic;
  allTasks?: GanttTask[];
  onClose: () => void;
  onStatusChange: (taskId: string, status: string) => void;
  onAssigneeChange: (taskId: string, assignee: string) => void;
  onScheduleChange: (taskId: string, startDate: string, endDate: string) => void;
  onUnlinkGithub?: (taskId: string, kind: "issue" | "pr", githubPrId?: string) => void;
  onResolveConflict?: (taskId: string, resolution: "keep_waypoint" | "keep_github") => void;
}

export function TaskDetailPanel({
  task,
  epic,
  allTasks,
  onClose,
  onStatusChange,
  onAssigneeChange,
  onScheduleChange,
  onUnlinkGithub,
  onResolveConflict,
}: TaskDetailPanelProps) {
  const depTitleMap = new Map<string, string>();
  if (allTasks) {
    for (const t of allTasks) depTitleMap.set(t.id, t.title);
  }

  return (
    <div className="flex h-full flex-col border-l border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="text-sm font-semibold truncate pr-2">{task.title}</h3>
        <Button variant="ghost" size="icon-xs" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {task.github_conflict && (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 space-y-2">
            <p className="text-xs font-medium text-amber-700 dark:text-amber-400">
              {task.github_conflict_reason ?? "This task conflicts with its linked GitHub issue."}
            </p>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => onResolveConflict?.(task.id, "keep_waypoint")}>
                Keep Waypoint
              </Button>
              <Button size="sm" variant="outline" onClick={() => onResolveConflict?.(task.id, "keep_github")}>
                Keep GitHub
              </Button>
            </div>
          </div>
        )}

        {task.github_sync_error && (
          <div className="rounded-md border border-red-500/40 bg-red-500/10 p-3">
            <p className="text-xs font-medium text-red-700 dark:text-red-400">
              Failed to sync to GitHub: {task.github_sync_error}
            </p>
          </div>
        )}

        {(task.github_issue || (task.github_prs && task.github_prs.length > 0)) && (
          <div>
            <Label className="text-xs text-muted-foreground">Linked GitHub</Label>
            <div className="mt-1 space-y-1.5">
              {task.github_issue && (
                <div className="flex items-center justify-between gap-2 rounded-md border border-border px-2 py-1.5">
                  <a
                    href={task.github_issue.html_url ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                    className="flex min-w-0 items-center gap-1.5 text-sm hover:underline"
                  >
                    <span className="shrink-0 text-muted-foreground">#{task.github_issue.number}</span>
                    <span className="truncate">{task.github_issue.title}</span>
                    <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" />
                  </a>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 shrink-0 px-2 text-xs"
                    onClick={() => onUnlinkGithub?.(task.id, "issue")}
                  >
                    Unlink
                  </Button>
                </div>
              )}
              {task.github_prs?.map((pr) => (
                <div key={pr.id} className="flex items-center justify-between gap-2 rounded-md border border-border px-2 py-1.5">
                  <a
                    href={pr.html_url ?? undefined}
                    target="_blank"
                    rel="noreferrer"
                    className="flex min-w-0 items-center gap-1.5 text-sm hover:underline"
                  >
                    <span className="shrink-0 text-muted-foreground">#{pr.number}</span>
                    <span className="truncate">{pr.title}</span>
                    <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" />
                  </a>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 shrink-0 px-2 text-xs"
                    onClick={() => onUnlinkGithub?.(task.id, "pr", pr.id)}
                  >
                    Unlink
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}

        {epic && (
          <div>
            <Label className="text-xs text-muted-foreground">Epic</Label>
            <p className="text-sm">{epic.title}</p>
          </div>
        )}

        <div className="flex gap-2">
          <Badge className={PRIORITY_COLORS[task.priority]}>{task.priority.toUpperCase()}</Badge>
          <Badge variant="outline">{STATUS_ITEMS[task.status] ?? task.status}</Badge>
        </div>

        {task.description && (
          <div>
            <Label className="text-xs text-muted-foreground">Description</Label>
            <p className="text-sm text-foreground/80">{task.description}</p>
          </div>
        )}

        <div>
          <Label className="text-xs text-muted-foreground">Status</Label>
          <Select
            value={task.status}
            onValueChange={(v) => { if (v) onStatusChange(task.id, v); }}
            items={STATUS_ITEMS}
          >
            <SelectTrigger className="h-8 mt-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="open">Open</SelectItem>
              <SelectItem value="in_review">In Review</SelectItem>
              <SelectItem value="done">Done</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className="text-xs text-muted-foreground">Assignee</Label>
          <Input
            className="h-8 mt-1"
            defaultValue={task.assignee ?? ""}
            placeholder="Unassigned"
            onBlur={(e) => {
              if (e.target.value !== (task.assignee ?? "")) {
                onAssigneeChange(task.id, e.target.value);
              }
            }}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs text-muted-foreground">Start Date</Label>
            <Input
              type="date"
              className="h-8 mt-1"
              defaultValue={task.start_date ?? ""}
              onChange={(e) => {
                const endDate = task.end_date ?? e.target.value;
                onScheduleChange(task.id, e.target.value, endDate);
              }}
            />
          </div>
          <div>
            <Label className="text-xs text-muted-foreground">End Date</Label>
            <Input
              type="date"
              className="h-8 mt-1"
              defaultValue={task.end_date ?? ""}
              onChange={(e) => {
                const startDate = task.start_date ?? e.target.value;
                onScheduleChange(task.id, startDate, e.target.value);
              }}
            />
          </div>
        </div>

        {task.estimated_days && (
          <div>
            <Label className="text-xs text-muted-foreground">Estimated Days</Label>
            <p className="text-sm">{task.estimated_days}d</p>
          </div>
        )}

        {task.dependencies.length > 0 && (
          <div>
            <Label className="text-xs text-muted-foreground">
              Dependencies ({task.dependencies.length})
            </Label>
            <ul className="mt-1 space-y-1">
              {task.dependencies.map((dep) => (
                <li key={dep} className="text-sm text-foreground/80">
                  {depTitleMap.get(dep) ?? dep.slice(0, 8)}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

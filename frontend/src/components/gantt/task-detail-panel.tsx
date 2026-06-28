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
import type { GanttTask, GanttEpic } from "./gantt-types";

const PRIORITY_COLORS: Record<string, string> = {
  p0: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  p1: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  p2: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
};

interface TaskDetailPanelProps {
  task: GanttTask;
  epic?: GanttEpic;
  onClose: () => void;
  onStatusChange: (taskId: string, status: string) => void;
  onAssigneeChange: (taskId: string, assignee: string) => void;
  onScheduleChange: (taskId: string, startDate: string, endDate: string) => void;
}

export function TaskDetailPanel({
  task,
  epic,
  onClose,
  onStatusChange,
  onAssigneeChange,
  onScheduleChange,
}: TaskDetailPanelProps) {
  return (
    <div className="flex h-full flex-col border-l border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h3 className="text-sm font-semibold truncate">{task.title}</h3>
        <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={onClose}>
          &times;
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {epic && (
          <div>
            <Label className="text-xs text-muted-foreground">Epic</Label>
            <p className="text-sm">{epic.title}</p>
          </div>
        )}

        <div className="flex gap-2">
          <Badge className={PRIORITY_COLORS[task.priority]}>{task.priority}</Badge>
          <Badge variant="outline">{task.status}</Badge>
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
            <Label className="text-xs text-muted-foreground">Dependencies</Label>
            <ul className="mt-1 space-y-1">
              {task.dependencies.map((dep) => (
                <li key={dep} className="text-xs text-muted-foreground">{dep}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

"use client";

import { useCallback, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { useSession } from "@/hooks/use-session";
import { useRealtimeDashboard } from "@/hooks/use-realtime-dashboard";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";
import { GanttChart } from "@/components/gantt";
import type { GanttTask, GanttEpic, ScheduleChange } from "@/components/gantt";
import { SummaryStats } from "@/components/gantt/summary-stats";
import { FilterBar } from "@/components/gantt/filter-bar";
import { TaskDetailPanel } from "@/components/gantt/task-detail-panel";
import type { ZoomLevel } from "@/components/gantt/gantt-utils";

interface EpicProgress {
  id: string;
  title: string;
  total_tasks: number;
  done_tasks: number;
  progress_pct: number;
}

interface GithubRef {
  number: number;
  title: string;
  state: string;
  merged?: boolean;
}

interface DashTask {
  id: string;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  assignee: string | null;
  epic_id: string;
  start_date: string | null;
  end_date: string | null;
  estimated_days: number | null;
  dependencies: string[];
  created_at: string;
  linked_issue: GithubRef | null;
  linked_pr: GithubRef | null;
}

interface MatchProposal {
  id: string;
  task_id: string;
  github_issue_id: string | null;
  github_pr_id: string | null;
  similarity_score: number;
}

interface Insight {
  type: string;
  task_id: string | null;
  priority: string;
  message: string;
}

interface DashboardResponse {
  epics: EpicProgress[];
  tasks: DashTask[];
  pending_proposals: MatchProposal[];
  unlinked_issues: GithubRef[];
  unlinked_prs: GithubRef[];
}

const PRIORITY_COLORS: Record<string, string> = {
  p0: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  p1: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  p2: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
};

export default function DashboardPage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();

  useRealtimeDashboard(id);

  const [zoom, setZoom] = useState<ZoomLevel>("2week");
  const [filterAssignee, setFilterAssignee] = useState("");
  const [filterEpic, setFilterEpic] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterPriority, setFilterPriority] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  const { data, isLoading } = useQuery<DashboardResponse>({
    queryKey: ["dashboard", id],
    queryFn: () => apiFetch(`/workspaces/${id}/dashboard`, { token: session!.access_token }),
    enabled: !!session,
  });

  const { data: insights = [] } = useQuery<Insight[]>({
    queryKey: ["insights", id],
    queryFn: () => apiFetch(`/workspaces/${id}/insights`, { token: session!.access_token }),
    enabled: !!session,
  });

  const scheduleMutation = useMutation({
    mutationFn: (change: ScheduleChange) =>
      apiFetch(`/workspaces/${id}/tasks/${change.taskId}/schedule`, {
        method: "PATCH",
        token: session!.access_token,
        body: JSON.stringify({
          start_date: change.start_date,
          end_date: change.end_date,
          ...(change.assignee ? { assignee: change.assignee } : {}),
        }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dashboard", id] }),
  });

  const statusMutation = useMutation({
    mutationFn: ({ taskId, status }: { taskId: string; status: string }) =>
      apiFetch(`/workspaces/${id}/tasks/${taskId}/status`, {
        method: "PATCH",
        token: session!.access_token,
        body: JSON.stringify({ status }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dashboard", id] }),
  });

  const assigneeMutation = useMutation({
    mutationFn: ({ taskId, assignee }: { taskId: string; assignee: string }) =>
      apiFetch(`/workspaces/${id}/tasks/${taskId}/assignee`, {
        method: "PATCH",
        token: session!.access_token,
        body: JSON.stringify({ assignee }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["dashboard", id] }),
  });

  const proposalMutation = useMutation({
    mutationFn: ({ proposalId, accept }: { proposalId: string; accept: boolean }) =>
      apiFetch(`/workspaces/${id}/match-proposals/${proposalId}/decide`, {
        method: "POST",
        token: session!.access_token,
        body: JSON.stringify({ accept }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard", id] });
      toast.success("Proposal updated");
    },
  });

  const handleScheduleChange = useCallback(
    (change: ScheduleChange) => {
      scheduleMutation.mutate(change);
    },
    [scheduleMutation],
  );

  const handleTaskClick = useCallback((taskId: string) => {
    setSelectedTaskId((prev) => (prev === taskId ? null : taskId));
  }, []);

  if (isLoading || !data) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading dashboard...</p>
      </div>
    );
  }

  const ganttTasks: GanttTask[] = data.tasks.map((t) => ({
    id: t.id,
    title: t.title,
    status: t.status,
    priority: t.priority,
    assignee: t.assignee,
    epic_id: t.epic_id,
    start_date: t.start_date,
    end_date: t.end_date,
    estimated_days: t.estimated_days,
    dependencies: t.dependencies ?? [],
  }));

  const ganttEpics: GanttEpic[] = data.epics.map((e) => ({
    id: e.id,
    title: e.title,
  }));

  const selectedTask = selectedTaskId
    ? data.tasks.find((t) => t.id === selectedTaskId)
    : null;
  const selectedEpic = selectedTask
    ? data.epics.find((e) => e.id === selectedTask.epic_id)
    : undefined;

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3">
        <h1 className="text-xl font-bold">Dashboard</h1>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => router.push(`/workspaces/${id}/reingest`)}>
            Re-ingest PRD
          </Button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: main area */}
        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="space-y-4 overflow-y-auto p-6">
            {/* Insights banner */}
            {insights.length > 0 && (
              <div className="flex gap-3 overflow-x-auto pb-1">
                {insights.map((insight, i) => (
                  <Card key={i} className="min-w-[260px] shrink-0">
                    <CardContent className="p-3 space-y-1">
                      <Badge className={PRIORITY_COLORS[insight.priority]} variant="secondary">
                        {insight.type.replace("_", " ")}
                      </Badge>
                      <p className="text-sm">{insight.message}</p>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}

            {/* Pending proposals */}
            {data.pending_proposals.length > 0 && (
              <div className="space-y-2">
                <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Pending Match Proposals
                </h2>
                {data.pending_proposals.map((p) => {
                  const task = data.tasks.find((t) => t.id === p.task_id);
                  return (
                    <Card key={p.id}>
                      <CardContent className="flex items-center justify-between p-3">
                        <p className="text-sm">
                          Link to &quot;{task?.title ?? p.task_id}&quot;? (score{" "}
                          {p.similarity_score.toFixed(2)})
                        </p>
                        <div className="flex gap-2">
                          <Button
                            size="sm"
                            onClick={() => proposalMutation.mutate({ proposalId: p.id, accept: true })}
                          >
                            Yes
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => proposalMutation.mutate({ proposalId: p.id, accept: false })}
                          >
                            No
                          </Button>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}

            {/* Summary stats */}
            <SummaryStats tasks={ganttTasks} />

            {/* Filter bar */}
            <FilterBar
              tasks={ganttTasks}
              epics={ganttEpics}
              zoom={zoom}
              onZoomChange={setZoom}
              filterAssignee={filterAssignee}
              onFilterAssignee={setFilterAssignee}
              filterEpic={filterEpic}
              onFilterEpic={setFilterEpic}
              filterStatus={filterStatus}
              onFilterStatus={setFilterStatus}
              filterPriority={filterPriority}
              onFilterPriority={setFilterPriority}
            />

            {/* Gantt chart */}
            <GanttChart
              tasks={ganttTasks}
              epics={ganttEpics}
              onScheduleChange={handleScheduleChange}
              onTaskClick={handleTaskClick}
              zoom={zoom}
              filterAssignee={filterAssignee || undefined}
              filterEpic={filterEpic || undefined}
              filterStatus={filterStatus || undefined}
              filterPriority={filterPriority || undefined}
            />
          </div>
        </div>

        {/* Right: task detail sidebar */}
        {selectedTask && (
          <div className="w-80 shrink-0 overflow-hidden">
            <TaskDetailPanel
              task={{
                id: selectedTask.id,
                title: selectedTask.title,
                description: selectedTask.description ?? undefined,
                status: selectedTask.status,
                priority: selectedTask.priority,
                assignee: selectedTask.assignee,
                epic_id: selectedTask.epic_id,
                start_date: selectedTask.start_date,
                end_date: selectedTask.end_date,
                estimated_days: selectedTask.estimated_days,
                dependencies: selectedTask.dependencies ?? [],
              }}
              epic={selectedEpic ? { id: selectedEpic.id, title: selectedEpic.title } : undefined}
              onClose={() => setSelectedTaskId(null)}
              onStatusChange={(taskId, status) => statusMutation.mutate({ taskId, status })}
              onAssigneeChange={(taskId, assignee) => assigneeMutation.mutate({ taskId, assignee })}
              onScheduleChange={(taskId, startDate, endDate) =>
                handleScheduleChange({ taskId, start_date: startDate, end_date: endDate })
              }
            />
          </div>
        )}
      </div>
    </div>
  );
}

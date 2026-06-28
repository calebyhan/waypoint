"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";

interface Task {
  id: string;
  epic_id: string;
  title: string;
  description: string | null;
  motivation?: string | null;
  deliverables?: string[];
  important_notes?: string[];
  estimated_days: number | null;
  priority: string;
  status: string;
  sort_order: number;
  dependencies: string[];
  version: number;
}

interface Epic {
  id: string;
  title: string;
  sort_order: number;
}

interface DecompositionEpic {
  title: string;
  tasks: {
    title: string;
    description: string;
    motivation?: string;
    deliverables?: string[];
    important_notes?: string[];
    estimated_days: number;
    priority: string;
    dependencies: string[];
  }[];
}

interface PlanResponse {
  source: "plan" | "decomposition";
  epics: Epic[];
  tasks: Task[];
  decomposition?: { summary?: string; epics: DecompositionEpic[] };
}

const PRIORITY_COLORS: Record<string, string> = {
  p0: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  p1: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  p2: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
};

export default function ProposalPage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();

  const [editingTask, setEditingTask] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [localTasks, setLocalTasks] = useState<Map<string, Partial<Task>>>(new Map());

  const { data: plan, isLoading } = useQuery<PlanResponse>({
    queryKey: ["plan", id],
    queryFn: () => apiFetch(`/workspaces/${id}/plan`, { token: session!.access_token }),
    enabled: !!session,
  });

  const isDecomposition = plan?.source === "decomposition";
  const epics = plan?.epics ?? [];
  const tasks = plan?.tasks ?? [];
  const decomposition = plan?.decomposition;

  const approveMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/workspaces/${id}/plan/approve`, {
        method: "POST",
        token: session!.access_token,
      }),
    onSuccess: () => {
      toast.success("Plan approved");
      queryClient.invalidateQueries({ queryKey: ["plan", id] });
      router.push(`/workspaces/${id}/dashboard`);
    },
    onError: () => toast.error("Failed to approve plan"),
  });

  const updateTaskMutation = useMutation({
    mutationFn: ({ taskId, updates }: { taskId: string; updates: Partial<Task> }) =>
      apiFetch(`/workspaces/${id}/tasks/${taskId}`, {
        method: "PATCH",
        token: session!.access_token,
        body: JSON.stringify(updates),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plan", id] });
      setEditingTask(null);
    },
    onError: (e) => {
      if (e instanceof Error && e.message.includes("modified by another")) {
        toast.error("Conflict: another user edited this task. Reloading...");
        queryClient.invalidateQueries({ queryKey: ["plan", id] });
      } else {
        toast.error("Failed to update task");
      }
    },
  });

  const deleteTaskMutation = useMutation({
    mutationFn: (taskId: string) =>
      apiFetch(`/workspaces/${id}/tasks/${taskId}`, {
        method: "DELETE",
        token: session!.access_token,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plan", id] }),
  });

  const createTaskMutation = useMutation({
    mutationFn: (data: { epic_id: string; title: string }) =>
      apiFetch(`/workspaces/${id}/tasks`, {
        method: "POST",
        token: session!.access_token,
        body: JSON.stringify(data),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plan", id] }),
  });

  const createEpicMutation = useMutation({
    mutationFn: (title: string) =>
      apiFetch(`/workspaces/${id}/epics`, {
        method: "POST",
        token: session!.access_token,
        body: JSON.stringify({ title }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plan", id] }),
  });

  const toggleCollapse = useCallback((epicId: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(epicId)) next.delete(epicId);
      else next.add(epicId);
      return next;
    });
  }, []);

  const handleLocalEdit = useCallback((taskId: string, field: string, value: string | number) => {
    setLocalTasks((prev) => {
      const next = new Map(prev);
      const existing = next.get(taskId) ?? {};
      next.set(taskId, { ...existing, [field]: value });
      return next;
    });
  }, []);

  const handleSaveTask = useCallback(
    (task: Task) => {
      const edits = localTasks.get(task.id);
      if (!edits) {
        setEditingTask(null);
        return;
      }
      updateTaskMutation.mutate({
        taskId: task.id,
        updates: { ...edits, version: task.version },
      });
      setLocalTasks((prev) => {
        const next = new Map(prev);
        next.delete(task.id);
        return next;
      });
    },
    [localTasks, updateTaskMutation],
  );

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading plan...</p>
      </div>
    );
  }

  const renderDecomposition = () => {
    if (!decomposition) return null;
    return (
      <div className="space-y-6">
        {decomposition.summary && (
          <Card>
            <CardHeader>
              <CardTitle>Business Justification</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground leading-relaxed">
                {decomposition.summary}
              </p>
            </CardContent>
          </Card>
        )}
        {decomposition.epics.map((epic, ei) => (
          <Card key={ei}>
            <CardHeader
              className="cursor-pointer"
              onClick={() => toggleCollapse(`d-${ei}`)}
            >
              <CardTitle className="flex items-center justify-between">
                <span>{epic.title}</span>
                <Badge variant="secondary">{epic.tasks.length} tasks</Badge>
              </CardTitle>
            </CardHeader>
            {!collapsed.has(`d-${ei}`) && (
              <CardContent className="space-y-3">
                {epic.tasks.map((task, ti) => (
                  <div
                    key={ti}
                    className="rounded-lg border p-4 space-y-2"
                  >
                    <div className="flex items-start justify-between">
                      <h4 className="font-medium">{task.title}</h4>
                      <div className="flex gap-2">
                        <Badge className={PRIORITY_COLORS[task.priority]}>
                          {task.priority}
                        </Badge>
                        <Badge variant="outline">
                          {task.estimated_days}d
                        </Badge>
                      </div>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {task.description}
                    </p>
                    {task.motivation && (
                      <p className="text-xs italic text-muted-foreground">
                        {task.motivation}
                      </p>
                    )}
                    {(task.deliverables?.length ?? 0) > 0 && (
                      <ul className="list-disc pl-5 text-sm space-y-0.5">
                        {task.deliverables?.map((d, di) => (
                          <li key={di}>{d}</li>
                        ))}
                      </ul>
                    )}
                    {(task.important_notes?.length ?? 0) > 0 && (
                      <ul className="list-disc pl-5 text-sm space-y-0.5 text-amber-700 dark:text-amber-400">
                        {task.important_notes?.map((n, ni) => (
                          <li key={ni}>{n}</li>
                        ))}
                      </ul>
                    )}
                    {task.dependencies.length > 0 && (
                      <p className="text-xs text-muted-foreground">
                        Depends on: {task.dependencies.join(", ")}
                      </p>
                    )}
                  </div>
                ))}
              </CardContent>
            )}
          </Card>
        ))}
      </div>
    );
  };

  const renderPlan = () => {
    return (
      <div className="space-y-6">
        {epics.map((epic) => {
          const epicTasks = tasks.filter((t) => t.epic_id === epic.id);
          return (
            <Card key={epic.id}>
              <CardHeader
                className="cursor-pointer"
                onClick={() => toggleCollapse(epic.id)}
              >
                <CardTitle className="flex items-center justify-between">
                  <span>{epic.title}</span>
                  <Badge variant="secondary">{epicTasks.length} tasks</Badge>
                </CardTitle>
              </CardHeader>
              {!collapsed.has(epic.id) && (
                <CardContent className="space-y-3">
                  {epicTasks.map((task) => {
                    const isEditing = editingTask === task.id;
                    const edits = localTasks.get(task.id) ?? {};
                    const displayTitle = edits.title ?? task.title;
                    const displayDesc = edits.description ?? task.description ?? "";
                    const displayDays = edits.estimated_days ?? task.estimated_days;
                    const displayPriority = (edits.priority ?? task.priority) as string;

                    return (
                      <div
                        key={task.id}
                        className="rounded-lg border p-4 space-y-2"
                      >
                        {isEditing ? (
                          <div className="space-y-3">
                            <Input
                              value={displayTitle}
                              onChange={(e) =>
                                handleLocalEdit(task.id, "title", e.target.value)
                              }
                              placeholder="Task title"
                            />
                            <Textarea
                              value={displayDesc}
                              onChange={(e) =>
                                handleLocalEdit(task.id, "description", e.target.value)
                              }
                              placeholder="Description"
                              rows={3}
                            />
                            <div className="flex gap-2">
                              <Input
                                type="number"
                                value={displayDays ?? ""}
                                onChange={(e) =>
                                  handleLocalEdit(
                                    task.id,
                                    "estimated_days",
                                    parseInt(e.target.value) || 0,
                                  )
                                }
                                placeholder="Days"
                                className="w-20"
                              />
                              <Select
                                value={displayPriority}
                                onValueChange={(v) => {
                                  if (v) handleLocalEdit(task.id, "priority", v);
                                }}
                              >
                                <SelectTrigger className="w-24">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  <SelectItem value="p0">p0</SelectItem>
                                  <SelectItem value="p1">p1</SelectItem>
                                  <SelectItem value="p2">p2</SelectItem>
                                </SelectContent>
                              </Select>
                            </div>
                            <div className="flex gap-2">
                              <Button
                                size="sm"
                                onClick={() => handleSaveTask(task)}
                                disabled={updateTaskMutation.isPending}
                              >
                                Save
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => {
                                  setEditingTask(null);
                                  setLocalTasks((prev) => {
                                    const next = new Map(prev);
                                    next.delete(task.id);
                                    return next;
                                  });
                                }}
                              >
                                Cancel
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <div className="flex items-start justify-between">
                              <h4
                                className="font-medium cursor-pointer hover:text-primary"
                                onClick={() => setEditingTask(task.id)}
                              >
                                {task.title}
                              </h4>
                              <div className="flex gap-2 items-center">
                                <Badge className={PRIORITY_COLORS[task.priority]}>
                                  {task.priority}
                                </Badge>
                                {task.estimated_days && (
                                  <Badge variant="outline">
                                    {task.estimated_days}d
                                  </Badge>
                                )}
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-6 px-2 text-xs text-destructive"
                                  onClick={() => deleteTaskMutation.mutate(task.id)}
                                >
                                  Delete
                                </Button>
                              </div>
                            </div>
                            {task.description && (
                              <p className="text-sm text-muted-foreground">
                                {task.description}
                              </p>
                            )}
                            {task.motivation && (
                              <p className="text-xs italic text-muted-foreground">
                                {task.motivation}
                              </p>
                            )}
                            {(task.deliverables?.length ?? 0) > 0 && (
                              <ul className="list-disc pl-5 text-sm space-y-0.5">
                                {task.deliverables?.map((d, di) => (
                                  <li key={di}>{d}</li>
                                ))}
                              </ul>
                            )}
                            {(task.important_notes?.length ?? 0) > 0 && (
                              <ul className="list-disc pl-5 text-sm space-y-0.5 text-amber-700 dark:text-amber-400">
                                {task.important_notes?.map((n, ni) => (
                                  <li key={ni}>{n}</li>
                                ))}
                              </ul>
                            )}
                          </>
                        )}
                      </div>
                    );
                  })}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full"
                    onClick={() => {
                      const title = prompt("Task title:");
                      if (title) createTaskMutation.mutate({ epic_id: epic.id, title });
                    }}
                  >
                    + Add Task
                  </Button>
                </CardContent>
              )}
            </Card>
          );
        })}
        <Button
          variant="outline"
          onClick={() => {
            const title = prompt("Epic title:");
            if (title) createEpicMutation.mutate(title);
          }}
        >
          + Add Epic
        </Button>
      </div>
    );
  };

  return (
    <div className="mx-auto max-w-3xl p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Proposal</h1>
          <p className="text-muted-foreground">
            {isDecomposition
              ? "Review the AI-generated plan. Click Approve to start tracking."
              : "Edit tasks inline. Click a task title to edit."}
          </p>
        </div>
      </div>

      {isDecomposition ? renderDecomposition() : renderPlan()}

      <Separator />

      <div className="flex justify-end">
        <Button
          size="lg"
          onClick={() => approveMutation.mutate()}
          disabled={approveMutation.isPending}
        >
          {approveMutation.isPending ? "Approving..." : "Approve Plan"}
        </Button>
      </div>
    </div>
  );
}

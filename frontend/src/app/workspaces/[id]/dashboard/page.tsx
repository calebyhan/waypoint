"use client";

import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { useSession } from "@/hooks/use-session";
import { useRealtimeDashboard } from "@/hooks/use-realtime-dashboard";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";

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
  status: string;
  priority: string;
  assignee: string | null;
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

interface DashboardResponse {
  epics: EpicProgress[];
  tasks: DashTask[];
  pending_proposals: MatchProposal[];
  unlinked_issues: GithubRef[];
  unlinked_prs: GithubRef[];
}

interface Insight {
  type: string;
  task_id: string | null;
  priority: string;
  message: string;
}

const PRIORITY_COLORS: Record<string, string> = {
  p0: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  p1: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
  p2: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
};

const STATUS_OPTIONS = ["open", "in_review", "done"];

export default function DashboardPage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();

  useRealtimeDashboard(id);

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

  if (isLoading || !data) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading dashboard...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl p-8 space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <Button variant="outline" onClick={() => router.push(`/workspaces/${id}/reingest`)}>
          Re-ingest PRD
        </Button>
      </div>

      {insights.length > 0 && (
        <div>
          <h2 className="mb-2 text-sm font-medium text-muted-foreground">
            Agent Insights
          </h2>
          <div className="flex gap-3 overflow-x-auto pb-2">
            {insights.map((insight, i) => (
              <Card key={i} className="min-w-[280px] shrink-0">
                <CardContent className="p-3 space-y-1">
                  <Badge className={PRIORITY_COLORS[insight.priority]} variant="secondary">
                    {insight.type.replace("_", " ")}
                  </Badge>
                  <p className="text-sm">{insight.message}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      )}

      {data.pending_proposals.length > 0 && (
        <div>
          <h2 className="mb-2 text-sm font-medium text-muted-foreground">
            Pending Match Proposals
          </h2>
          <div className="space-y-2">
            {data.pending_proposals.map((p) => {
              const task = data.tasks.find((t) => t.id === p.task_id);
              return (
                <Card key={p.id}>
                  <CardContent className="flex items-center justify-between p-3">
                    <p className="text-sm">
                      Link to task &quot;{task?.title ?? p.task_id}&quot;? (score{" "}
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
        </div>
      )}

      <div>
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">
          Epic Progress
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {data.epics.map((epic) => (
            <Card key={epic.id}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium flex justify-between">
                  <span>{epic.title}</span>
                  <span className="text-muted-foreground">
                    {epic.done_tasks}/{epic.total_tasks}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Progress value={epic.progress_pct} />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      <div>
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">Tasks</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Priority</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Assignee</TableHead>
              <TableHead>Issue</TableHead>
              <TableHead>PR</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.tasks.map((task) => (
              <TableRow key={task.id}>
                <TableCell className="font-medium">{task.title}</TableCell>
                <TableCell>
                  <Badge className={PRIORITY_COLORS[task.priority]}>
                    {task.priority}
                  </Badge>
                </TableCell>
                <TableCell>
                  <Select
                    value={task.status}
                    onValueChange={(v) => {
                      if (v) statusMutation.mutate({ taskId: task.id, status: v });
                    }}
                  >
                    <SelectTrigger className="w-32 h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {STATUS_OPTIONS.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell>
                  <Input
                    defaultValue={task.assignee ?? ""}
                    placeholder="Unassigned"
                    className="h-8 w-32"
                    onBlur={(e) => {
                      if (e.target.value !== (task.assignee ?? "")) {
                        assigneeMutation.mutate({
                          taskId: task.id,
                          assignee: e.target.value,
                        });
                      }
                    }}
                  />
                </TableCell>
                <TableCell>
                  {task.linked_issue ? (
                    <span className="text-sm">#{task.linked_issue.number}</span>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell>
                  {task.linked_pr ? (
                    <span className="text-sm">#{task.linked_pr.number}</span>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {(data.unlinked_issues.length > 0 || data.unlinked_prs.length > 0) && (
        <div>
          <h2 className="mb-2 text-sm font-medium text-muted-foreground">
            Unlinked GitHub Items
          </h2>
          <div className="space-y-1 text-sm">
            {data.unlinked_issues.map((i) => (
              <p key={i.number}>Issue #{i.number}: {i.title}</p>
            ))}
            {data.unlinked_prs.map((p) => (
              <p key={p.number}>PR #{p.number}: {p.title}</p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

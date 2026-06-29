"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus, Trash2, RefreshCw, AlertTriangle, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
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
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";

const ROLES = [
  { value: "frontend", label: "Frontend" },
  { value: "backend", label: "Backend" },
  { value: "fullstack", label: "Full Stack" },
  { value: "devops", label: "DevOps" },
  { value: "design", label: "Design" },
  { value: "qa", label: "QA" },
  { value: "pm", label: "PM" },
] as const;

const WEEKDAYS = [
  { value: "-1", label: "No preference" },
  { value: "0", label: "Monday" },
  { value: "1", label: "Tuesday" },
  { value: "2", label: "Wednesday" },
  { value: "3", label: "Thursday" },
  { value: "4", label: "Friday" },
] as const;

interface Workspace {
  id: string;
  name: string;
  repo_owner: string | null;
  repo_name: string | null;
  state: string;
  schedule_start_date: string | null;
  tickets_per_member_per_week: number;
  assign_day: number;
}

interface TeamMember {
  id?: string;
  name: string;
  role: string;
  weekly_capacity_hours: number;
}

export default function SettingsPage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();

  const [workspaceName, setWorkspaceName] = useState("");
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [teamDirty, setTeamDirty] = useState(false);

  const [startDate, setStartDate] = useState("");
  const [ticketsPerWeek, setTicketsPerWeek] = useState("");
  const [assignDay, setAssignDay] = useState(-1);
  const [scheduleDirty, setScheduleDirty] = useState(false);

  const { data: workspace, isLoading: wsLoading } = useQuery<Workspace>({
    queryKey: ["workspace", id],
    queryFn: () => apiFetch(`/workspaces/${id}`, { token: session!.access_token }),
    enabled: !!session,
  });

  const { data: existingTeam, isLoading: teamLoading } = useQuery<TeamMember[]>({
    queryKey: ["team", id],
    queryFn: () => apiFetch(`/workspaces/${id}/team`, { token: session!.access_token }),
    enabled: !!session,
  });

  useEffect(() => {
    if (workspace) setWorkspaceName(workspace.name);
  }, [workspace]);

  useEffect(() => {
    if (workspace && !scheduleDirty) {
      setStartDate(workspace.schedule_start_date ?? "");
      setTicketsPerWeek(
        workspace.tickets_per_member_per_week ? String(workspace.tickets_per_member_per_week) : "",
      );
      setAssignDay(workspace.assign_day ?? -1);
    }
  }, [workspace, scheduleDirty]);

  useEffect(() => {
    if (existingTeam && !teamDirty) {
      setTeamMembers(existingTeam.map((m) => ({ ...m })));
    }
  }, [existingTeam, teamDirty]);

  const renameMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/workspaces/${id}`, {
        method: "PATCH",
        token: session!.access_token,
        body: JSON.stringify({ name: workspaceName.trim() }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspace", id] });
      toast.success("Workspace renamed");
    },
    onError: () => toast.error("Failed to rename workspace"),
  });

  const teamSyncMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/workspaces/${id}/team/sync`, {
        method: "PUT",
        token: session!.access_token,
        body: JSON.stringify({
          members: teamMembers
            .filter((m) => m.name.trim())
            .map((m) => ({
              name: m.name,
              role: m.role,
              weekly_capacity_hours: m.weekly_capacity_hours,
            })),
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team", id] });
      setTeamDirty(false);
      toast.success("Team saved");
    },
    onError: () => toast.error("Failed to save team"),
  });

  const rescheduleMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/workspaces/${id}/reschedule`, {
        method: "POST",
        token: session!.access_token,
        body: JSON.stringify({
          start_date: startDate || null,
          tickets_per_member_per_week: parseFloat(ticketsPerWeek) || 0,
          assign_day: assignDay,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard", id] });
      queryClient.invalidateQueries({ queryKey: ["workspace", id] });
      setScheduleDirty(false);
      toast.success("Timeline restructured");
    },
    onError: () => toast.error("Failed to restructure timeline"),
  });

  const archiveMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/workspaces/${id}/archive`, {
        method: "POST",
        token: session!.access_token,
      }),
    onSuccess: () => {
      toast.success("Workspace archived");
      router.push("/workspaces");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/workspaces/${id}`, {
        method: "DELETE",
        token: session!.access_token,
      }),
    onSuccess: () => {
      toast.success("Workspace deleted");
      router.push("/workspaces");
    },
  });

  const addMember = useCallback(() => {
    setTeamMembers((prev) => [...prev, { name: "", role: "fullstack", weekly_capacity_hours: 40 }]);
    setTeamDirty(true);
  }, []);

  const updateMember = useCallback((index: number, field: keyof TeamMember, value: string | number) => {
    setTeamMembers((prev) => prev.map((m, i) => (i === index ? { ...m, [field]: value } : m)));
    setTeamDirty(true);
  }, []);

  const removeMember = useCallback((index: number) => {
    setTeamMembers((prev) => prev.filter((_, i) => i !== index));
    setTeamDirty(true);
  }, []);

  if (wsLoading || teamLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => router.push(`/workspaces/${id}/dashboard`)}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="text-xl font-bold">Settings</h1>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl space-y-6 p-6">
          {/* Workspace Name */}
          <Card>
            <CardHeader>
              <CardTitle>Workspace</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="ws-name">Name</Label>
                <div className="flex gap-2">
                  <Input
                    id="ws-name"
                    value={workspaceName}
                    onChange={(e) => setWorkspaceName(e.target.value)}
                  />
                  <Button
                    onClick={() => renameMutation.mutate()}
                    disabled={
                      !workspaceName.trim() ||
                      workspaceName === workspace?.name ||
                      renameMutation.isPending
                    }
                  >
                    {renameMutation.isPending ? "Saving..." : "Save"}
                  </Button>
                </div>
              </div>
              {workspace?.repo_owner && (
                <div className="space-y-1">
                  <Label>Connected Repository</Label>
                  <p className="text-sm text-muted-foreground">
                    {workspace.repo_owner}/{workspace.repo_name}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Team Members */}
          <Card>
            <CardHeader>
              <CardTitle>Team Members</CardTitle>
              <CardDescription>
                Manage your team for task assignment and scheduling
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {teamMembers.map((member, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    placeholder="Name"
                    value={member.name}
                    onChange={(e) => updateMember(i, "name", e.target.value)}
                    className="flex-1"
                  />
                  <Select
                    value={member.role}
                    onValueChange={(v) => v && updateMember(i, "role", v)}
                  >
                    <SelectTrigger className="w-32">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ROLES.map((r) => (
                        <SelectItem key={r.value} value={r.value}>
                          {r.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    type="number"
                    value={member.weekly_capacity_hours}
                    onChange={(e) => updateMember(i, "weekly_capacity_hours", parseInt(e.target.value) || 0)}
                    className="w-20"
                    title="Weekly hours"
                  />
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => removeMember(i)}
                  >
                    <Trash2 className="h-4 w-4 text-muted-foreground" />
                  </Button>
                </div>
              ))}
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={addMember}>
                  <Plus className="mr-1.5 h-3.5 w-3.5" />
                  Add Member
                </Button>
                {teamDirty && (
                  <Button
                    size="sm"
                    onClick={() => teamSyncMutation.mutate()}
                    disabled={teamSyncMutation.isPending}
                  >
                    {teamSyncMutation.isPending ? "Saving..." : "Save Team"}
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Scheduling & Restructure */}
          <Card>
            <CardHeader>
              <CardTitle>Timeline</CardTitle>
              <CardDescription>
                Adjust scheduling parameters and restructure the timeline
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="start-date">Project Start Date</Label>
                  <Input
                    id="start-date"
                    type="date"
                    value={startDate}
                    onChange={(e) => {
                      setStartDate(e.target.value);
                      setScheduleDirty(true);
                    }}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="tickets-per-week">Tickets / Member / Week</Label>
                  <Input
                    id="tickets-per-week"
                    type="number"
                    min={0}
                    step={0.5}
                    value={ticketsPerWeek}
                    onChange={(e) => {
                      setTicketsPerWeek(e.target.value);
                      setScheduleDirty(true);
                    }}
                  />
                  <p className="text-xs text-muted-foreground">
                    0 = no pacing (back-to-back)
                  </p>
                </div>
              </div>
              <div className="space-y-2">
                <Label>Preferred Start Day</Label>
                <Select
                  value={String(assignDay)}
                  onValueChange={(v) => {
                    if (v) {
                      setAssignDay(parseInt(v));
                      setScheduleDirty(true);
                    }
                  }}
                >
                  <SelectTrigger className="w-48">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WEEKDAYS.map((d) => (
                      <SelectItem key={d.value} value={d.value}>
                        {d.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Only applies when pacing is active
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  onClick={() => rescheduleMutation.mutate()}
                  disabled={rescheduleMutation.isPending}
                >
                  <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${rescheduleMutation.isPending ? "animate-spin" : ""}`} />
                  {rescheduleMutation.isPending ? "Restructuring..." : "Restructure Timeline"}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => router.push(`/workspaces/${id}/reingest`)}
                >
                  <FileText className="mr-1.5 h-3.5 w-3.5" />
                  Re-ingest PRD
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Danger Zone */}
          <Card className="border-red-200 dark:border-red-900">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-red-600 dark:text-red-400">
                <AlertTriangle className="h-4 w-4" />
                Danger Zone
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Archive workspace</p>
                  <p className="text-xs text-muted-foreground">
                    Hide from workspace list. Can be restored later.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (confirm("Archive this workspace?")) archiveMutation.mutate();
                  }}
                  disabled={archiveMutation.isPending}
                >
                  Archive
                </Button>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Delete workspace</p>
                  <p className="text-xs text-muted-foreground">
                    Permanently delete this workspace and all its data.
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="border-red-300 text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950"
                  onClick={() => {
                    if (confirm("Delete this workspace permanently? This cannot be undone."))
                      deleteMutation.mutate();
                  }}
                  disabled={deleteMutation.isPending}
                >
                  Delete
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

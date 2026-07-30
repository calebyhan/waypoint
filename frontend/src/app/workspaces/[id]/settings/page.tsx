"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Copy, Plus, Trash2, RefreshCw, AlertTriangle, FileText, UserPlus, X } from "lucide-react";
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
import { apiFetch, ApiError } from "@/lib/api";
import { ErrorState } from "@/components/ui/error-state";
import { toast } from "sonner";

/** Surface the backend's ApiError.detail in toasts so distinct failure modes read distinctly. */
function toastApiError(fallback: string) {
  return (e: unknown) => {
    toast.error(e instanceof ApiError && e.detail ? e.detail : fallback);
  };
}

const ROLES = [
  { value: "frontend", label: "Frontend" },
  { value: "backend", label: "Backend" },
  { value: "fullstack", label: "Full Stack" },
  { value: "devops", label: "DevOps" },
  { value: "design", label: "Design" },
  { value: "qa", label: "QA" },
  { value: "pm", label: "PM" },
] as const;

const ROLE_ITEMS: Record<string, string> = Object.fromEntries(ROLES.map((r) => [r.value, r.label]));

const WEEKDAYS = [
  { value: "-1", label: "No preference" },
  { value: "0", label: "Monday" },
  { value: "1", label: "Tuesday" },
  { value: "2", label: "Wednesday" },
  { value: "3", label: "Thursday" },
  { value: "4", label: "Friday" },
] as const;

const WEEKDAY_ITEMS: Record<string, string> = Object.fromEntries(WEEKDAYS.map((d) => [d.value, d.label]));

const MEMBER_ROLE_ITEMS: Record<string, string> = { pm: "PM", member: "Member" };

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
  user_id?: string | null;
  /** Stable client-side key for list rendering (rows can be removed from the middle). */
  _key?: string;
}

interface Member {
  user_id: string;
  role: "owner" | "pm" | "member";
  github_username: string | null;
  avatar_url: string | null;
}

interface Invite {
  id: string;
  github_username: string;
  role: "pm" | "member";
  status: string;
  invite_url?: string;
  is_expired?: boolean;
}

/**
 * Copy text, falling back to a prompt where the async Clipboard API is
 * unavailable (it requires a secure context, so plain-HTTP deployments and
 * some in-app browsers don't have it). The invite link is useless if the PM
 * can't actually get it out of the page.
 */
async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the manual path
  }
  window.prompt("Copy this invite link:", text);
  return false;
}

const UNLINKED = "__unlinked__";

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

  const [inviteUsername, setInviteUsername] = useState("");
  const [inviteRole, setInviteRole] = useState<"pm" | "member">("member");

  const { data: workspace, isLoading: wsLoading, error: wsError } = useQuery<Workspace, ApiError>({
    queryKey: ["workspace", id],
    queryFn: () => apiFetch(`/workspaces/${id}`, { token: session!.access_token }),
    enabled: !!session,
  });

  const { data: existingTeam, isLoading: teamLoading } = useQuery<TeamMember[]>({
    queryKey: ["team", id],
    queryFn: () => apiFetch(`/workspaces/${id}/team`, { token: session!.access_token }),
    enabled: !!session,
  });

  const { data: members } = useQuery<Member[]>({
    queryKey: ["members", id],
    queryFn: () => apiFetch(`/workspaces/${id}/members`, { token: session!.access_token }),
    enabled: !!session,
  });

  const myRole = members?.find((m) => m.user_id === session?.user.id)?.role ?? "member";
  const canManage = myRole === "owner" || myRole === "pm";

  const { data: invites } = useQuery<Invite[]>({
    queryKey: ["invites", id],
    queryFn: () => apiFetch(`/workspaces/${id}/invites`, { token: session!.access_token }),
    enabled: !!session && canManage,
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
      setTeamMembers(existingTeam.map((m) => ({ ...m, _key: m.id ?? crypto.randomUUID() })));
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
    onError: toastApiError("Failed to rename workspace"),
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
              user_id: m.user_id ?? null,
            })),
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team", id] });
      setTeamDirty(false);
      toast.success("Team saved");
    },
    onError: toastApiError("Failed to save team"),
  });

  const inviteMutation = useMutation({
    mutationFn: () =>
      apiFetch<Invite>(`/workspaces/${id}/invites`, {
        method: "POST",
        token: session!.access_token,
        body: JSON.stringify({ github_username: inviteUsername.trim(), role: inviteRole }),
      }),
    onSuccess: async (invite) => {
      queryClient.invalidateQueries({ queryKey: ["invites", id] });
      const username = inviteUsername.trim();
      setInviteUsername("");

      // Waypoint has no way to contact someone who hasn't signed up (auth is
      // GitHub-only, so we hold no email address). The PM delivers the link.
      if (invite?.invite_url) {
        const copied = await copyToClipboard(invite.invite_url);
        toast.success(
          copied
            ? `Invite link copied — send it to @${username}`
            : `Invite created for @${username}`,
          { description: "They join by opening the link and signing in with GitHub." },
        );
      } else {
        toast.success(`Invite created for @${username}`);
      }
    },
    onError: toastApiError("Failed to create invite"),
  });

  const revokeInviteMutation = useMutation({
    mutationFn: (inviteId: string) =>
      apiFetch(`/workspaces/${id}/invites/${inviteId}`, {
        method: "DELETE",
        token: session!.access_token,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["invites", id] });
      toast.success("Invite revoked");
    },
    onError: toastApiError("Failed to revoke invite"),
  });

  const updateRoleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: "pm" | "member" }) =>
      apiFetch(`/workspaces/${id}/members/${userId}`, {
        method: "PATCH",
        token: session!.access_token,
        body: JSON.stringify({ role }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["members", id] });
      toast.success("Role updated");
    },
    onError: toastApiError("Failed to update role"),
  });

  const removeMemberMutation = useMutation({
    mutationFn: (userId: string) =>
      apiFetch(`/workspaces/${id}/members/${userId}`, {
        method: "DELETE",
        token: session!.access_token,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["members", id] });
      toast.success("Member removed");
    },
    onError: toastApiError("Failed to remove member"),
  });

  const linkTeamMemberMutation = useMutation({
    mutationFn: ({ memberId, userId }: { memberId: string; userId: string | null }) =>
      apiFetch(`/workspaces/${id}/team/${memberId}/link`, {
        method: "POST",
        token: session!.access_token,
        body: JSON.stringify({ user_id: userId }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team", id] });
      toast.success("Linked to account");
    },
    onError: toastApiError("Failed to link account"),
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
    onError: toastApiError("Failed to restructure timeline"),
  });

  const archiveMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/workspaces/${id}/archive`, {
        method: "POST",
        token: session!.access_token,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success("Workspace archived");
      router.push("/workspaces");
    },
    onError: toastApiError("Failed to archive workspace"),
  });

  const deleteMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/workspaces/${id}`, {
        method: "DELETE",
        token: session!.access_token,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success("Workspace deleted");
      router.push("/workspaces");
    },
    onError: toastApiError("Failed to delete workspace"),
  });

  const addMember = useCallback(() => {
    setTeamMembers((prev) => [
      ...prev,
      { name: "", role: "fullstack", weekly_capacity_hours: 40, _key: crypto.randomUUID() },
    ]);
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

  if (wsError) {
    return (
      <ErrorState
        message={wsError.detail}
        onRetry={() => queryClient.invalidateQueries({ queryKey: ["workspace", id] })}
      />
    );
  }

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
            aria-label="Back to dashboard"
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
                    disabled={!canManage}
                  />
                  <Button
                    onClick={() => renameMutation.mutate()}
                    disabled={
                      !canManage ||
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

          {/* Members */}
          <Card>
            <CardHeader>
              <CardTitle>Members</CardTitle>
              <CardDescription>
                People with access to this workspace and their permission level
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {members?.map((m) => (
                <div key={m.user_id} className="flex items-center gap-2">
                  <span className="flex-1 truncate text-sm">
                    {m.github_username ?? m.user_id}
                  </span>
                  {m.role === "owner" ? (
                    <span className="w-32 text-sm text-muted-foreground">Owner</span>
                  ) : (
                    <Select
                      value={m.role}
                      onValueChange={(v) =>
                        v && canManage && updateRoleMutation.mutate({ userId: m.user_id, role: v as "pm" | "member" })
                      }
                      disabled={!canManage}
                      items={MEMBER_ROLE_ITEMS}
                    >
                      <SelectTrigger className="w-32">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="pm">PM</SelectItem>
                        <SelectItem value="member">Member</SelectItem>
                      </SelectContent>
                    </Select>
                  )}
                  {canManage && m.role !== "owner" && (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Remove ${m.github_username ?? m.user_id} from the workspace`}
                      onClick={() => {
                        if (confirm(`Remove ${m.github_username ?? "this member"} from the workspace?`))
                          removeMemberMutation.mutate(m.user_id);
                      }}
                    >
                      <X className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  )}
                </div>
              ))}

              {canManage && (
                <>
                  <div className="flex gap-2 pt-2">
                    <Input
                      placeholder="GitHub username"
                      value={inviteUsername}
                      onChange={(e) => setInviteUsername(e.target.value)}
                      className="flex-1"
                      disabled={inviteMutation.isPending}
                    />
                    <Select
                      value={inviteRole}
                      onValueChange={(v) => v && setInviteRole(v as "pm" | "member")}
                      disabled={inviteMutation.isPending}
                      items={MEMBER_ROLE_ITEMS}
                    >
                      <SelectTrigger className="w-32">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="pm">PM</SelectItem>
                        <SelectItem value="member">Member</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button
                      onClick={() => inviteMutation.mutate()}
                      disabled={!inviteUsername.trim() || inviteMutation.isPending}
                    >
                      <UserPlus className="mr-1.5 h-3.5 w-3.5" />
                      Invite
                    </Button>
                  </div>

                  <p className="text-xs text-muted-foreground">
                    Waypoint can&apos;t email people — sign-in is GitHub-only. Creating an
                    invite gives you a link to send them yourself.
                  </p>

                  {invites && invites.length > 0 ? (
                    <div className="space-y-1.5 pt-1">
                      {invites.map((inv) => (
                        <div key={inv.id} className="flex items-center gap-2 text-sm text-muted-foreground">
                          <span className="flex-1">
                            {inv.github_username} · invited as {inv.role} ·{" "}
                            {inv.is_expired ? "expired" : "awaiting sign-in"}
                          </span>
                          {inv.invite_url && !inv.is_expired && (
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              aria-label={`Copy invite link for ${inv.github_username}`}
                              title="Copy invite link"
                              onClick={async () => {
                                const copied = await copyToClipboard(inv.invite_url!);
                                if (copied) toast.success("Invite link copied");
                              }}
                            >
                              <Copy className="h-4 w-4" />
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Revoke invite for ${inv.github_username}`}
                            onClick={() => {
                              if (confirm(`Revoke invite for ${inv.github_username}?`))
                                revokeInviteMutation.mutate(inv.id);
                            }}
                          >
                            <X className="h-4 w-4" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="pt-1 text-xs text-muted-foreground">No pending invites.</p>
                  )}
                </>
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
                <div key={member._key ?? member.id ?? member.name} className="flex items-center gap-2">
                  <Input
                    placeholder="Name"
                    value={member.name}
                    onChange={(e) => updateMember(i, "name", e.target.value)}
                    className="flex-1"
                    disabled={!canManage}
                  />
                  <Select
                    value={member.role}
                    onValueChange={(v) => v && updateMember(i, "role", v)}
                    disabled={!canManage}
                    items={ROLE_ITEMS}
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
                    disabled={!canManage}
                  />
                  {member.id && canManage && (
                    <Select
                      value={member.user_id ?? UNLINKED}
                      onValueChange={(v) =>
                        linkTeamMemberMutation.mutate({
                          memberId: member.id!,
                          userId: v === UNLINKED ? null : v,
                        })
                      }
                      items={{
                        [UNLINKED]: "Not linked",
                        ...Object.fromEntries(
                          (members ?? []).map((m) => [m.user_id, m.github_username ?? m.user_id]),
                        ),
                      }}
                    >
                      <SelectTrigger className="w-40" title="Link to account">
                        <SelectValue placeholder="Link to account" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={UNLINKED}>Not linked</SelectItem>
                        {members?.map((m) => (
                          <SelectItem key={m.user_id} value={m.user_id}>
                            {m.github_username ?? m.user_id}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                  {canManage && (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Remove team member ${member.name || "row"}`}
                      onClick={() => removeMember(i)}
                    >
                      <Trash2 className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  )}
                </div>
              ))}
              {canManage && (
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
              )}
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
                  items={WEEKDAY_ITEMS}
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
          <Card className="border-destructive/30">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-destructive">
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
                  disabled={!canManage || archiveMutation.isPending}
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
                  className="border-destructive/40 text-destructive hover:bg-destructive/10"
                  onClick={() => {
                    if (confirm("Delete this workspace permanently? This cannot be undone."))
                      deleteMutation.mutate();
                  }}
                  disabled={myRole !== "owner" || deleteMutation.isPending}
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

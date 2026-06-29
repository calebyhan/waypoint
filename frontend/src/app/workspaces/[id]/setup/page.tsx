"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";

const ROLES = [
  { value: "frontend", label: "Frontend" },
  { value: "backend", label: "Backend" },
  { value: "fullstack", label: "Full Stack" },
  { value: "devops", label: "DevOps" },
  { value: "design", label: "Design" },
  { value: "qa", label: "QA" },
  { value: "pm", label: "PM" },
] as const;

interface TeamMember {
  name: string;
  role: string;
  weekly_capacity_hours: number;
}

interface Repo {
  full_name: string;
  owner: string;
  name: string;
}

interface Workspace {
  id: string;
  name: string;
  repo_owner: string | null;
  repo_name: string | null;
  webhook_secret: string;
}

export default function WorkspaceSetupPage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [selectedRepo, setSelectedRepo] = useState("");
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [teamDirty, setTeamDirty] = useState(false);

  const { data: workspace } = useQuery<Workspace>({
    queryKey: ["workspace", id],
    queryFn: () =>
      apiFetch(`/workspaces/${id}`, { token: session!.access_token }),
    enabled: !!session,
  });

  const { data: repos = [], isLoading: reposLoading } = useQuery<Repo[]>({
    queryKey: ["repos", id],
    queryFn: () =>
      apiFetch(`/workspaces/${id}/repos`, { token: session!.access_token }),
    enabled: !!session,
  });

  const { data: existingTeam } = useQuery<TeamMember[]>({
    queryKey: ["team", id],
    queryFn: () =>
      apiFetch(`/workspaces/${id}/team`, { token: session!.access_token }),
    enabled: !!session,
  });

  useEffect(() => {
    if (existingTeam && existingTeam.length > 0 && teamMembers.length === 0) {
      setTeamMembers(
        existingTeam.map((m) => ({
          name: m.name,
          role: m.role,
          weekly_capacity_hours: m.weekly_capacity_hours,
        })),
      );
    }
  }, [existingTeam, teamMembers.length]);

  const saveTeamMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/workspaces/${id}/team/sync`, {
        method: "PUT",
        token: session!.access_token,
        body: JSON.stringify({
          members: teamMembers.filter((m) => m.name.trim()),
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["team", id] });
      setTeamDirty(false);
      toast.success("Team saved");
    },
    onError: () => toast.error("Failed to save team"),
  });

  const addMember = () => {
    setTeamMembers((prev) => [
      ...prev,
      { name: "", role: "fullstack", weekly_capacity_hours: 40 },
    ]);
    setTeamDirty(true);
  };

  const updateMember = (index: number, field: keyof TeamMember, value: string | number) => {
    setTeamMembers((prev) =>
      prev.map((m, i) => (i === index ? { ...m, [field]: value } : m)),
    );
    setTeamDirty(true);
  };

  const removeMember = (index: number) => {
    setTeamMembers((prev) => prev.filter((_, i) => i !== index));
    setTeamDirty(true);
  };

  const connectMutation = useMutation({
    mutationFn: (repoFullName: string) => {
      const [owner, name] = repoFullName.split("/");
      return apiFetch(`/workspaces/${id}/connect-repo`, {
        method: "POST",
        token: session!.access_token,
        body: JSON.stringify({ repo_owner: owner, repo_name: name }),
      });
    },
    onSuccess: () => {
      toast.success("Repository connected");
    },
    onError: () => toast.error("Failed to connect repository"),
  });

  const webhookUrl =
    typeof window !== "undefined"
      ? `${process.env.NEXT_PUBLIC_API_URL}/webhooks/github`
      : "";

  const isConnected = workspace?.repo_owner || connectMutation.isSuccess;

  return (
    <div className="mx-auto max-w-2xl p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{workspace?.name ?? "Setup"}</h1>
        <p className="text-muted-foreground">
          Connect a GitHub repository and configure webhooks.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Connect Repository</CardTitle>
          <CardDescription>
            Choose the GitHub repo Waypoint will monitor.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {workspace?.repo_owner ? (
            <p className="text-sm">
              Connected to{" "}
              <span className="font-mono font-medium">
                {workspace.repo_owner}/{workspace.repo_name}
              </span>
            </p>
          ) : (
            <>
              <Select
                value={selectedRepo}
                onValueChange={(v) => setSelectedRepo(v ?? "")}
              >
                <SelectTrigger>
                  <SelectValue
                    placeholder={
                      reposLoading ? "Loading repos..." : "Select a repository"
                    }
                  />
                </SelectTrigger>
                <SelectContent>
                  {repos.map((repo) => (
                    <SelectItem key={repo.full_name} value={repo.full_name}>
                      {repo.full_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                onClick={() => connectMutation.mutate(selectedRepo)}
                disabled={
                  !selectedRepo || connectMutation.isPending
                }
              >
                {connectMutation.isPending ? "Connecting..." : "Connect"}
              </Button>
            </>
          )}
        </CardContent>
      </Card>

      {isConnected && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Configure Webhook</CardTitle>
              <CardDescription>
                Add this webhook in your GitHub repo settings under Webhooks.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Payload URL</Label>
                <Input readOnly value={webhookUrl} />
              </div>
              <div className="space-y-2">
                <Label>Secret</Label>
                <Input readOnly value={workspace?.webhook_secret ?? ""} />
              </div>
              <div className="space-y-1">
                <Label>Content type</Label>
                <p className="text-sm text-muted-foreground">
                  application/json
                </p>
              </div>
              <div className="space-y-1">
                <Label>Events</Label>
                <p className="text-sm text-muted-foreground">
                  Select &quot;Let me select individual events&quot; → check{" "}
                  <strong>Issues</strong> and <strong>Pull requests</strong>.
                </p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Team Members</CardTitle>
              <CardDescription>
                Manage your project team. Members and their specialties are used for ticket
                assignment during PRD ingestion.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {teamMembers.length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No team members yet. Add members here or during ingestion.
                </p>
              )}
              {teamMembers.map((member, i) => (
                <div key={i} className="flex items-end gap-2">
                  <div className="flex-1 space-y-1.5">
                    {i === 0 && <Label>Name</Label>}
                    <Input
                      placeholder="e.g. Alice"
                      value={member.name}
                      onChange={(e) => updateMember(i, "name", e.target.value)}
                    />
                  </div>
                  <div className="w-36 space-y-1.5">
                    {i === 0 && <Label>Role</Label>}
                    <Select
                      value={member.role}
                      onValueChange={(v) => updateMember(i, "role", v ?? member.role)}
                    >
                      <SelectTrigger className="w-full">
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
                  </div>
                  <div className="w-20 space-y-1.5">
                    {i === 0 && <Label>Hrs/wk</Label>}
                    <Input
                      type="number"
                      min={1}
                      max={60}
                      value={member.weekly_capacity_hours}
                      onChange={(e) =>
                        updateMember(i, "weekly_capacity_hours", parseInt(e.target.value) || 40)
                      }
                    />
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => removeMember(i)}
                    className="shrink-0"
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              ))}
              <Button variant="outline" onClick={addMember} className="w-full">
                <Plus className="size-4 mr-1.5" />
                Add Team Member
              </Button>
              {teamDirty && (
                <Button
                  onClick={() => saveTeamMutation.mutate()}
                  disabled={saveTeamMutation.isPending}
                >
                  {saveTeamMutation.isPending ? "Saving..." : "Save Team"}
                </Button>
              )}
            </CardContent>
          </Card>

          <Separator />

          <Button onClick={() => router.push(`/workspaces/${id}/ingest`)}>
            Continue to Ingest →
          </Button>
        </>
      )}
    </div>
  );
}

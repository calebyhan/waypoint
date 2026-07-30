"use client";

import { useState } from "react";
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
import { apiFetch, ApiError } from "@/lib/api";
import { ErrorState } from "@/components/ui/error-state";
import { reconnectGithub } from "@/lib/reconnect-github";
import { toast } from "sonner";

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

  const { data: workspace, error: wsError } = useQuery<Workspace, ApiError>({
    queryKey: ["workspace", id],
    queryFn: () =>
      apiFetch(`/workspaces/${id}`, { token: session!.access_token }),
    enabled: !!session,
  });

  const {
    data: repos = [],
    isLoading: reposLoading,
    error: reposError,
  } = useQuery<Repo[], ApiError>({
    queryKey: ["repos", id],
    queryFn: () =>
      apiFetch(`/workspaces/${id}/repos`, { token: session!.access_token }),
    enabled: !!session,
    retry: false,
  });

  const [reconnecting, setReconnecting] = useState(false);
  const handleReconnect = async () => {
    setReconnecting(true);
    const error = await reconnectGithub(window.location.pathname);
    if (error) {
      toast.error("Failed to start GitHub reconnect");
      setReconnecting(false);
    }
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
      queryClient.invalidateQueries({ queryKey: ["workspace", id] });
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success("Repository connected");
    },
    onError: () => toast.error("Failed to connect repository"),
  });

  const webhookUrl =
    typeof window !== "undefined"
      ? `${process.env.NEXT_PUBLIC_API_URL}/webhooks/github`
      : "";

  const isConnected = workspace?.repo_owner || connectMutation.isSuccess;

  if (wsError) {
    return (
      <ErrorState
        message={wsError.detail}
        onRetry={() => queryClient.invalidateQueries({ queryKey: ["workspace", id] })}
      />
    );
  }

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
          ) : reposError ? (
            <div className="space-y-3">
              <p className="text-sm text-destructive">
                {reposError.detail || "Couldn't load your GitHub repositories."}
              </p>
              <Button onClick={handleReconnect} disabled={reconnecting}>
                {reconnecting ? "Redirecting to GitHub..." : "Reconnect GitHub"}
              </Button>
            </div>
          ) : (
            <>
              <Select
                value={selectedRepo}
                onValueChange={(v) => setSelectedRepo(v ?? "")}
                items={Object.fromEntries(repos.map((repo) => [repo.full_name, repo.full_name]))}
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

          <Separator />

          <Button onClick={() => router.push(`/workspaces/${id}/ingest`)}>
            Continue to Ingest →
          </Button>
        </>
      )}
    </div>
  );
}

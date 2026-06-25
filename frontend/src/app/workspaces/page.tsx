"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { toast } from "sonner";

interface Workspace {
  id: string;
  name: string;
  state: string;
  repo_owner: string | null;
  repo_name: string | null;
  created_at: string;
}

export default function WorkspacesPage() {
  const { session, loading: sessionLoading } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [newName, setNewName] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);

  const { data: workspaces = [], isLoading } = useQuery<Workspace[]>({
    queryKey: ["workspaces"],
    queryFn: () =>
      apiFetch("/workspaces", { token: session!.access_token }),
    enabled: !!session,
  });

  const createMutation = useMutation({
    mutationFn: (name: string) =>
      apiFetch<Workspace>("/workspaces", {
        method: "POST",
        token: session!.access_token,
        body: JSON.stringify({ name }),
      }),
    onSuccess: (workspace) => {
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      setDialogOpen(false);
      setNewName("");
      router.push(`/workspaces/${workspace.id}/setup`);
    },
    onError: () => toast.error("Failed to create workspace"),
  });

  const handleSignOut = async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
  };

  if (sessionLoading || isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Workspaces</h1>
        <div className="flex gap-2">
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger render={<Button>New Workspace</Button>} />
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create Workspace</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 pt-2">
                <Input
                  placeholder="Project name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && newName.trim()) {
                      createMutation.mutate(newName.trim());
                    }
                  }}
                />
                <Button
                  onClick={() => createMutation.mutate(newName.trim())}
                  disabled={!newName.trim() || createMutation.isPending}
                  className="w-full"
                >
                  {createMutation.isPending ? "Creating..." : "Create"}
                </Button>
              </div>
            </DialogContent>
          </Dialog>
          <Button variant="ghost" onClick={handleSignOut}>
            Sign out
          </Button>
        </div>
      </div>

      {workspaces.length === 0 ? (
        <p className="mt-8 text-center text-muted-foreground">
          No workspaces yet. Create one to get started.
        </p>
      ) : (
        <div className="mt-6 grid gap-4">
          {workspaces.map((ws) => (
            <Card
              key={ws.id}
              className="cursor-pointer transition-colors hover:bg-muted/50"
              onClick={() =>
                router.push(
                  ws.repo_owner
                    ? `/workspaces/${ws.id}/ingest`
                    : `/workspaces/${ws.id}/setup`,
                )
              }
            >
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-lg">{ws.name}</CardTitle>
                  <Badge
                    variant={ws.state === "active" ? "default" : "secondary"}
                  >
                    {ws.state}
                  </Badge>
                </div>
                <CardDescription>
                  {ws.repo_owner
                    ? `${ws.repo_owner}/${ws.repo_name}`
                    : "No repo connected"}
                </CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

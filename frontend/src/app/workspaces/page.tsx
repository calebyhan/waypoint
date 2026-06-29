"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  MoreHorizontal,
  Pencil,
  Archive,
  Trash2,
  RotateCcw,
  Search,
  Plus,
  FolderOpen,
  Settings,
  LogOut,
  User,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  has_ingestion: boolean;
  created_at: string;
}

type StateFilter = "active" | "archived" | "all";
type SortField = "name" | "created_at";

function formatRelativeDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function SkeletonCard() {
  return (
    <Card className="animate-pulse">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="h-5 w-40 rounded bg-muted" />
          <div className="h-5 w-16 rounded bg-muted" />
        </div>
        <div className="flex items-center justify-between pt-1">
          <div className="h-4 w-32 rounded bg-muted" />
          <div className="h-3 w-20 rounded bg-muted" />
        </div>
      </CardHeader>
    </Card>
  );
}

export default function WorkspacesPage() {
  const { session, loading: sessionLoading } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [newName, setNewName] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Workspace | null>(null);
  const [renameName, setRenameName] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [stateFilter, setStateFilter] = useState<StateFilter>("active");
  const [sortField, setSortField] = useState<SortField>("created_at");
  const [deleteTarget, setDeleteTarget] = useState<Workspace | null>(null);

  const { data: workspaces = [], isLoading } = useQuery<Workspace[]>({
    queryKey: ["workspaces", stateFilter],
    queryFn: () =>
      apiFetch(
        `/workspaces${stateFilter !== "all" ? `?state=${stateFilter}` : ""}`,
        { token: session!.access_token },
      ),
    enabled: !!session,
  });

  const filtered = useMemo(() => {
    let result = workspaces;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (ws) =>
          ws.name.toLowerCase().includes(q) ||
          (ws.repo_name && ws.repo_name.toLowerCase().includes(q)),
      );
    }
    result.sort((a, b) => {
      if (sortField === "name") return a.name.localeCompare(b.name);
      return (
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      );
    });
    return result;
  }, [workspaces, searchQuery, sortField]);

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

  const renameMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      apiFetch(`/workspaces/${id}`, {
        method: "PATCH",
        token: session!.access_token,
        body: JSON.stringify({ name }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      setRenameTarget(null);
      toast.success("Workspace renamed");
    },
    onError: () => toast.error("Failed to rename workspace"),
  });

  const archiveMutation = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/workspaces/${id}/archive`, {
        method: "POST",
        token: session!.access_token,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success("Workspace archived");
    },
    onError: () => toast.error("Failed to archive workspace"),
  });

  const restoreMutation = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/workspaces/${id}/restore`, {
        method: "POST",
        token: session!.access_token,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      toast.success("Workspace restored");
    },
    onError: () => toast.error("Failed to restore workspace"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/workspaces/${id}`, {
        method: "DELETE",
        token: session!.access_token,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      setDeleteTarget(null);
      toast.success("Workspace permanently deleted");
    },
    onError: () => toast.error("Failed to delete workspace"),
  });

  const handleSignOut = async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
  };

  if (sessionLoading || isLoading) {
    return (
      <div className="mx-auto max-w-4xl p-8">
        <div className="flex items-center justify-between">
          <div className="h-8 w-40 animate-pulse rounded bg-muted" />
          <div className="h-8 w-8 animate-pulse rounded-full bg-muted" />
        </div>
        <div className="mt-4 flex items-center gap-3">
          <div className="h-8 flex-1 animate-pulse rounded-lg bg-muted" />
          <div className="h-8 w-[140px] animate-pulse rounded-lg bg-muted" />
          <div className="h-8 w-[140px] animate-pulse rounded-lg bg-muted" />
        </div>
        <div className="mt-4 grid gap-4">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Workspaces</h1>
        <div className="flex items-center gap-2">
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger render={<Button><Plus className="mr-1.5 h-4 w-4" />New Workspace</Button>} />
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

          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button variant="ghost" size="icon">
                  <User className="h-4 w-4" />
                </Button>
              }
            />
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => router.push("/settings")}>
                <Settings className="mr-2 h-4 w-4" />
                Settings
              </DropdownMenuItem>
              <DropdownMenuItem onClick={handleSignOut}>
                <LogOut className="mr-2 h-4 w-4" />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search workspaces..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select
          value={stateFilter}
          onValueChange={(v) => setStateFilter(v as StateFilter)}
          items={{ active: "Active", archived: "Archived", all: "All" }}
        >
          <SelectTrigger className="w-[140px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="archived">Archived</SelectItem>
            <SelectItem value="all">All</SelectItem>
          </SelectContent>
        </Select>
        <Select
          value={sortField}
          onValueChange={(v) => setSortField(v as SortField)}
          items={{ created_at: "Newest first", name: "Name A-Z" }}
        >
          <SelectTrigger className="w-[140px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="created_at">Newest first</SelectItem>
            <SelectItem value="name">Name A-Z</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {filtered.length > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">
          {filtered.length} workspace{filtered.length !== 1 ? "s" : ""}
          {searchQuery && ` matching "${searchQuery}"`}
        </p>
      )}

      {filtered.length === 0 ? (
        <div className="mt-12 flex flex-col items-center text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted">
            <FolderOpen className="h-8 w-8 text-muted-foreground" />
          </div>
          <h3 className="mt-4 text-base font-medium">
            {workspaces.length === 0 ? "No workspaces yet" : "No results"}
          </h3>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            {workspaces.length === 0
              ? "Create a workspace to start planning your project."
              : "No workspaces match your current filters. Try adjusting your search or filter."}
          </p>
          {workspaces.length === 0 && (
            <Button className="mt-4" onClick={() => setDialogOpen(true)}>
              <Plus className="mr-1.5 h-4 w-4" />
              New Workspace
            </Button>
          )}
        </div>
      ) : (
        <div className="mt-2 grid gap-3">
          {filtered.map((ws) => {
            const isArchived = ws.state === "archived";
            return (
              <Card
                key={ws.id}
                className={
                  isArchived
                    ? "opacity-60"
                    : "cursor-pointer transition-colors hover:bg-muted/50"
                }
                onClick={() => {
                  if (isArchived) return;
                  router.push(
                    ws.has_ingestion
                      ? `/workspaces/${ws.id}/dashboard`
                      : ws.repo_owner
                        ? `/workspaces/${ws.id}/ingest`
                        : `/workspaces/${ws.id}/setup`,
                  );
                }}
              >
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-lg">{ws.name}</CardTitle>
                    <div className="flex items-center gap-2">
                      {isArchived && (
                        <Badge variant="secondary">Archived</Badge>
                      )}
                      <DropdownMenu>
                        <DropdownMenuTrigger
                          render={
                            <button
                              className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </button>
                          }
                        />
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onClick={(e) => {
                              e.stopPropagation();
                              setRenameName(ws.name);
                              setRenameTarget(ws);
                            }}
                          >
                            <Pencil className="mr-2 h-4 w-4" />
                            Rename
                          </DropdownMenuItem>
                          {ws.state === "active" ? (
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                archiveMutation.mutate(ws.id);
                              }}
                            >
                              <Archive className="mr-2 h-4 w-4" />
                              Archive
                            </DropdownMenuItem>
                          ) : (
                            <>
                              <DropdownMenuItem
                                onClick={(e) => {
                                  e.stopPropagation();
                                  restoreMutation.mutate(ws.id);
                                }}
                              >
                                <RotateCcw className="mr-2 h-4 w-4" />
                                Restore
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                className="text-destructive"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setDeleteTarget(ws);
                                }}
                              >
                                <Trash2 className="mr-2 h-4 w-4" />
                                Delete permanently
                              </DropdownMenuItem>
                            </>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </div>
                  <div className="flex items-center justify-between">
                    <CardDescription>
                      {ws.repo_owner
                        ? `${ws.repo_owner}/${ws.repo_name}`
                        : "No repo connected"}
                    </CardDescription>
                    <span className="text-xs text-muted-foreground">
                      {formatRelativeDate(ws.created_at)}
                    </span>
                  </div>
                </CardHeader>
              </Card>
            );
          })}
        </div>
      )}

      {/* Rename dialog */}
      <Dialog
        open={!!renameTarget}
        onOpenChange={(open) => !open && setRenameTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename Workspace</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <Input
              value={renameName}
              onChange={(e) => setRenameName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && renameName.trim() && renameTarget) {
                  renameMutation.mutate({
                    id: renameTarget.id,
                    name: renameName.trim(),
                  });
                }
              }}
            />
            <Button
              onClick={() =>
                renameTarget &&
                renameMutation.mutate({
                  id: renameTarget.id,
                  name: renameName.trim(),
                })
              }
              disabled={!renameName.trim() || renameMutation.isPending}
              className="w-full"
            >
              {renameMutation.isPending ? "Renaming..." : "Rename"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation dialog */}
      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Workspace</DialogTitle>
            <DialogDescription>
              This will permanently delete <strong>{deleteTarget?.name}</strong> and
              all associated data. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={deleteMutation.isPending}
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
            >
              {deleteMutation.isPending ? "Deleting..." : "Delete permanently"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

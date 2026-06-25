"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";

interface ExistingTask {
  id: string;
  title: string;
  description: string | null;
  estimated_days: number | null;
  priority: string;
}

interface NewTask {
  title: string;
  description: string;
  estimated_days: number;
  priority: string;
  epic_title: string;
}

interface DiffEntry {
  existing_task?: ExistingTask;
  new_task?: NewTask;
  similarity?: number;
  linked_issue_number?: number;
}

interface DiffResult {
  unchanged: DiffEntry[];
  modified: DiffEntry[];
  added: DiffEntry[];
  removed: DiffEntry[];
}

export default function ReingestPage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useSession();
  const router = useRouter();

  const [content, setContent] = useState("");
  const [diff, setDiff] = useState<DiffResult | null>(null);
  const [removedIds, setRemovedIds] = useState<Set<string>>(new Set());
  const [addedExcluded, setAddedExcluded] = useState<Set<number>>(new Set());

  const diffMutation = useMutation({
    mutationFn: () =>
      apiFetch<DiffResult>(`/workspaces/${id}/reingest`, {
        method: "POST",
        token: session!.access_token,
        body: JSON.stringify({ content }),
      }),
    onSuccess: (result) => setDiff(result),
    onError: () => toast.error("Failed to compute diff"),
  });

  const applyMutation = useMutation({
    mutationFn: () => {
      const added = (diff?.added ?? [])
        .filter((_, i) => !addedExcluded.has(i))
        .map((e) => e.new_task);
      const modified = (diff?.modified ?? []).map((e) => ({
        task_id: e.existing_task!.id,
        title: e.new_task!.title,
        description: e.new_task!.description,
        estimated_days: e.new_task!.estimated_days,
        priority: e.new_task!.priority,
      }));
      return apiFetch(`/workspaces/${id}/reingest/approve`, {
        method: "POST",
        token: session!.access_token,
        body: JSON.stringify({
          added,
          modified,
          removed_task_ids: Array.from(removedIds),
        }),
      });
    },
    onSuccess: () => {
      toast.success("Plan updated");
      router.push(`/workspaces/${id}/dashboard`);
    },
    onError: () => toast.error("Failed to apply changes"),
  });

  if (!diff) {
    return (
      <div className="mx-auto max-w-2xl p-8 space-y-6">
        <div>
          <h1 className="text-2xl font-bold">Re-ingest PRD</h1>
          <p className="text-muted-foreground">
            Paste the updated PRD. The agent will diff it against your current
            plan.
          </p>
        </div>
        <Card>
          <CardContent className="pt-6 space-y-4">
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={12}
              placeholder="Paste updated PRD content..."
              className="font-mono text-sm"
            />
            <Button
              onClick={() => diffMutation.mutate()}
              disabled={!content.trim() || diffMutation.isPending}
            >
              {diffMutation.isPending ? "Diffing..." : "Compute Diff"}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Review Changes</h1>
        <p className="text-muted-foreground">
          {diff.unchanged.length} unchanged, {diff.modified.length} modified,{" "}
          {diff.added.length} new, {diff.removed.length} removed
        </p>
      </div>

      {diff.modified.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Modified Tasks</CardTitle>
            <CardDescription>Scope changed — review carefully</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {diff.modified.map((entry, i) => (
              <div key={i} className="rounded-lg border p-3 space-y-1">
                <div className="flex items-center justify-between">
                  <p className="font-medium">{entry.new_task!.title}</p>
                  <Badge variant="secondary">was: {entry.existing_task!.title}</Badge>
                </div>
                <p className="text-sm text-muted-foreground">{entry.new_task!.description}</p>
                {entry.linked_issue_number && (
                  <p className="text-xs text-amber-600">
                    Linked to issue #{entry.linked_issue_number} — the GitHub issue description may be outdated.
                  </p>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {diff.added.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base text-green-700">New Tasks</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {diff.added.map((entry, i) => (
              <div key={i} className="flex items-start gap-2 rounded-lg border p-3">
                <input
                  type="checkbox"
                  checked={!addedExcluded.has(i)}
                  onChange={(e) => {
                    setAddedExcluded((prev) => {
                      const next = new Set(prev);
                      if (e.target.checked) next.delete(i);
                      else next.add(i);
                      return next;
                    });
                  }}
                  className="mt-1"
                />
                <div>
                  <p className="font-medium">{entry.new_task!.title}</p>
                  <p className="text-sm text-muted-foreground">{entry.new_task!.description}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {diff.removed.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base text-red-700">Removed Tasks</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {diff.removed.map((entry, i) => (
              <div key={i} className="flex items-start gap-2 rounded-lg border p-3">
                <input
                  type="checkbox"
                  checked={removedIds.has(entry.existing_task!.id)}
                  onChange={(e) => {
                    setRemovedIds((prev) => {
                      const next = new Set(prev);
                      if (e.target.checked) next.add(entry.existing_task!.id);
                      else next.delete(entry.existing_task!.id);
                      return next;
                    });
                  }}
                  className="mt-1"
                />
                <p className="font-medium">{entry.existing_task!.title}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="flex gap-2">
        <Button onClick={() => applyMutation.mutate()} disabled={applyMutation.isPending}>
          {applyMutation.isPending ? "Applying..." : "Apply Changes"}
        </Button>
        <Button variant="ghost" onClick={() => setDiff(null)}>
          Back
        </Button>
      </div>
    </div>
  );
}

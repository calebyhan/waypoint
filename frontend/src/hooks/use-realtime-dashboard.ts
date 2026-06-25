"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { createClient } from "@/lib/supabase/client";

export function useRealtimeDashboard(workspaceId: string) {
  const queryClient = useQueryClient();

  useEffect(() => {
    const supabase = createClient();

    const channel = supabase
      .channel(`workspace-${workspaceId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "tasks", filter: `workspace_id=eq.${workspaceId}` },
        () => queryClient.invalidateQueries({ queryKey: ["dashboard", workspaceId] }),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "github_issues", filter: `workspace_id=eq.${workspaceId}` },
        () => queryClient.invalidateQueries({ queryKey: ["dashboard", workspaceId] }),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "github_prs", filter: `workspace_id=eq.${workspaceId}` },
        () => queryClient.invalidateQueries({ queryKey: ["dashboard", workspaceId] }),
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "match_proposals", filter: `workspace_id=eq.${workspaceId}` },
        () => queryClient.invalidateQueries({ queryKey: ["dashboard", workspaceId] }),
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [workspaceId, queryClient]);
}

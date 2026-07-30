"use client";

import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface Notification {
  id: string;
  type: string;
  payload: Record<string, string | null>;
  workspace_id: string | null;
  read_at: string | null;
  created_at: string;
}

/** How a notification reads in the feed, and where clicking it goes. */
function describe(n: Notification): { text: string; href: string | null } {
  const p = n.payload ?? {};
  const workspace = p.workspace_name ?? "a workspace";

  switch (n.type) {
    case "workspace_invite":
      return {
        text: `${p.invited_by ? `@${p.invited_by}` : "Someone"} invited you to ${workspace}`,
        // Route through the invite landing page rather than straight to the
        // workspace: membership may not be granted yet when this is the very
        // first thing a new user clicks.
        href: p.token ? `/invite/${p.token}` : null,
      };
    case "added_to_workspace":
      return {
        text: `You now have access to ${workspace}`,
        href: n.workspace_id ? `/workspaces/${n.workspace_id}/dashboard` : null,
      };
    case "workspace_invite_accepted":
      return {
        text: `@${p.github_username} joined ${workspace}`,
        href: n.workspace_id ? `/workspaces/${n.workspace_id}/settings` : null,
      };
    default:
      return { text: "You have a new notification", href: null };
  }
}

function relativeTime(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function NotificationBell() {
  const { session } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data: notifications = [] } = useQuery<Notification[]>({
    queryKey: ["notifications"],
    queryFn: () => apiFetch("/notifications", { token: session!.access_token }),
    enabled: !!session,
    // Cheap poll so an invite that arrives mid-session still surfaces without
    // a page reload. No websocket infrastructure exists to push this.
    refetchInterval: 60_000,
  });

  const unreadCount = notifications.filter((n) => !n.read_at).length;

  const markRead = useMutation({
    mutationFn: (notificationId: string) =>
      apiFetch(`/notifications/${notificationId}/read`, {
        method: "POST",
        token: session!.access_token,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

  const markAllRead = useMutation({
    mutationFn: () =>
      apiFetch("/notifications/read-all", {
        method: "POST",
        token: session!.access_token,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

  if (!session) return null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" size="icon" className="relative" aria-label={
            unreadCount > 0 ? `Notifications (${unreadCount} unread)` : "Notifications"
          }>
            <Bell className="h-4 w-4" />
            {unreadCount > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-medium text-primary-foreground">
                {unreadCount > 9 ? "9+" : unreadCount}
              </span>
            )}
          </Button>
        }
      />
      <DropdownMenuContent align="end" className="w-90 max-w-[calc(100vw-2rem)] p-0">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="text-sm font-medium">Notifications</span>
          {unreadCount > 0 && (
            <button
              type="button"
              onClick={() => markAllRead.mutate()}
              className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              <Check className="h-3 w-3" />
              Mark all read
            </button>
          )}
        </div>

        {notifications.length === 0 ? (
          <p className="px-3 py-8 text-center text-sm text-muted-foreground">
            Nothing here yet.
          </p>
        ) : (
          <div className="max-h-96 overflow-y-auto">
            {notifications.map((n) => {
              const { text, href } = describe(n);
              return (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => {
                    if (!n.read_at) markRead.mutate(n.id);
                    if (href) router.push(href);
                  }}
                  className={cn(
                    "flex w-full flex-col items-start gap-0.5 border-b px-3 py-2.5 text-left transition-colors last:border-b-0 hover:bg-accent",
                    !n.read_at && "bg-primary/5",
                  )}
                >
                  <span className="flex w-full items-start gap-2">
                    {!n.read_at && (
                      <span
                        aria-hidden
                        className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
                      />
                    )}
                    <span className="flex-1 text-sm">{text}</span>
                  </span>
                  <span className="pl-3.5 text-xs text-muted-foreground">
                    {relativeTime(n.created_at)}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

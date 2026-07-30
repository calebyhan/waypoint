"use client";

import { useCallback, useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useSession } from "@/hooks/use-session";
import { apiFetch, ApiError } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { toast } from "sonner";

interface InvitePreview {
  workspace_name: string | null;
  invited_username: string;
  invited_by: string | null;
  role: string;
  status: string;
  is_expired: boolean;
}

export default function InviteLandingPage() {
  const { token } = useParams<{ token: string }>();
  const { session, loading: sessionLoading } = useSession();
  const router = useRouter();

  // Unauthenticated: this is what a brand-new user sees before they have an
  // account, so it has to stand on its own without a session.
  const {
    data: invite,
    isLoading,
    error,
  } = useQuery<InvitePreview, ApiError>({
    queryKey: ["invite", token],
    queryFn: () => apiFetch(`/invites/${token}`),
    retry: false,
  });

  const signIn = useCallback(async () => {
    const supabase = createClient();
    const redirectTo = new URL("/auth/callback", window.location.origin);
    // Come back here after OAuth so the invite is accepted rather than
    // dumping a new user on an empty workspace list.
    redirectTo.searchParams.set("next", `/invite/${token}`);

    const { error } = await supabase.auth.signInWithOAuth({
      provider: "github",
      options: { redirectTo: redirectTo.toString(), scopes: "repo read:user user:email" },
    });
    if (error) toast.error("Sign-in failed. Please try again.");
  }, [token]);

  const acceptMutation = useMutation({
    mutationFn: () =>
      apiFetch<{ status: string; workspace_id: string }>(`/invites/${token}/accept`, {
        method: "POST",
        token: session!.access_token,
      }),
    onSuccess: (result) => {
      toast.success(
        result.status === "already_member"
          ? "You're already a member"
          : `Joined ${invite?.workspace_name ?? "the workspace"}`,
      );
      router.push(`/workspaces/${result.workspace_id}/dashboard`);
    },
  });

  // Signed in and the invite is good -> accept without a second click. The user
  // already expressed intent by opening the link and authorizing GitHub.
  //
  // The ref guard makes this fire exactly once: the effect re-runs whenever the
  // session or preview object identity changes, and each extra run would be
  // another POST.
  const attempted = useRef(false);
  useEffect(() => {
    if (attempted.current) return;
    if (session && invite && invite.status === "pending" && !invite.is_expired) {
      attempted.current = true;
      acceptMutation.mutate();
    }
  }, [session, invite, acceptMutation]);

  if (isLoading || sessionLoading) {
    return <Shell><p className="text-muted-foreground">Loading invite...</p></Shell>;
  }

  if (error) {
    return (
      <Shell>
        <Card>
          <CardHeader>
            <CardTitle>Invite not found</CardTitle>
            <CardDescription>
              This link isn&apos;t valid. It may have been revoked, or the URL may be
              incomplete — check that you copied the whole thing.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" onClick={() => router.push("/")}>
              Go to Waypoint
            </Button>
          </CardContent>
        </Card>
      </Shell>
    );
  }

  if (!invite) return null;

  const unusable = invite.is_expired || invite.status !== "pending";

  return (
    <Shell>
      <Card>
        <CardHeader>
          <CardTitle>
            {unusable
              ? "This invite is no longer available"
              : `Join ${invite.workspace_name ?? "a workspace"}`}
          </CardTitle>
          <CardDescription>
            {unusable ? (
              invite.is_expired ? (
                <>This invite expired. Ask {invite.invited_by ? `@${invite.invited_by}` : "the sender"} for a new one.</>
              ) : (
                <>This invite has already been {invite.status}.</>
              )
            ) : (
              <>
                {invite.invited_by ? `@${invite.invited_by}` : "Someone"} invited{" "}
                <span className="font-medium text-foreground">@{invite.invited_username}</span>{" "}
                to join{" "}
                <span className="font-medium text-foreground">
                  {invite.workspace_name ?? "a workspace"}
                </span>{" "}
                as {invite.role === "pm" ? "a PM" : "a member"}.
              </>
            )}
          </CardDescription>
        </CardHeader>

        {!unusable && (
          <CardContent className="space-y-4">
            {acceptMutation.isError ? (
              <>
                <p className="text-sm text-destructive">
                  {acceptMutation.error instanceof Error
                    ? acceptMutation.error.message
                    : "Couldn't accept this invite"}
                </p>
                <p className="text-sm text-muted-foreground">
                  This invite only works for @{invite.invited_username}. If that&apos;s
                  you, sign out and sign back in with that GitHub account.
                </p>
              </>
            ) : session ? (
              <p className="text-sm text-muted-foreground">
                {acceptMutation.isPending ? "Joining..." : "Checking your invite..."}
              </p>
            ) : (
              <>
                <p className="text-sm text-muted-foreground">
                  Sign in with the GitHub account{" "}
                  <span className="font-medium text-foreground">@{invite.invited_username}</span>{" "}
                  to accept. You don&apos;t need an account yet — signing in creates one.
                </p>
                <Button onClick={signIn} className="w-full" size="lg">
                  Continue with GitHub
                </Button>
              </>
            )}
          </CardContent>
        )}
      </Card>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold">Waypoint</h1>
        </div>
        {children}
      </div>
    </div>
  );
}

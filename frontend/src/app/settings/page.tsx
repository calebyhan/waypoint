"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
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
import { useSession } from "@/hooks/use-session";
import { apiFetch } from "@/lib/api";
import { toast } from "sonner";

interface Profile {
  id: string;
  github_username: string;
  avatar_url: string | null;
  gemini_api_key: string | null;
}

export default function SettingsPage() {
  const { session, loading: sessionLoading } = useSession();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [editedKey, setEditedKey] = useState<string | null>(null);

  const { data: profile, isLoading } = useQuery<Profile>({
    queryKey: ["profile"],
    queryFn: () => apiFetch("/auth/me", { token: session!.access_token }),
    enabled: !!session,
  });

  const apiKey = editedKey ?? profile?.gemini_api_key ?? "";

  const saveMutation = useMutation({
    mutationFn: () =>
      apiFetch("/auth/me", {
        method: "PATCH",
        token: session!.access_token,
        body: JSON.stringify({ gemini_api_key: apiKey.trim() }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["profile"] });
      toast.success("API key saved");
    },
    onError: () => toast.error("Failed to save API key"),
  });

  if (sessionLoading || isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">Loading...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-md p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Settings</h1>
        <Button variant="ghost" onClick={() => router.push("/workspaces")}>
          Back to workspaces
        </Button>
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Profile</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center gap-3">
          {profile?.avatar_url && (
            <img
              src={profile.avatar_url}
              alt={profile.github_username}
              className="h-10 w-10 rounded-full"
            />
          )}
          <span className="font-medium">{profile?.github_username}</span>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>AI Key</CardTitle>
          <CardDescription>
            Waypoint uses Google Gemini for PRD analysis. Provide your free API
            key to get started.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="api-key">Gemini API Key</Label>
            <Input
              id="api-key"
              type="password"
              placeholder="AIza..."
              value={apiKey}
              onChange={(e) => setEditedKey(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Get a free key at{" "}
              <a
                href="https://aistudio.google.com/apikey"
                target="_blank"
                rel="noopener noreferrer"
                className="underline"
              >
                aistudio.google.com/apikey
              </a>
            </p>
          </div>
          <Button
            onClick={() => saveMutation.mutate()}
            disabled={!apiKey.trim() || saveMutation.isPending}
          >
            {saveMutation.isPending ? "Saving..." : "Save"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

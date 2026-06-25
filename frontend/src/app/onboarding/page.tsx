"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
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

export default function OnboardingPage() {
  const { session } = useSession();
  const router = useRouter();
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!apiKey.trim() || !session) return;
    setSaving(true);
    try {
      await apiFetch("/auth/me", {
        method: "PATCH",
        token: session.access_token,
        body: JSON.stringify({ gemini_api_key: apiKey.trim() }),
      });
      toast.success("API key saved");
      router.push("/workspaces");
    } catch {
      toast.error("Failed to save API key");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Set up your AI key</CardTitle>
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
              onChange={(e) => setApiKey(e.target.value)}
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
          <div className="flex gap-2">
            <Button onClick={handleSave} disabled={!apiKey.trim() || saving}>
              {saving ? "Saving..." : "Save & Continue"}
            </Button>
            <Button variant="ghost" onClick={() => router.push("/workspaces")}>
              Skip for now
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

"use client";

import { useSearchParams } from "next/navigation";

import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";

export default function LoginPage() {
  const searchParams = useSearchParams();
  const error = searchParams?.get("error");

  const handleLogin = async () => {
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "github",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
        scopes: "repo read:user user:email",
      },
    });
    if (error) {
      console.error("GitHub sign-in failed:", error.message);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="w-full max-w-sm space-y-6 text-center">
        <div>
          <h1 className="text-3xl font-bold">Waypoint</h1>
          <p className="mt-2 text-muted-foreground">
            AI-powered project management for small teams
          </p>
        </div>
        {error && (
          <p className="text-sm text-destructive">
            Sign-in failed. Please try again.
          </p>
        )}
        <Button onClick={handleLogin} className="w-full" size="lg">
          Sign in with GitHub
        </Button>
      </div>
    </div>
  );
}

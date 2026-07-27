"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";

async function handleLogin() {
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
}

function LoginError() {
  const searchParams = useSearchParams();
  const error = searchParams?.get("error");
  if (!error) return null;
  return (
    <p className="text-sm text-destructive">Sign-in failed. Please try again.</p>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="w-full max-w-sm space-y-6 text-center">
        <div>
          <h1 className="text-3xl font-bold">Waypoint</h1>
          <p className="mt-2 text-muted-foreground">
            AI-powered project management for small teams
          </p>
        </div>
        <Suspense fallback={null}>
          <LoginError />
        </Suspense>
        <Button onClick={handleLogin} className="w-full" size="lg">
          Sign in with GitHub
        </Button>
      </div>
    </div>
  );
}

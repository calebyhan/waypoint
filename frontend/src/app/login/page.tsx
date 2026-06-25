"use client";

import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";

export default function LoginPage() {
  const handleLogin = async () => {
    const supabase = createClient();
    await supabase.auth.signInWithOAuth({
      provider: "github",
      options: {
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });
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
        <Button onClick={handleLogin} className="w-full" size="lg">
          Sign in with GitHub
        </Button>
      </div>
    </div>
  );
}

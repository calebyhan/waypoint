import { createClient } from "@/lib/supabase/client";

/**
 * Re-run the GitHub OAuth flow for an already-signed-in user to refresh the
 * provider token stored on their profile (Supabase only exposes the GitHub
 * access token on the OAuth session response, not afterward, so an expired
 * or revoked token can only be replaced by going through sign-in again).
 */
export async function reconnectGithub(returnTo?: string) {
  const supabase = createClient();
  const redirectTo = new URL("/auth/callback", window.location.origin);
  if (returnTo) redirectTo.searchParams.set("next", returnTo);

  const { error } = await supabase.auth.signInWithOAuth({
    provider: "github",
    options: {
      redirectTo: redirectTo.toString(),
      scopes: "repo read:user user:email",
    },
  });
  return error;
}

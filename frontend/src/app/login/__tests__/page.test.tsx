import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const signInWithOAuth = vi.fn();

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: { signInWithOAuth },
  }),
}));

import LoginPage from "@/app/login/page";

describe("LoginPage", () => {
  it("renders the GitHub sign-in button", () => {
    render(<LoginPage />);
    expect(screen.getByRole("button", { name: /sign in with github/i })).toBeInTheDocument();
  });

  it("starts a GitHub OAuth flow with a redirect back to /auth/callback on click", async () => {
    render(<LoginPage />);

    await userEvent.click(screen.getByRole("button", { name: /sign in with github/i }));

    expect(signInWithOAuth).toHaveBeenCalledWith({
      provider: "github",
      options: {
        redirectTo: expect.stringContaining("/auth/callback"),
        scopes: expect.stringContaining("repo"),
      },
    });
  });
});

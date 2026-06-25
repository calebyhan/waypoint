import { createClient } from "@/lib/supabase/server";
import { redirect } from "next/navigation";

export default async function WorkspacesPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  return (
    <div className="mx-auto max-w-4xl p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Workspaces</h1>
      </div>
      <p className="mt-4 text-muted-foreground">
        Your workspaces will appear here. Create one to get started.
      </p>
    </div>
  );
}

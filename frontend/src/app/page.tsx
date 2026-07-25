import { redirect } from "next/navigation";

// Middleware already sends unauthenticated visitors to /login; authenticated
// visitors land on their workspace list instead of create-next-app boilerplate.
export default function Home() {
  redirect("/workspaces");
}

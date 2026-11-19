import { redirect } from "next/navigation";

// The home page is the login; system status lives at /status.
export default function Home() {
  redirect("/login");
}

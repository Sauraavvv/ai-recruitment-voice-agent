"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useLoad } from "@/lib/use-load";
import { logout, me } from "@/services/auth";

const LINKS = [
  { href: "/candidates", label: "Candidates" },
  { href: "/candidates/upload", label: "Upload" },
  { href: "/settings/job", label: "Job settings" },
  { href: "/", label: "System status" },
];

export function AppNav() {
  const pathname = usePathname();
  const router = useRouter();
  // A 401 here redirects to /login (see lib/api.ts), which protects every recruiter page.
  const { data: user } = useLoad("me", me);

  async function onLogout() {
    await logout().catch(() => undefined);
    router.replace("/login");
  }

  return (
    <header className="border-b border-zinc-200 dark:border-zinc-800">
      <nav className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-4 px-4 py-3 text-sm">
        <span className="font-semibold">Recruitment Agent</span>
        {LINKS.map((link) => {
          const active =
            link.href === "/candidates"
              ? pathname === "/candidates" || /^\/candidates\/(?!upload)/.test(pathname)
              : pathname === link.href;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={active ? "font-medium underline" : "text-zinc-600 dark:text-zinc-400"}
            >
              {link.label}
            </Link>
          );
        })}
        <span className="ml-auto text-zinc-500">{user?.name}</span>
        {user && (
          <button type="button" onClick={onLogout} className="underline">
            Log out
          </button>
        )}
      </nav>
    </header>
  );
}

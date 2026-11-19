"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useSyncExternalStore } from "react";

import { LogoMark } from "@/components/logo";
import { useLoad } from "@/lib/use-load";
import { logout, me } from "@/services/auth";

const STORAGE_KEY = "hirecall.sidebar.collapsed";

// 20×20 stroke icons (inline, no icon library)
const icon = (path: ReactNode) => (
  <svg
    viewBox="0 0 24 24"
    className="h-5 w-5 shrink-0"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.8}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {path}
  </svg>
);

const ICONS = {
  dashboard: icon(
    <>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </>,
  ),
  candidates: icon(
    <>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0" />
      <path d="M16 4.5a3.5 3.5 0 0 1 0 7" />
      <path d="M18 14.5a6.5 6.5 0 0 1 3.5 5.5" />
    </>,
  ),
  upload: icon(
    <>
      <path d="M12 15V4" />
      <path d="m7 9 5-5 5 5" />
      <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </>,
  ),
  questions: icon(
    <>
      <path d="M9 6h11" />
      <path d="M9 12h11" />
      <path d="M9 18h11" />
      <circle cx="4.5" cy="6" r="1" />
      <circle cx="4.5" cy="12" r="1" />
      <circle cx="4.5" cy="18" r="1" />
    </>,
  ),
  job: icon(
    <>
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
      <path d="M3 13h18" />
    </>,
  ),
  calls: icon(
    <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />,
  ),
  settings: icon(
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
    </>,
  ),
  logout: icon(
    <>
      <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" />
      <path d="M10 17l-5-5 5-5" />
      <path d="M5 12h11" />
    </>,
  ),
  collapse: icon(
    <>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <path d="M9 3v18" />
      <path d="m15 10-2 2 2 2" />
    </>,
  ),
  expand: icon(
    <>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <path d="M9 3v18" />
      <path d="m13 10 2 2-2 2" />
    </>,
  ),
};

const LINKS = [
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: ICONS.dashboard,
  },
  {
    href: "/candidates",
    label: "Candidates",
    icon: ICONS.candidates,
    // The list, a candidate's page and adding one; the upload flow has its own link
    isActive: (p: string) => p === "/candidates" || /^\/candidates\/(?!upload)/.test(p),
  },
  { href: "/calls", label: "Calls", icon: ICONS.calls },
  { href: "/candidates/upload", label: "Upload", icon: ICONS.upload },
  { href: "/settings/job", label: "Job settings", icon: ICONS.job },
  { href: "/default-questions", label: "Default questions", icon: ICONS.questions },
  { href: "/settings", label: "Settings", icon: ICONS.settings },
];

// The collapsed choice lives in localStorage; components re-read it when it changes.
const CHANGE_EVENT = "hirecall:sidebar";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

function setStoredCollapsed(value: boolean) {
  try {
    window.localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
  } catch {
    // storage blocked: the choice just isn't remembered
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  // A 401 here redirects to /login (see lib/api.ts), which protects every recruiter page.
  const { data: user } = useLoad("me", me);
  // Server render: expanded; the browser then applies the remembered choice.
  const collapsed = useSyncExternalStore(subscribe, readCollapsed, () => false);
  const toggle = () => setStoredCollapsed(!collapsed);

  async function onLogout() {
    await logout().catch(() => undefined);
    router.replace("/login");
  }

  const row =
    "flex h-10 items-center gap-3 rounded-xl px-3 text-sm transition-colors " +
    (collapsed ? "justify-center px-0" : "");

  return (
    <aside
      className={`sticky top-0 flex h-screen shrink-0 py-3 pl-3 transition-[width] duration-200 ${
        collapsed ? "w-[84px]" : "w-[252px]"
      }`}
    >
      <nav
        aria-label="Main"
        className="flex flex-1 flex-col overflow-hidden rounded-3xl bg-[#18191c] p-3 text-white"
      >
        <div className={`mb-6 flex h-10 items-center ${collapsed ? "justify-center" : "px-2"}`}>
          <LogoMark className="h-6 w-6 shrink-0" />
          {!collapsed && (
            <span className="font-display ml-2.5 text-lg font-semibold tracking-tight">
              HireCall
            </span>
          )}
        </div>

        <ul className="space-y-1">
          {LINKS.map((link) => {
            const active = link.isActive ? link.isActive(pathname) : pathname === link.href;
            return (
              <li key={link.href}>
                <Link
                  href={link.href}
                  title={collapsed ? link.label : undefined}
                  aria-label={collapsed ? link.label : undefined}
                  aria-current={active ? "page" : undefined}
                  className={`${row} ${
                    active
                      ? "bg-white/10 font-medium text-white"
                      : "text-zinc-400 hover:bg-white/5 hover:text-white"
                  }`}
                >
                  {link.icon}
                  {!collapsed && <span className="truncate">{link.label}</span>}
                </Link>
              </li>
            );
          })}
        </ul>

        <div className="mt-auto space-y-1 border-t border-white/5 pt-3">
          {user && !collapsed && (
            <div className="truncate px-3 pb-2 text-sm">
              <div className="truncate font-medium">{user.name}</div>
              <div className="truncate text-xs text-zinc-500">{user.email}</div>
            </div>
          )}
          <button
            type="button"
            onClick={onLogout}
            title={collapsed ? "Log out" : undefined}
            aria-label="Log out"
            className={`${row} w-full text-zinc-400 hover:bg-white/5 hover:text-white`}
          >
            {ICONS.logout}
            {!collapsed && <span>Log out</span>}
          </button>
          <button
            type="button"
            onClick={toggle}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
            className={`${row} w-full text-zinc-400 hover:bg-white/5 hover:text-white`}
          >
            {collapsed ? ICONS.expand : ICONS.collapse}
            {!collapsed && <span>Collapse</span>}
          </button>
        </div>
      </nav>
    </aside>
  );
}

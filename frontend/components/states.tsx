// Loading, empty and error states shared by the recruiter pages.
import Link from "next/link";
import type { ReactNode } from "react";

import { Button, buttonClass } from "@/components/ui";
import { ApiError, errorMessage } from "@/lib/api";

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-white/[0.06] ${className}`} aria-hidden />;
}

export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10" />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: { href: string; label: string };
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 px-6 py-10 text-center">
      <p className="font-medium text-zinc-200">{title}</p>
      {children && <p className="mt-1 max-w-md text-sm text-zinc-500">{children}</p>}
      {action && (
        <Link href={action.href} className={`${buttonClass("primary")} mt-4`}>
          {action.label}
        </Link>
      )}
    </div>
  );
}

/** Inline error with a retry button. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const offline = error instanceof ApiError && error.code === "network_error";
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200"
    >
      <span>{offline ? "Can't reach the server." : errorMessage(error)}</span>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

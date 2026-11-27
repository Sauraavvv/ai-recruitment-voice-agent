"use client";

import type { ReactNode } from "react";

import { Skeleton } from "@/components/states";
import { Alert, PageHeader } from "@/components/ui";
import { useLoad } from "@/lib/use-load";
import { me } from "@/services/auth";

/** Renders its page only for a super admin. Recruiters get a short note instead, and the page's
 * own requests never start for them (the backend refuses them as well). */
export function AdminOnly({ title, children }: { title: string; children: ReactNode }) {
  const { data: user, error } = useLoad("me", me);
  if (!user && !error) return <Skeleton className="h-96 rounded-3xl" />;
  if (user?.role !== "super_admin") {
    return (
      <>
        <PageHeader title={title} />
        <Alert kind="info">Only a super admin can see and change {title.toLowerCase()}.</Alert>
      </>
    );
  }
  return <>{children}</>;
}

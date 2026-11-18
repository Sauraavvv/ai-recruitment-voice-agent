import { Suspense } from "react";

import { AppNav } from "@/components/app-nav";

export default function RecruiterLayout({ children }: LayoutProps<"/">) {
  return (
    <>
      {/* AppNav reads the pathname, which is only known at request time on dynamic routes. */}
      <Suspense fallback={<div className="h-11 border-b border-zinc-200 dark:border-zinc-800" />}>
        <AppNav />
      </Suspense>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
    </>
  );
}

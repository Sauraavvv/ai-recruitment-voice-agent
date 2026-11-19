import { Suspense } from "react";

import { Sidebar } from "@/components/sidebar";

export default function RecruiterLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-screen flex-1 bg-black text-white">
      {/* The sidebar reads the pathname, which is only known at request time on dynamic routes. */}
      <Suspense fallback={<div className="w-[252px] shrink-0" />}>
        <Sidebar />
      </Suspense>
      <main className="min-w-0 flex-1 px-8 py-8">
        <div className="mx-auto w-full max-w-6xl">{children}</div>
      </main>
    </div>
  );
}

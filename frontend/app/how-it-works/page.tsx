import Link from "next/link";

import { FlowExplorer } from "@/components/flow/flow-canvas";
import { Logo } from "@/components/logo";

export const metadata = {
  title: "How CallZest works · CallZest",
  description: "Every step from adding a job to a scored shortlist, as a flow you can explore.",
};

export default function HowItWorksPage() {
  return (
    <div className="flex h-dvh flex-col bg-black font-sans text-white">
      <header className="z-10 flex h-16 shrink-0 items-center justify-between border-b border-white/[0.06] px-5 sm:px-8">
        <div className="flex items-center gap-5">
          <Link href="/" aria-label="CallZest home">
            <Logo className="text-white" markClassName="h-6 w-6" textClassName="text-lg" />
          </Link>
          <span className="hidden h-5 w-px bg-white/10 sm:block" />
          <h1 className="hidden font-mono text-[11px] tracking-[0.22em] text-zinc-400 uppercase sm:block">How CallZest works</h1>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/" className="rounded-lg px-3 py-2 font-mono text-[11px] tracking-[0.22em] text-zinc-400 uppercase transition-colors hover:text-white">
            ← Home
          </Link>
          <Link
            href="/signup"
            className="rounded-full bg-white px-4 py-2 text-sm font-medium text-black transition hover:bg-zinc-200"
          >
            Sign up
          </Link>
        </div>
      </header>
      <main className="relative min-h-0 flex-1">
        <div className="pointer-events-none absolute top-5 left-5 z-10 max-w-sm">
          <p className="flex items-center gap-2.5 font-mono text-[11px] tracking-[0.25em] text-zinc-400 uppercase">
            <span className="h-1.5 w-1.5 rounded-full bg-zinc-500" aria-hidden="true" />
            The full flow
          </p>
          <p className="mt-2 text-sm text-zinc-500">Click any step to read about it. Drag to move, scroll to zoom, or press Run.</p>
        </div>
        <FlowExplorer />
      </main>
    </div>
  );
}

import Link from "next/link";

import { Reveal } from "@/components/landing/motion";
import { Logo } from "@/components/logo";
import { PHASES } from "@/components/proof/build-log";
import { CallRecording } from "@/components/proof/call-recording";

export const metadata = {
  title: "Proof · CallZest",
  description:
    "A real screening call recorded end to end, and the build log: ten phases, each tested before the next began.",
};

const container = "mx-auto w-full max-w-6xl px-5 sm:px-8";

const RESULTS = [
  { value: "0.72s", label: "first sound after the candidate stops (median)" },
  { value: "48/48", label: "test conversations passed" },
  { value: "90.8%", label: "key details right in noisy test clips" },
  { value: "771", label: "automated checks by the last phase" },
];

function Label({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-2.5 font-mono text-[11px] tracking-[0.25em] text-zinc-400 uppercase">
      <span className="h-1.5 w-1.5 rounded-full bg-zinc-500" aria-hidden="true" />
      {children}
    </p>
  );
}

function Check() {
  return (
    <svg viewBox="0 0 24 24" className="mt-1 h-3.5 w-3.5 shrink-0 text-emerald-400" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}

export default function ProofPage() {
  return (
    <div className="flex-1 overflow-x-clip bg-black font-sans text-white">
      <header className="sticky top-0 z-50 border-b border-white/[0.06] bg-black/70 backdrop-blur-xl">
        <div className={`${container} flex h-16 items-center justify-between`}>
          <div className="flex items-center gap-5">
            <Link href="/" aria-label="CallZest home">
              <Logo className="text-white" markClassName="h-6 w-6" textClassName="text-lg" />
            </Link>
            <span className="hidden h-5 w-px bg-white/10 sm:block" />
            <span className="hidden font-mono text-[11px] tracking-[0.22em] text-zinc-400 uppercase sm:block">Proof</span>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/" className="rounded-lg px-3 py-2 font-mono text-[11px] tracking-[0.22em] text-zinc-400 uppercase transition-colors hover:text-white">
              ← Home
            </Link>
            <Link href="/signup" className="rounded-full bg-white px-4 py-2 text-sm font-medium text-black transition hover:bg-zinc-200">
              Sign up
            </Link>
          </div>
        </div>
      </header>

      <main>
        {/* Intro */}
        <section className="relative">
          <div className="cz-grid pointer-events-none absolute inset-0" aria-hidden="true" />
          <div className={`${container} relative pt-16 pb-16 sm:pt-24`}>
            <Reveal>
              <Label>Proof · recorded, not mocked up</Label>
              <h1 className="font-display mt-8 text-5xl leading-[0.95] font-semibold tracking-[-0.05em] sm:text-7xl">
                <span className="block text-white">A real phone call.</span>
                <span className="block text-zinc-600">Start to finish.</span>
              </h1>
              <p className="mt-8 max-w-2xl text-lg leading-relaxed text-zinc-400">
                Below is a real screening call from our test sessions: the AI rings a real
                phone, holds the conversation, and the transcript and answers fill in on screen
                while it happens. Then the build log, phase by phase, with how each one was
                checked.
              </p>
            </Reveal>
            <div className="mt-12 grid grid-cols-2 border-t border-l border-white/10 lg:grid-cols-4">
              {RESULTS.map((r, i) => (
                <Reveal key={r.label} delay={i * 70} className="border-r border-b border-white/10 p-6">
                  <p className="font-display text-4xl font-semibold tracking-[-0.04em] sm:text-5xl">{r.value}</p>
                  <p className="mt-2 font-mono text-[11px] leading-relaxed tracking-[0.16em] text-zinc-500 uppercase">{r.label}</p>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* The recording */}
        <section className={`${container} pt-12`} aria-labelledby="recording">
          <Reveal className="mb-8 flex flex-wrap items-end justify-between gap-4">
            <div>
              <Label>Live test · 20 Nov 2026 · 3 min</Label>
              <h2 id="recording" className="font-display mt-5 text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">
                The phone on the left, the app on the right
              </h2>
            </div>
          </Reveal>
          <Reveal delay={80}>
            <CallRecording />
          </Reveal>
          <p className="mt-5 max-w-3xl text-sm leading-relaxed text-zinc-500">
            Recorded during development, when CallZest was still called HireCall, so the old name
            and a few early screens appear. The tester called themself; their phone number and
            email are blurred. The call audio starts once the phone&apos;s own recording was
            switched on, a few seconds into the call.
          </p>
        </section>

        {/* Build log */}
        <section className={`${container} pt-28 pb-28`} aria-labelledby="build-log">
          <Reveal className="mb-10 flex flex-wrap items-end justify-between gap-6">
            <div>
              <Label>Build log</Label>
              <h2 id="build-log" className="font-display mt-6 text-5xl leading-[0.95] font-semibold tracking-[-0.045em] sm:text-6xl">
                <span className="block text-white">Ten phases.</span>
                <span className="block text-zinc-600">Each one tested.</span>
              </h2>
            </div>
            <p className="max-w-sm leading-relaxed text-zinc-400">
              Every phase ended with a written report: what was built, how, and the checks it had
              to pass before the next one started. Open any phase to read it.
            </p>
          </Reveal>

          <ol className="border-t border-white/10">
            {PHASES.map((p) => (
              <li key={p.n} className="border-b border-white/10">
                <details className="group">
                  <summary className="grid cursor-pointer list-none gap-2 py-6 sm:grid-cols-[72px_1fr_auto] sm:items-baseline sm:gap-6 [&::-webkit-details-marker]:hidden">
                    <span className="font-mono text-sm text-zinc-600 transition-colors group-open:text-white">
                      {String(p.n).padStart(2, "0")}
                    </span>
                    <span>
                      <span className="font-display block text-2xl font-semibold tracking-[-0.03em] text-zinc-200 transition-colors group-hover:text-white group-open:text-white">
                        {p.title}
                      </span>
                      <span className="mt-1.5 block max-w-3xl leading-relaxed text-zinc-500">{p.summary}</span>
                    </span>
                    <span className="flex items-center gap-4 font-mono text-[11px] tracking-[0.2em] text-zinc-600 uppercase">
                      {p.date}
                      <span className="text-lg leading-none text-zinc-500 transition-transform group-open:rotate-45" aria-hidden="true">
                        +
                      </span>
                    </span>
                  </summary>
                  <div className="grid gap-6 pb-8 sm:grid-cols-[72px_1fr_1fr] sm:gap-6">
                    <span className="hidden sm:block" />
                    <div>
                      <p className="mb-3 font-mono text-[11px] tracking-[0.2em] text-zinc-500 uppercase">What was built</p>
                      <ul className="space-y-2 text-sm leading-relaxed text-zinc-300">
                        {p.done.map((d) => (
                          <li key={d} className="flex gap-3">
                            <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-zinc-500" aria-hidden="true" />
                            {d}
                          </li>
                        ))}
                      </ul>
                    </div>
                    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-5">
                      <p className="mb-3 font-mono text-[11px] tracking-[0.2em] text-zinc-500 uppercase">How it was checked</p>
                      <ul className="space-y-2 text-sm leading-relaxed text-zinc-200">
                        {p.checked.map((c) => (
                          <li key={c} className="flex gap-2.5">
                            <Check />
                            {c}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </details>
              </li>
            ))}
          </ol>
          <p className="mt-6 text-sm text-zinc-500">
            Reports were written during development under the product&apos;s earlier name,
            HireCall. Screens in them showed fictional demo candidates.
          </p>
        </section>
      </main>

      <footer className="border-t border-white/[0.08]">
        <div className={`${container} flex flex-col items-center justify-between gap-5 py-10 sm:flex-row`}>
          <Logo className="text-white" markClassName="h-5 w-5" textClassName="text-base" />
          <p className="font-mono text-[11px] tracking-[0.22em] text-zinc-500 uppercase">© 2026 CallZest · AI phone screening</p>
          <Link href="/" className="font-mono text-[11px] tracking-[0.22em] text-zinc-400 uppercase hover:text-white">
            Home
          </Link>
        </div>
      </footer>
    </div>
  );
}

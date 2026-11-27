import type { ReactNode } from "react";
import Link from "next/link";

import { FlowPreview } from "@/components/flow/flow-canvas";
import { LiveCall } from "@/components/landing/live-call";
import { Reveal, ScrollProgress, SpotlightRows, type Row } from "@/components/landing/motion";
import { Logo } from "@/components/logo";
import { TOTAL_SECONDS } from "@/components/walkthrough/scenes";
import { Walkthrough } from "@/components/walkthrough/walkthrough";

export const metadata = {
  title: "CallZest · AI phone screening for recruiters",
  description:
    "CallZest's AI recruiter calls your candidates, asks your screening questions and hands you structured answers, a transcript and a summary.",
};

export default function Home() {
  return (
    <div className="relative flex-1 overflow-x-clip bg-black font-sans text-white">
      <ScrollProgress />
      <Header />
      <main>
        <Hero />
        <Marquee />
        <Features />
        <WalkthroughSection />
        <FlowSection />
        <Numbers />
        <Responsible />
        <FinalCta />
      </main>
      <Footer />
    </div>
  );
}

/* Shared pieces */

function Arrow({ className = "h-3.5 w-3.5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M7 17 17 7M8 7h9v9" />
    </svg>
  );
}

function PrimaryPill({ href, children, large = false }: { href: string; children: ReactNode; large?: boolean }) {
  return (
    <Link
      href={href}
      className={`group inline-flex items-center gap-3 rounded-full bg-white font-medium text-black shadow-[0_0_40px_-8px_rgb(255_255_255/0.35)] transition hover:bg-zinc-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white ${
        large ? "py-2 pr-2 pl-6 text-base" : "py-1.5 pr-1.5 pl-5 text-sm"
      }`}
    >
      {children}
      <span
        className={`flex items-center justify-center rounded-full bg-black text-white transition-transform duration-300 group-hover:rotate-45 ${
          large ? "h-10 w-10" : "h-8 w-8"
        }`}
      >
        <Arrow />
      </span>
    </Link>
  );
}

function GhostPill({ href, children, large = false }: { href: string; children: ReactNode; large?: boolean }) {
  const className = `inline-flex items-center gap-2.5 rounded-full border border-white/15 font-medium text-white transition hover:border-white/30 hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white ${
    large ? "px-6 py-3.5 text-base" : "px-5 py-2.5 text-sm"
  }`;
  return href.startsWith("#") ? (
    <a href={href} className={className}>
      {children}
    </a>
  ) : (
    <Link href={href} className={className}>
      {children}
    </Link>
  );
}

function Label({ children, live = false }: { children: ReactNode; live?: boolean }) {
  return (
    <p className="flex items-center gap-2.5 font-mono text-[11px] tracking-[0.25em] text-zinc-400 uppercase">
      <span className={`h-1.5 w-1.5 rounded-full ${live ? "animate-pulse bg-emerald-400" : "bg-zinc-500"}`} aria-hidden="true" />
      {children}
    </p>
  );
}

/** Two-tone headline: the first line bright, the second grey. */
function Headline({ top, bottom, className = "" }: { top: ReactNode; bottom: ReactNode; className?: string }) {
  return (
    <h2 className={`font-display leading-[0.95] font-semibold tracking-[-0.045em] ${className}`}>
      <span className="block text-white">{top}</span>
      <span className="block text-zinc-600">{bottom}</span>
    </h2>
  );
}

const container = "mx-auto w-full max-w-6xl px-5 sm:px-8";

/* Header */

function Header() {
  const link = "hidden rounded-lg px-3 py-2 font-mono text-[11px] tracking-[0.22em] text-zinc-400 uppercase transition-colors hover:text-white md:block";
  return (
    <header className="sticky top-0 z-50 border-b border-white/[0.06] bg-black/70 backdrop-blur-xl">
      <div className={`${container} flex h-16 items-center justify-between`}>
        <div className="flex items-center gap-6">
          <Link href="/" aria-label="CallZest home">
            <Logo className="text-white" markClassName="h-6 w-6" textClassName="text-lg" />
          </Link>
          <nav className="flex items-center">
            <a href="#features" className={link}>
              Features
            </a>
            <a href="#walkthrough" className={link}>
              Walkthrough
            </a>
            <a href="#flow" className={link}>
              How it works
            </a>
            <a href="#responsible" className={link}>
              Responsibly
            </a>
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/login" className="rounded-lg px-3 py-2 font-mono text-[11px] tracking-[0.22em] text-zinc-300 uppercase transition-colors hover:text-white">
            Log in
          </Link>
          <PrimaryPill href="/signup">Sign up</PrimaryPill>
        </div>
      </div>
    </header>
  );
}

/* Hero */

function Hero() {
  return (
    <section className="relative">
      <div className="cz-grid pointer-events-none absolute inset-0" aria-hidden="true" />
      <div
        className="pointer-events-none absolute -top-40 right-[-10%] h-[620px] w-[620px] rounded-full bg-white/[0.06] blur-[120px]"
        aria-hidden="true"
      />
      <div className={`${container} relative grid items-center gap-14 pt-16 pb-20 sm:pt-24 lg:grid-cols-[13fr_7fr] lg:gap-10 lg:pt-24 lg:pb-28`}>
        <div>
          <Reveal>
            <Label live>AI phone screening for recruiters</Label>
          </Reveal>

          <Reveal delay={80}>
            <h1 className="font-display mt-8 text-[52px] leading-[0.95] font-semibold tracking-[-0.05em] sm:text-7xl lg:text-[68px] xl:text-[78px]">
              <span className="block text-white">Every candidate.</span>
              <span className="block text-zinc-600">One phone call.</span>
            </h1>
          </Reveal>

          <Reveal delay={160}>
            <p className="mt-8 max-w-lg text-lg leading-relaxed text-zinc-400">
              CallZest&apos;s AI recruiter calls your candidates, asks your screening questions and
              hands you structured answers, a transcript and a summary. Your team only talks to the
              people worth talking to.
            </p>
          </Reveal>
          <Reveal delay={220}>
            <div className="mt-10 flex flex-wrap gap-3">
              <PrimaryPill href="/signup" large>
                Create your account
              </PrimaryPill>
              <GhostPill href="#walkthrough" large>
                <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor" aria-hidden="true">
                  <path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5Z" />
                </svg>
                Watch the walkthrough
              </GhostPill>
            </div>
          </Reveal>
        </div>

        <Reveal delay={280} className="flex justify-center lg:block">
          <LiveCall />
        </Reveal>
      </div>
    </section>
  );
}

/* Marquee */

const KEYWORDS = [
  "Real phone calls",
  "Live transcripts",
  "Structured answers",
  "Excel & CSV upload",
  "Automatic retries",
  "Scheduled callbacks",
  "Conflict checks",
  "Scored second round",
  "Calling hours",
  "Opt-outs respected",
];

function Marquee() {
  const items = [...KEYWORDS, ...KEYWORDS];
  return (
    <div className="overflow-hidden border-y border-white/[0.08] py-5 [mask-image:linear-gradient(90deg,transparent,black_12%,black_88%,transparent)]" aria-hidden="true">
      <div className="cz-marquee flex w-max items-center gap-10">
        {items.map((k, i) => (
          <span key={i} className="flex items-center gap-10 font-mono text-xs tracking-[0.28em] whitespace-nowrap text-zinc-400 uppercase">
            {k}
            <span className="h-1 w-1 rounded-full bg-zinc-600" />
          </span>
        ))}
      </div>
    </div>
  );
}

/* Walkthrough */

function WalkthroughSection() {
  return (
    <section id="walkthrough" className={`${container} scroll-mt-20 pt-24 sm:pt-32`}>
      <Reveal className="flex flex-wrap items-center justify-between gap-4">
        <Label>Walkthrough · {TOTAL_SECONDS} seconds</Label>
        <p className="hidden font-mono text-[11px] tracking-[0.25em] text-zinc-500 uppercase md:block">
          Job → List → Call → Live → Review → Round
        </p>
      </Reveal>
      <Reveal delay={80}>
        <Headline top="See it work." bottom="Feature by feature." className="mt-6 mb-12 text-5xl sm:text-6xl lg:text-7xl" />
      </Reveal>
      <Reveal delay={140}>
        <Walkthrough />
      </Reveal>
    </section>
  );
}

/* How it works: the flow chart preview */

function FlowSection() {
  return (
    <section id="flow" className={`${container} scroll-mt-20 pt-28 sm:pt-36`}>
      <Reveal className="flex flex-wrap items-center justify-between gap-4">
        <Label>How it works</Label>
        <p className="hidden font-mono text-[11px] tracking-[0.25em] text-zinc-500 uppercase md:block">25 steps · 5 stages</p>
      </Reveal>
      <Reveal delay={80} className="mt-6 mb-12 flex flex-wrap items-end justify-between gap-6">
        <Headline top="From a job" bottom="to a shortlist." className="text-5xl sm:text-6xl lg:text-7xl" />
        <p className="max-w-sm leading-relaxed text-zinc-400">
          Every step, every check and every outcome, the way CallZest actually runs. Open the full
          flow to explore each step.
        </p>
      </Reveal>
      <Reveal delay={140}>
        <FlowPreview />
      </Reveal>
    </section>
  );
}

/* Numbers */

const STATS = [
  { value: "0.7s", label: "until the AI starts replying" },
  { value: "10", label: "standard questions, plus your own" },
  { value: "3", label: "call attempts, retried for you" },
  { value: "100%", label: "of answers in the candidate's words" },
];

function Numbers() {
  return (
    <section aria-label="CallZest in numbers" className={`${container} pt-28 sm:pt-36`}>
      <div className="grid grid-cols-2 border-t border-l border-white/10 lg:grid-cols-4">
        {STATS.map((s, i) => (
          <Reveal key={s.label} delay={i * 80} className="border-r border-b border-white/10 p-6 sm:p-8">
            <p className="font-display text-5xl font-semibold tracking-[-0.04em] sm:text-6xl">{s.value}</p>
            <p className="mt-3 font-mono text-[11px] leading-relaxed tracking-[0.18em] text-zinc-500 uppercase">{s.label}</p>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

/* Features */

const FEATURES: Row[] = [
  {
    title: "Real phone calls",
    text: "Candidates get a normal call on their phone. No app, no link, nothing to install.",
    tag: "Nothing to install",
  },
  {
    title: "A natural conversation",
    text: "The AI waits for the candidate to finish, handles interruptions, accepts corrections and reads the answers back at the end.",
    tag: "Talks like a recruiter",
  },
  {
    title: "Answers you can trust",
    text: "Every value comes with the candidate's own words. When two answers disagree, you choose which one to keep.",
    tag: "Their own words",
  },
  {
    title: "Watch calls live",
    text: "Follow the transcript line by line while a call is in progress, and end it whenever you need to.",
    tag: "Live transcript",
  },
  {
    title: "A second round, scored",
    text: "Interested candidates get a short round of questions made from the job description. Each answer is scored, and you decide.",
    tag: "From the JD",
  },
  {
    title: "Retries and callbacks",
    text: "Unanswered calls are tried again on later days. \"Call me tomorrow at 5\" becomes a scheduled callback.",
    tag: "Automatic",
  },
];

function Features() {
  return (
    <section id="features" className={`${container} scroll-mt-20 pt-28 sm:pt-36`}>
      <div className="mb-14 flex flex-wrap items-end justify-between gap-8">
        <Reveal>
          <Label>Why CallZest</Label>
          <Headline top="Built for how" bottom="India screens." className="mt-6 text-5xl sm:text-6xl lg:text-7xl" />
        </Reveal>
        <Reveal delay={120} className="flex items-end gap-4">
          <span className="font-display text-8xl leading-none font-semibold tracking-[-0.06em] text-white sm:text-9xl">06</span>
          <span className="pb-3 font-mono text-[11px] leading-relaxed tracking-[0.22em] text-zinc-500 uppercase">
            Features in
            <br />
            every call
          </span>
        </Reveal>
      </div>
      <SpotlightRows rows={FEATURES} />
    </section>
  );
}

/* Calling responsibly */

const PROMISES = [
  "The AI always says it is an AI at the start of every call.",
  "Nobody is called without recorded consent.",
  "\"Don't call me again\" is final: the candidate is never called again.",
  "Calls happen only inside your calling days and hours, and one switch pauses all calling.",
  "Questions only a recruiter can answer are passed on to your team, not guessed.",
];

function Responsible() {
  return (
    <section id="responsible" className={`${container} scroll-mt-20 pt-28 sm:pt-36`}>
      <div className="grid gap-12 lg:grid-cols-[1fr_1.1fr] lg:gap-20">
        <Reveal>
          <Label>Calling responsibly</Label>
          <Headline top="Polite. Honest." bottom="On their terms." className="mt-6 text-5xl sm:text-6xl" />
          <p className="mt-6 max-w-md text-lg leading-relaxed text-zinc-400">
            A screening call is often a candidate&apos;s first contact with your company. CallZest is
            built to make it a good one.
          </p>
        </Reveal>
        <ul className="border-t border-white/10">
          {PROMISES.map((p, i) => (
            <Reveal key={p} delay={i * 60}>
              <li className="flex gap-5 border-b border-white/10 py-5">
                <span className="pt-0.5 font-mono text-xs text-zinc-600">{String(i + 1).padStart(2, "0")}</span>
                <span className="flex-1 leading-relaxed text-zinc-200">{p}</span>
                <svg viewBox="0 0 24 24" className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M5 12.5l4.5 4.5L19 7.5" />
                </svg>
              </li>
            </Reveal>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* Final call to action */

function FinalCta() {
  return (
    <section className="relative mt-28 overflow-hidden border-t border-white/[0.08] sm:mt-36">
      <div className="cz-grid pointer-events-none absolute inset-0" aria-hidden="true" />
      <div
        className="pointer-events-none absolute bottom-[-280px] left-1/2 h-[520px] w-[900px] -translate-x-1/2 rounded-full bg-white/[0.07] blur-[120px]"
        aria-hidden="true"
      />
      <div className={`${container} relative py-24 sm:py-32`}>
        <Reveal>
          <Label>Get started</Label>
          <h2 className="font-display mt-8 text-5xl leading-[0.95] font-semibold tracking-[-0.05em] sm:text-7xl lg:text-[96px]">
            <span className="block text-white">Spend your time on interviews.</span>
            <span className="block text-zinc-600">Not on first calls.</span>
          </h2>
        </Reveal>
        <Reveal delay={120}>
          <div className="mt-12 flex flex-wrap items-center gap-3">
            <PrimaryPill href="/signup" large>
              Create your account
            </PrimaryPill>
            <GhostPill href="/login" large>
              I already have one
            </GhostPill>
          </div>
          <p className="mt-6 text-sm text-zinc-500">Your team can join with logins from you.</p>
        </Reveal>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-white/[0.08]">
      <div className={`${container} flex flex-col items-center justify-between gap-5 py-10 sm:flex-row`}>
        <Logo className="text-white" markClassName="h-5 w-5" textClassName="text-base" />
        <p className="font-mono text-[11px] tracking-[0.22em] text-zinc-500 uppercase">© 2026 CallZest · AI phone screening</p>
        <div className="flex gap-6 font-mono text-[11px] tracking-[0.22em] text-zinc-400 uppercase">
          <Link href="/login" className="hover:text-white">
            Log in
          </Link>
          <Link href="/signup" className="hover:text-white">
            Sign up
          </Link>
        </div>
      </div>
    </footer>
  );
}

import type { ReactNode } from "react";
import Link from "next/link";

import { Logo } from "@/components/logo";

import { WavePanel } from "./login/wave-panel";

export const metadata = {
  title: "HireCall · AI phone screening for recruiters",
  description:
    "HireCall's AI recruiter calls your candidates, asks your screening questions and hands you structured answers, a transcript and a summary.",
};

const primaryButton =
  "inline-flex items-center justify-center rounded-xl bg-[#1d4ed8] px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#2563eb] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563eb]";
const secondaryButton =
  "inline-flex items-center justify-center rounded-xl border border-[#34363d] bg-[#24262b] px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-[#2c2e34] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-400";

export default function Home() {
  return (
    <div className="flex-1 bg-black font-sans text-white">
      <Header />
      <main className="mx-auto w-full max-w-6xl px-4 pb-16 sm:px-6">
        <Hero />
        <Stats />
        <HowItWorks />
        <Features />
        <Responsible />
        <FinalCta />
      </main>
      <Footer />
    </div>
  );
}

function Header() {
  return (
    <header className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
      <Link href="/" aria-label="HireCall home">
        <Logo className="text-white" markClassName="h-7 w-7" textClassName="text-xl" />
      </Link>
      <nav className="flex items-center gap-1 text-sm sm:gap-2">
        <a href="#how-it-works" className="hidden rounded-lg px-3 py-2 text-zinc-400 hover:text-white md:block">
          How it works
        </a>
        <a href="#features" className="hidden rounded-lg px-3 py-2 text-zinc-400 hover:text-white md:block">
          Features
        </a>
        <a href="#responsible" className="hidden rounded-lg px-3 py-2 text-zinc-400 hover:text-white md:block">
          Calling responsibly
        </a>
        <Link href="/login" className="ml-2 rounded-lg px-3 py-2 text-zinc-300 hover:text-white">
          Log in
        </Link>
        <Link href="/signup" className={`${primaryButton} px-4 py-2`}>
          Sign up
        </Link>
      </nav>
    </header>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden rounded-3xl">
      <div className="absolute inset-0">
        <WavePanel />
      </div>
      {/* Only the buttons take the pointer, so the waves still react to the cursor elsewhere */}
      <div className="pointer-events-none relative grid items-center gap-12 px-6 py-16 sm:px-12 lg:grid-cols-[1.1fr_1fr] lg:py-24">
        <div>
          <p className="inline-flex items-center gap-2 rounded-full border border-[#34363d] bg-black/40 px-3 py-1 text-xs text-zinc-300">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
            AI phone screening for recruiters
          </p>
          <h1 className="font-display mt-6 text-4xl leading-[1.1] font-semibold tracking-tight sm:text-5xl lg:text-[56px]">
            Screen every candidate with one phone call.
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-zinc-400">
            HireCall&apos;s AI recruiter calls your candidates, asks your screening questions and
            hands you structured answers, a transcript and a summary. Your team only talks to
            the people worth talking to.
          </p>
          <div className="pointer-events-auto mt-9 flex flex-wrap gap-3">
            <Link href="/signup" className={primaryButton}>
              Create your account
            </Link>
            <Link href="/login" className={secondaryButton}>
              Log in
            </Link>
            <a href="#how-it-works" className={secondaryButton}>
              See how it works
            </a>
          </div>
        </div>
        <CallPreview />
      </div>
    </section>
  );
}

/** A still picture of a call in progress, built like the app's own transcript. */
function CallPreview() {
  return (
    <div className="rounded-3xl border border-[#2a2c31] bg-[#18191c]/95 p-5 shadow-2xl shadow-black/60 sm:p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#24262b] text-xs font-medium text-zinc-300">
            PN
          </span>
          <div>
            <p className="text-sm font-medium">Priya Nair</p>
            <p className="text-xs text-zinc-500">Backend Developer</p>
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-400">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" aria-hidden="true" />
          On call · 01:12
        </span>
      </div>
      <ol className="mt-5 space-y-3 text-sm">
        <Line who="ai">
          Hi Priya, this is HireCall, an AI assistant calling about the Backend Developer role.
          Is now a good time?
        </Line>
        <Line who="candidate">Yes, go ahead.</Line>
        <Line who="ai">Great. What is your current CTC?</Line>
        <Line who="candidate">Around twelve lakhs.</Line>
      </ol>
      <div className="mt-5 rounded-2xl border border-[#2a2c31] bg-[#202226] p-4">
        <div className="flex items-center justify-between text-xs">
          <span className="text-zinc-500">Current CTC</span>
          <span className="rounded-full bg-sky-500/10 px-2 py-0.5 text-sky-400">Answered</span>
        </div>
        <p className="mt-1.5 font-medium">12 LPA</p>
        <p className="mt-0.5 text-xs text-zinc-500 italic">&ldquo;Around twelve lakhs&rdquo;</p>
      </div>
    </div>
  );
}

function Line({ who, children }: { who: "ai" | "candidate"; children: ReactNode }) {
  const ai = who === "ai";
  return (
    <li className={`flex flex-col ${ai ? "items-start" : "items-end"}`}>
      <span className="mb-1 text-[11px] text-zinc-500">{ai ? "HireCall AI" : "Candidate"}</span>
      <span
        className={`max-w-[85%] rounded-2xl px-3.5 py-2 leading-relaxed ${
          ai ? "rounded-tl-md bg-[#24262b] text-zinc-200" : "rounded-tr-md bg-[#1d4ed8]/25 text-blue-100"
        }`}
      >
        {children}
      </span>
    </li>
  );
}

const STATS = [
  { value: "0.7 s", label: "until the AI starts replying" },
  { value: "10", label: "standard screening questions, plus your own" },
  { value: "3", label: "call attempts, retried automatically" },
  { value: "100%", label: "of answers backed by the candidate's own words" },
];

function Stats() {
  return (
    <section aria-label="HireCall in numbers" className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-3xl bg-[#2a2c31] lg:grid-cols-4">
      {STATS.map((s) => (
        <div key={s.label} className="bg-[#18191c] px-6 py-7">
          <p className="font-display text-3xl font-semibold tracking-tight">{s.value}</p>
          <p className="mt-1.5 text-sm text-zinc-500">{s.label}</p>
        </div>
      ))}
    </section>
  );
}

function SectionHeading({ id, kicker, title, intro }: { id: string; kicker: string; title: string; intro: string }) {
  return (
    <div id={id} className="max-w-2xl scroll-mt-8">
      <p className="text-sm font-medium text-[#6b8cff]">{kicker}</p>
      <h2 className="font-display mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h2>
      <p className="mt-4 text-lg leading-relaxed text-zinc-400">{intro}</p>
    </div>
  );
}

const STEPS = [
  {
    title: "Add your candidates",
    text: "Upload a spreadsheet or add people by hand. Every row is checked and previewed before anything is saved, and duplicates are caught.",
  },
  {
    title: "The AI makes the calls",
    text: "Inside your calling hours, HireCall phones each candidate, says it is an AI, and asks your questions one at a time, like a recruiter would.",
  },
  {
    title: "Answers arrive structured",
    text: "Experience, CTC, notice period, location, interest and availability, each with the exact words the candidate used, plus a transcript and a summary.",
  },
  {
    title: "Your team picks it up",
    text: "Results land on the dashboard and in your Google Sheet. Missed calls are retried and callbacks happen at the time the candidate asked for.",
  },
];

function HowItWorks() {
  return (
    <section className="mt-28">
      <SectionHeading
        id="how-it-works"
        kicker="How it works"
        title="From a spreadsheet to screened candidates"
        intro="Four steps, and only the first one needs you."
      />
      <ol className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {STEPS.map((step, i) => (
          <li key={step.title} className="rounded-3xl bg-[#18191c] p-6">
            <span className="font-display flex h-9 w-9 items-center justify-center rounded-full bg-[#24262b] text-sm font-semibold text-zinc-300">
              {i + 1}
            </span>
            <h3 className="font-display mt-5 text-lg font-semibold">{step.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-zinc-400">{step.text}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

const FEATURES: { title: string; text: string; icon: ReactNode }[] = [
  {
    title: "Real phone calls",
    text: "Candidates get a normal call on their phone. No app, no link, nothing to install.",
    icon: <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />,
  },
  {
    title: "A natural conversation",
    text: "The AI waits for the candidate to finish, handles interruptions, accepts corrections and reads the answers back at the end.",
    icon: <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12Z" />,
  },
  {
    title: "Answers you can trust",
    text: "Every value comes with the candidate's own words. When two answers disagree, you choose which one to keep.",
    icon: <path d="M9 12l2 2 4-4M12 3l7 3v6c0 4.5-3 8-7 9-4-1-7-4.5-7-9V6l7-3Z" />,
  },
  {
    title: "Watch calls live",
    text: "Follow the transcript line by line while a call is in progress, and end it whenever you need to.",
    icon: (
      <>
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
        <circle cx="12" cy="12" r="3" />
      </>
    ),
  },
  {
    title: "Your Google Sheet, always current",
    text: "Every candidate is copied to your team's sheet and kept up to date after each call or edit.",
    icon: (
      <>
        <rect x="4" y="3" width="16" height="18" rx="2" />
        <path d="M4 9h16M4 15h16M10 3v18" />
      </>
    ),
  },
  {
    title: "Retries and callbacks",
    text: "Unanswered calls are tried again on later days, morning and afternoon. \"Call me tomorrow at 5\" becomes a scheduled callback.",
    icon: <path d="M3 12a9 9 0 0 1 15.5-6.2L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.2L3 16M3 21v-5h5" />,
  },
];

function Features() {
  return (
    <section className="mt-28">
      <SectionHeading
        id="features"
        kicker="Features"
        title="Everything a first screening call needs"
        intro="Built around how recruiting teams in India actually screen: CTC in lakhs, notice periods and callbacks included."
      />
      <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((f) => (
          <div key={f.title} className="rounded-3xl bg-[#18191c] p-6">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#24262b] text-zinc-200">
              <svg
                viewBox="0 0 24 24"
                className="h-5 w-5"
                fill="none"
                stroke="currentColor"
                strokeWidth={1.8}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                {f.icon}
              </svg>
            </span>
            <h3 className="font-display mt-5 text-lg font-semibold">{f.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-zinc-400">{f.text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

const PROMISES = [
  "The AI always says it is an AI at the start of every call.",
  "Nobody is called without recorded consent.",
  "\"Don't call me again\" is final: the candidate is never called again.",
  "Calls happen only inside your calling days and hours, and one switch pauses all calling.",
  "Questions only a recruiter can answer are passed on to your team, not guessed.",
];

function Responsible() {
  return (
    <section className="mt-28 grid gap-10 rounded-3xl bg-[#18191c] p-6 sm:p-10 lg:grid-cols-2 lg:p-12">
      <SectionHeading
        id="responsible"
        kicker="Calling responsibly"
        title="Polite, honest and on the candidate's terms"
        intro="A screening call is often a candidate's first contact with your company. HireCall is built to make it a good one."
      />
      <ul className="space-y-3 self-center">
        {PROMISES.map((p) => (
          <li key={p} className="flex gap-3 rounded-2xl bg-[#202226] px-4 py-3.5 text-sm leading-relaxed text-zinc-300">
            <svg
              viewBox="0 0 24 24"
              className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.2}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M5 12.5l4.5 4.5L19 7.5" />
            </svg>
            {p}
          </li>
        ))}
      </ul>
    </section>
  );
}

function FinalCta() {
  return (
    <section className="relative mt-28 overflow-hidden rounded-3xl">
      <div className="absolute inset-0">
        <WavePanel />
      </div>
      <div className="pointer-events-none relative px-6 py-20 text-center sm:px-12">
        <h2 className="font-display mx-auto max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">
          Spend your time on interviews, not first calls.
        </h2>
        <p className="mx-auto mt-4 max-w-lg text-zinc-400">
          Create an account for your company and start screening today. Your team can join with
          logins from you.
        </p>
        <div className="pointer-events-auto mt-8 flex flex-wrap justify-center gap-3">
          <Link href="/signup" className={primaryButton}>
            Create your account
          </Link>
          <Link href="/login" className={secondaryButton}>
            Log in
          </Link>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="mx-auto flex w-full max-w-6xl flex-col items-center justify-between gap-3 border-t border-[#1f2024] px-4 py-8 text-sm text-zinc-500 sm:flex-row sm:px-6">
      <Logo className="text-zinc-400" markClassName="h-5 w-5" textClassName="text-base" />
      <p>© 2026 HireCall. AI phone screening for recruiters.</p>
    </footer>
  );
}

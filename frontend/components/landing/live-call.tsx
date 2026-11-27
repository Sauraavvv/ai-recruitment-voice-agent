"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

/**
 * The hero's live call: transcript lines arrive one by one (with a "speaking" indicator first),
 * the call timer runs, and answers are captured as they are given. Loops; pauses off screen.
 */

type Line = { ai: boolean; text: string; answer?: [string, string] };

const SCRIPT: Line[] = [
  { ai: true, text: "Hi Priya, this is CallZest, an AI assistant calling about the Backend Developer role. Is now a good time?" },
  { ai: false, text: "Yes, go ahead." },
  { ai: true, text: "Great. Are you interested in this role?" },
  { ai: false, text: "Yes, I'm looking for a backend role in Pune.", answer: ["Interested", "Yes"] },
  { ai: true, text: "What is your notice period?" },
  { ai: false, text: "Thirty days. I can join early next month.", answer: ["Notice", "30 days"] },
  { ai: true, text: "Thanks. And your current CTC?" },
  { ai: false, text: "Around twelve lakhs.", answer: ["Current CTC", "12 LPA"] },
  { ai: true, text: "Got it. Let me read your answers back to you." },
];

const TYPING_MS = 900; // the "speaking" dots before each line
const LINE_MS = 2300; // from one line to the next
const END_PAUSE_MS = 3500; // hold the finished call before starting over
const START_SECONDS = 0;

function useLoopClock(active: boolean): number {
  const [ms, setMs] = useState(0);
  useEffect(() => {
    if (!active) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      setMs((m) => {
        const next = m + (now - last);
        return next >= SCRIPT.length * LINE_MS + END_PAUSE_MS ? 0 : next;
      });
      last = now;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active]);
  return ms;
}

const REDUCED = "(prefers-reduced-motion: reduce)";
function subscribeReduced(onChange: () => void) {
  const query = window.matchMedia(REDUCED);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

export function LiveCall() {
  const root = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(true);
  const reduced = useSyncExternalStore(
    subscribeReduced,
    () => window.matchMedia(REDUCED).matches,
    () => false,
  );

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const ms = useLoopClock(visible && !reduced);
  const elapsed = reduced ? SCRIPT.length * LINE_MS : ms;

  // A line shows once its "speaking" dots are done; the dots show just before it
  const shown = SCRIPT.filter((_, i) => elapsed >= i * LINE_MS + TYPING_MS);
  const speaking = SCRIPT.findIndex((_, i) => elapsed >= i * LINE_MS && elapsed < i * LINE_MS + TYPING_MS);
  const ended = shown.length === SCRIPT.length && elapsed >= SCRIPT.length * LINE_MS;
  const seconds = START_SECONDS + Math.floor(elapsed / 1000);
  const clock = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  const answers = shown.filter((l) => l.answer).map((l) => l.answer as [string, string]);

  return (
    <div ref={root} className="relative w-full max-w-[420px] lg:max-w-none">
      <div className="absolute -inset-6 rounded-[32px] bg-white/[0.05] blur-2xl" aria-hidden="true" />
      <div className="relative overflow-hidden rounded-3xl border border-white/10 bg-[#101113]/90 shadow-2xl shadow-black/60 backdrop-blur">
        {/* Header: who, and the running call */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/[0.06] text-xs font-medium text-zinc-300">PN</span>
            <div>
              <p className="text-sm font-medium">Priya Nair</p>
              <p className="text-xs text-zinc-500">Backend Developer</p>
            </div>
          </div>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs tabular-nums transition-colors ${
              ended ? "bg-white/5 text-zinc-400" : "bg-emerald-500/10 text-emerald-400"
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${ended ? "bg-zinc-500" : "animate-pulse bg-emerald-400"}`} aria-hidden="true" />
            {ended ? "Wrapping up" : "On call"} · {clock}
          </span>
        </div>

        {/* Transcript: newest at the bottom, older lines scroll away */}
        <ol
          aria-label="Live transcript"
          aria-live="polite"
          className="flex h-[360px] flex-col justify-end gap-2 overflow-hidden px-4 pt-4 pb-3 [mask-image:linear-gradient(to_bottom,transparent,black_22%)]"
        >
          {shown.map((line, i) => (
            <li key={i} className={`cz-rise flex flex-col ${line.ai ? "items-start" : "items-end"}`}>
              <span className="mb-0.5 px-1 text-[10px] text-zinc-500">{line.ai ? "CallZest AI" : "Priya"}</span>
              <span
                className={`max-w-[86%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                  line.ai ? "rounded-tl-md bg-white/[0.06] text-zinc-200" : "rounded-tr-md bg-[#1d4ed8]/25 text-blue-50"
                }`}
              >
                {line.text}
              </span>
            </li>
          ))}
          {speaking >= 0 && (
            <li className={`flex ${SCRIPT[speaking].ai ? "justify-start" : "justify-end"}`} aria-hidden="true">
              <span className="flex items-center gap-1 rounded-2xl bg-white/[0.04] px-3.5 py-3 text-zinc-400">
                <span className="cz-dot h-1.5 w-1.5 rounded-full bg-current" />
                <span className="cz-dot h-1.5 w-1.5 rounded-full bg-current [animation-delay:150ms]" />
                <span className="cz-dot h-1.5 w-1.5 rounded-full bg-current [animation-delay:300ms]" />
              </span>
            </li>
          )}
        </ol>

        {/* Answers captured so far */}
        <div className="grid grid-cols-3 gap-px border-t border-white/[0.06] bg-white/[0.06]">
          {(["Interested", "Notice", "Current CTC"] as const).map((key) => {
            const value = answers.find(([k]) => k === key)?.[1];
            return (
              <div key={key} className="bg-[#101113] px-3 py-3">
                <p className="text-[10px] tracking-wide text-zinc-500 uppercase">{key}</p>
                <p className={`mt-0.5 text-sm font-medium transition-colors duration-500 ${value ? "text-white" : "text-zinc-700"}`}>
                  {value ? <span className="cz-rise inline-block">{value}</span> : "—"}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

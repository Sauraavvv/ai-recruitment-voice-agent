"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { LogoMark } from "@/components/logo";

import { SceneView } from "./scene-views";
import { SCENES, type NavId } from "./scenes";

/** The app is drawn at this size and scaled to fit; phones drop the sidebar and use COMPACT_W. */
const W = 1180;
const COMPACT_W = 900;
const BAR = 36;
const H = 690;

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

/** Milliseconds into the current scene; resets when `sceneKey` changes, holds while paused. */
function useSceneClock(sceneKey: string, duration: number, playing: boolean, onDone: () => void): number {
  const [clock, setClock] = useState({ key: sceneKey, elapsed: 0 });
  const saved = useRef({ key: sceneKey, elapsed: 0 });
  const done = useRef(onDone);

  useEffect(() => {
    done.current = onDone;
  }, [onDone]);

  useEffect(() => {
    if (saved.current.key !== sceneKey) saved.current = { key: sceneKey, elapsed: 0 };
    if (!playing) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const elapsed = Math.min(duration, saved.current.elapsed + (now - last));
      last = now;
      saved.current = { key: sceneKey, elapsed };
      setClock(saved.current);
      if (elapsed >= duration) {
        done.current();
        return;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [sceneKey, duration, playing]);

  return clock.key === sceneKey ? clock.elapsed : 0;
}

function useStage(ref: React.RefObject<HTMLDivElement | null>) {
  const [available, setAvailable] = useState(W);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setAvailable(el.clientWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  const compact = available < 700;
  const width = compact ? COMPACT_W : W;
  return { width, scale: Math.min(1, available / width), compact };
}

function useInView(ref: React.RefObject<HTMLElement | null>): boolean {
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { threshold: 0.25 });
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return inView;
}

/* The app's own sidebar (Settings is left out: it is switched off in the app) */

const icon = (path: ReactNode) => (
  <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {path}
  </svg>
);

const NAV: { id: NavId; label: string; icon: ReactNode }[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    icon: icon(
      <>
        <rect x="3" y="3" width="7" height="9" rx="1.5" />
        <rect x="14" y="3" width="7" height="5" rx="1.5" />
        <rect x="14" y="12" width="7" height="9" rx="1.5" />
        <rect x="3" y="16" width="7" height="5" rx="1.5" />
      </>,
    ),
  },
  {
    id: "clients",
    label: "Your clients",
    icon: icon(<path d="M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16M16 9h3a2 2 0 0 1 2 2v10M3 21h18M8 7h4M8 11h4M8 15h4" />),
  },
  {
    id: "jobs",
    label: "Total jobs",
    icon: icon(
      <>
        <rect x="3" y="7" width="18" height="13" rx="2" />
        <path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18" />
      </>,
    ),
  },
  {
    id: "candidates",
    label: "Candidates",
    icon: icon(
      <>
        <circle cx="9" cy="8" r="3.5" />
        <path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14.5a6.5 6.5 0 0 1 3.5 5.5" />
      </>,
    ),
  },
  {
    id: "calls",
    label: "Screening calls",
    icon: icon(<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />),
  },
  {
    id: "telephonic",
    label: "Telephonic round",
    icon: icon(<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2M15 3a6 6 0 0 1 6 6M15 7a2 2 0 0 1 2 2" />),
  },
  {
    id: "questions",
    label: "Default questions",
    icon: icon(
      <>
        <path d="M9 6h11M9 12h11M9 18h11" />
        <circle cx="4.5" cy="6" r="1" />
        <circle cx="4.5" cy="12" r="1" />
        <circle cx="4.5" cy="18" r="1" />
      </>,
    ),
  },
  {
    id: "accounts",
    label: "Accounts",
    icon: icon(
      <>
        <circle cx="9" cy="8" r="3.5" />
        <path d="M2.5 20a6.5 6.5 0 0 1 13 0M19 8v6M16 11h6" />
      </>,
    ),
  },
];

function AppSidebar({ active }: { active: NavId }) {
  return (
    <div className="flex w-[228px] shrink-0 flex-col rounded-3xl bg-[#18191c] p-3">
      <div className="mb-5 flex h-10 items-center gap-2.5 px-2">
        <LogoMark className="h-6 w-6" />
        <span className="font-display text-lg font-semibold tracking-tight">CallZest</span>
      </div>
      <ul className="space-y-1">
        {NAV.map((item) => (
          <li
            key={item.id}
            className={`flex h-10 items-center gap-3 rounded-xl px-3 text-sm transition-colors duration-300 ${
              item.id === active ? "bg-white/10 font-medium text-white" : "text-zinc-400"
            }`}
          >
            {item.icon}
            {item.label}
          </li>
        ))}
      </ul>
      <div className="mt-auto rounded-2xl bg-white/[0.03] p-3">
        <p className="text-sm font-medium text-white">Asha Rao</p>
        <p className="text-xs text-zinc-500">Recruiter at Demo Hiring</p>
        <div className="mt-3 flex items-center justify-between border-t border-white/5 pt-3">
          <span className="text-xs text-zinc-400">Demo Hiring</span>
          <span className="rounded-full bg-amber-400/10 px-2 py-0.5 text-[10px] font-medium tracking-wide text-amber-300 uppercase ring-1 ring-amber-400/20">
            Super admin
          </span>
        </div>
      </div>
    </div>
  );
}

function Cursor({ pressed, ripple, visible, cursorRef }: {
  pressed: boolean;
  ripple: number | null;
  visible: boolean;
  cursorRef: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <div
      ref={cursorRef}
      aria-hidden="true"
      className="pointer-events-none absolute top-0 left-0 z-30 transition-[transform,opacity] duration-[750ms] ease-[cubic-bezier(0.22,1,0.36,1)]"
      style={{ transform: `translate(${W * 0.55}px, ${H * 0.75}px)`, opacity: visible ? 1 : 0 }}
    >
      {ripple !== null && <span key={ripple} className="cz-ripple absolute -top-4 -left-4 h-8 w-8 rounded-full border-2 border-white/80" />}
      <svg width="22" height="22" viewBox="0 0 24 24" className={`drop-shadow-[0_2px_6px_rgb(0_0_0/0.6)] transition-transform duration-150 ${pressed ? "scale-[0.82]" : ""}`}>
        <path
          d="M4.5 3.2 19.2 10c.8.4.7 1.5-.1 1.8l-6 1.9-2.4 5.8c-.3.8-1.5.8-1.8 0L3.3 4.5c-.3-.8.5-1.6 1.2-1.3Z"
          fill="white"
          stroke="black"
          strokeWidth="1.2"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

function PlayIcon({ paused }: { paused: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="currentColor" aria-hidden="true">
      {paused ? <path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5Z" /> : <path d="M6 4h4v16H6zM14 4h4v16h-4z" />}
    </svg>
  );
}

export function Walkthrough() {
  const reduced = useReducedMotion();
  const section = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const cursorRef = useRef<HTMLDivElement>(null);
  const inView = useInView(section);
  const { width: stageW, scale, compact } = useStage(frame);

  const [index, setIndex] = useState(0);
  const [run, setRun] = useState(0);
  const [paused, setPaused] = useState(false);
  const scene = SCENES[index];
  const playing = inView && !paused && !reduced;

  const next = useCallback(() => {
    setIndex((i) => (i + 1) % SCENES.length);
    setRun((n) => n + 1);
  }, []);
  const jump = (i: number) => {
    setIndex(i);
    setRun((n) => n + 1);
    setPaused(false);
  };

  const clock = useSceneClock(`${scene.id}:${run}`, scene.duration, playing, next);
  const e = reduced ? scene.duration : clock;

  const move = [...scene.cursor].reverse().find((c) => e >= c.at);
  const target = move?.target;
  const click = move?.click;
  const pressed = click !== undefined && e >= click && e < click + 220;
  const ripple = click !== undefined && e >= click && e < click + 550 ? click : null;

  // Glide the pointer to the centre of the element it is going for (in stage pixels)
  useLayoutEffect(() => {
    const root = stage.current;
    const pointer = cursorRef.current;
    if (!root || !pointer || !target) return;
    const el = root.querySelector<HTMLElement>(`[data-target="${target}"]`);
    if (!el) return;
    const box = root.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    const k = box.width / stageW || 1;
    const x = (r.left - box.left + r.width / 2) / k;
    const y = (r.top - box.top + r.height / 2) / k;
    pointer.style.transform = `translate(${x}px, ${y}px)`;
  }, [target, scene.id, run, stageW]);

  const stepIndex = scene.steps.reduce((acc, s, i) => (e >= s.at ? i : acc), 0);

  return (
    <div ref={section}>
      {/* Feature tabs */}
      <div className="mb-5 flex [scrollbar-width:none] items-center gap-2 overflow-x-auto pb-1">
        <button
          type="button"
          onClick={() => setPaused((p) => !p)}
          disabled={reduced}
          aria-label={paused ? "Play walkthrough" : "Pause walkthrough"}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-white/10 text-zinc-200 transition-colors hover:bg-white/5 disabled:opacity-40"
        >
          <PlayIcon paused={paused || reduced} />
        </button>
        {SCENES.map((s, i) => {
          const active = i === index;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => jump(i)}
              aria-current={active ? "step" : undefined}
              className={`relative h-10 shrink-0 overflow-hidden rounded-full border px-4 font-mono text-[11px] tracking-[0.16em] uppercase transition-colors ${
                active ? "border-white/40 text-white" : "border-white/10 text-zinc-500 hover:border-white/25 hover:text-zinc-200"
              }`}
            >
              {active && <span className="absolute inset-0 origin-left bg-white/[0.08]" style={{ transform: `scaleX(${e / s.duration})` }} />}
              <span className="relative">
                <span className={active ? "text-zinc-400" : "text-zinc-600"}>{String(i + 1).padStart(2, "0")}</span> {s.label}
              </span>
            </button>
          );
        })}
      </div>

      {/* The stage: CallZest itself, scaled to fit */}
      <div ref={frame} className="overflow-x-clip" style={{ height: (H + BAR) * scale }}>
        <div
          className="relative origin-top-left overflow-hidden rounded-[22px] border border-white/10 bg-black shadow-[0_50px_140px_-40px_rgb(0_0_0/0.95)]"
          style={{ width: stageW, height: H + BAR, transform: `scale(${scale})` }}
        >
          <div className="flex items-center gap-3 border-b border-white/[0.06] bg-[#0c0c0e] px-4" style={{ height: BAR }}>
            <span className="flex gap-1.5" aria-hidden="true">
              <span className="h-3 w-3 rounded-full bg-[#2a2b30]" />
              <span className="h-3 w-3 rounded-full bg-[#2a2b30]" />
              <span className="h-3 w-3 rounded-full bg-[#2a2b30]" />
            </span>
            <span className="mx-auto flex items-center gap-1.5 rounded-lg bg-white/[0.04] px-3 py-1 font-mono text-[11px] text-zinc-500">
              <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                <rect x="5" y="11" width="14" height="10" rx="2" />
                <path d="M8 11V8a4 4 0 0 1 8 0v3" />
              </svg>
              callzest.in{scene.path}
            </span>
            <span className="w-[48px]" />
          </div>
          <div ref={stage} className="relative font-sans text-white" style={{ height: H }} role="img" aria-label={`CallZest walkthrough: ${scene.title}`}>
            <div className="flex h-full gap-3 p-3">
              {!compact && <AppSidebar active={scene.nav} />}
              <div key={`${scene.id}:${run}`} className="cz-scene-in relative min-w-0 flex-1 overflow-hidden px-4 pt-3">
                <SceneView id={scene.id} e={e} />
              </div>
            </div>
            <Cursor cursorRef={cursorRef} pressed={pressed} ripple={ripple} visible={!reduced && target !== undefined} />
          </div>
        </div>
      </div>

      {/* What this step is, and how to use it, in step with the stage */}
      <div className="mt-8 grid gap-6 border-t border-white/10 pt-8 lg:grid-cols-[1fr_1.15fr]">
        <div>
          <p className="font-mono text-xs tracking-[0.2em] text-zinc-500">
            {String(index + 1).padStart(2, "0")} / {String(SCENES.length).padStart(2, "0")}
          </p>
          <h3 className="font-display mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">{scene.title}</h3>
          <p className="mt-2 max-w-md leading-relaxed text-zinc-400">{scene.summary}</p>
        </div>
        <ol className="space-y-1">
          {scene.steps.map((step, n) => {
            const state = reduced || n < stepIndex ? "done" : n === stepIndex ? "now" : "next";
            return (
              <li
                key={`${scene.id}-${step.text}`}
                className={`flex items-center gap-4 border-b border-white/[0.06] py-3 transition-colors duration-300 ${
                  state === "now" ? "text-white" : state === "done" ? "text-zinc-400" : "text-zinc-600"
                }`}
              >
                <span
                  className={`h-px shrink-0 transition-all duration-500 ${state === "now" ? "w-8 bg-white" : state === "done" ? "w-4 bg-zinc-500" : "w-4 bg-zinc-700"}`}
                  aria-hidden="true"
                />
                <span className="text-[15px] leading-snug">{step.text}</span>
                {state === "done" && <span className="ml-auto font-mono text-[10px] tracking-widest text-zinc-600 uppercase">done</span>}
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

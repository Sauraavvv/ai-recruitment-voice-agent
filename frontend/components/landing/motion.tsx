"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/** Fades its children up the first time they scroll into view. */
export function Reveal({ children, delay = 0, className = "" }: { children: ReactNode; delay?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          observer.disconnect();
        }
      },
      { threshold: 0.15 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return (
    <div
      ref={ref}
      style={{ transitionDelay: `${delay}ms` }}
      className={`transition-[opacity,translate] duration-700 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:translate-y-0 motion-reduce:opacity-100 motion-reduce:transition-none ${
        shown ? "translate-y-0 opacity-100" : "translate-y-6 opacity-0"
      } ${className}`}
    >
      {children}
    </div>
  );
}

/** A thin line across the top of the page showing how far down the reader is. */
export function ScrollProgress() {
  const [p, setP] = useState(0);
  useEffect(() => {
    const update = () => {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      setP(max > 0 ? window.scrollY / max : 0);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);
  return (
    <div aria-hidden="true" className="fixed inset-x-0 top-0 z-[60] h-px">
      <div className="h-full origin-left bg-white/70" style={{ transform: `scaleX(${p})` }} />
    </div>
  );
}

export type Row = { title: string; text: string; tag: string };

/** Numbered rows; the one nearest the middle of the screen is lit, the rest are dimmed. */
export function SpotlightRows({ rows }: { rows: Row[] }) {
  const refs = useRef<(HTMLLIElement | null)[]>([]);
  const [active, setActive] = useState(0);
  useEffect(() => {
    const update = () => {
      const middle = window.innerHeight * 0.5;
      let best = 0;
      let bestDistance = Infinity;
      refs.current.forEach((el, i) => {
        if (!el) return;
        const r = el.getBoundingClientRect();
        const d = Math.abs(r.top + r.height / 2 - middle);
        if (d < bestDistance) {
          bestDistance = d;
          best = i;
        }
      });
      setActive(best);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  return (
    <ol className="border-t border-white/10">
      {rows.map((row, i) => {
        const lit = i === active;
        return (
          <li
            key={row.title}
            ref={(el) => {
              refs.current[i] = el;
            }}
            onMouseEnter={() => setActive(i)}
            className="relative grid gap-3 border-b border-white/10 py-8 sm:grid-cols-[64px_1fr] lg:grid-cols-[96px_1fr_1.1fr_170px] lg:gap-8 lg:py-10"
          >
            <span
              aria-hidden="true"
              className={`absolute -bottom-px left-0 h-px bg-white transition-all duration-700 ${lit ? "w-full opacity-60" : "w-0 opacity-0"}`}
            />
            <span className={`font-mono text-sm transition-colors duration-500 ${lit ? "text-white" : "text-zinc-600"}`}>
              {String(i + 1).padStart(2, "0")}
            </span>
            <h3
              className={`font-display text-2xl font-semibold tracking-[-0.03em] transition-colors duration-500 sm:text-3xl ${
                lit ? "text-white" : "text-zinc-600"
              }`}
            >
              {row.title}
            </h3>
            <p className={`leading-relaxed transition-colors duration-500 sm:col-start-2 lg:col-start-auto ${lit ? "text-zinc-300" : "text-zinc-600"}`}>
              {row.text}
            </p>
            <span
              className={`font-mono text-[11px] tracking-[0.22em] uppercase transition-colors duration-500 sm:col-start-2 lg:col-start-auto lg:text-right ${
                lit ? "text-zinc-300" : "text-zinc-700"
              }`}
            >
              {row.tag}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

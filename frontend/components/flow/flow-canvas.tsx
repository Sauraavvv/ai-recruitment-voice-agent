"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

import {
  CANVAS_H,
  CANVAS_W,
  EDGES,
  GROUPS,
  NODE_H,
  NODE_W,
  NODES,
  RUN,
  byId,
  type FlowEdge,
  type FlowNode,
  type NodeKind,
  type Port,
} from "./flow-data";

const STEP_MS = 1500;

/* Geometry */

type P = { x: number; y: number };

function portPoint(n: FlowNode, port: Port): P {
  if (port === "left") return { x: n.x, y: n.y + NODE_H / 2 };
  if (port === "right") return { x: n.x + NODE_W, y: n.y + NODE_H / 2 };
  if (port === "top") return { x: n.x + NODE_W / 2, y: n.y };
  return { x: n.x + NODE_W / 2, y: n.y + NODE_H };
}

const DIR: Record<Port, P> = { left: { x: -1, y: 0 }, right: { x: 1, y: 0 }, top: { x: 0, y: -1 }, bottom: { x: 0, y: 1 } };

/** A polyline with rounded corners. */
function rounded(points: P[], r = 18): string {
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const [a, b, c] = [points[i - 1], points[i], points[i + 1]];
    const l1 = Math.hypot(b.x - a.x, b.y - a.y);
    const l2 = Math.hypot(c.x - b.x, c.y - b.y);
    const k = Math.min(r, l1 / 2, l2 / 2);
    const p1 = { x: b.x - ((b.x - a.x) / l1) * k, y: b.y - ((b.y - a.y) / l1) * k };
    const p2 = { x: b.x + ((c.x - b.x) / l2) * k, y: b.y + ((c.y - b.y) / l2) * k };
    d += ` L ${p1.x} ${p1.y} Q ${b.x} ${b.y} ${p2.x} ${p2.y}`;
  }
  const last = points[points.length - 1];
  return `${d} L ${last.x} ${last.y}`;
}

function edgeGeometry(e: FlowEdge): { d: string; label: P } {
  const a = byId(e.from);
  const b = byId(e.to);
  const fp = e.fromPort ?? "right";
  const tp = e.toPort ?? "left";
  const p1 = portPoint(a, fp);
  const p2 = portPoint(b, tp);
  if (e.wrapY !== undefined) {
    const pts = [p1, { x: p1.x + 36, y: p1.y }, { x: p1.x + 36, y: e.wrapY }, { x: p2.x - 30, y: e.wrapY }, { x: p2.x - 30, y: p2.y }, p2];
    return { d: rounded(pts), label: { x: p1.x + 36, y: (p1.y + e.wrapY) / 2 } };
  }
  const k = Math.max(40, Math.hypot(p2.x - p1.x, p2.y - p1.y) * 0.42);
  const c1 = { x: p1.x + DIR[fp].x * k, y: p1.y + DIR[fp].y * k };
  const c2 = { x: p2.x + DIR[tp].x * k, y: p2.y + DIR[tp].y * k };
  const mid = { x: (p1.x + 3 * c1.x + 3 * c2.x + p2.x) / 8, y: (p1.y + 3 * c1.y + 3 * c2.y + p2.y) / 8 };
  return { d: `M ${p1.x} ${p1.y} C ${c1.x} ${c1.y} ${c2.x} ${c2.y} ${p2.x} ${p2.y}`, label: mid };
}

/* Look of each kind of node */

const KIND: Record<NodeKind, { tag: string; panel: string }> = {
  you: { tag: "You", panel: "You do this" },
  auto: { tag: "CallZest", panel: "CallZest does this" },
  decision: { tag: "Check", panel: "CallZest checks" },
  outcome: { tag: "Then", panel: "What happens" },
  end: { tag: "Done", panel: "The result" },
};

function KindIcon({ kind }: { kind: NodeKind }) {
  const common = { viewBox: "0 0 24 24", className: "h-[18px] w-[18px]", fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  if (kind === "you")
    return (
      <svg {...common}>
        <circle cx="12" cy="8" r="3.5" />
        <path d="M5 20a7 7 0 0 1 14 0" />
      </svg>
    );
  if (kind === "auto")
    return (
      <svg {...common}>
        <path d="M12 3v3M12 18v3M3 12h3M18 12h3" />
        <path d="M12 8.5 13.2 11l2.3 1-2.3 1L12 15.5 10.8 13l-2.3-1 2.3-1Z" fill="currentColor" stroke="none" />
      </svg>
    );
  if (kind === "decision")
    return (
      <svg {...common}>
        <path d="M12 3.5 20.5 12 12 20.5 3.5 12Z" />
      </svg>
    );
  if (kind === "end")
    return (
      <svg {...common}>
        <path d="M5 12.5l4.5 4.5L19 7.5" />
      </svg>
    );
  return (
    <svg {...common}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

function NodeCard({ node, state, onSelect, selected }: {
  node: FlowNode;
  state: "active" | "visited" | "idle";
  selected: boolean;
  onSelect?: (id: string) => void;
}) {
  const outcome = node.kind === "outcome";
  const tile =
    node.kind === "you" || node.kind === "end"
      ? "bg-white text-black"
      : node.kind === "decision"
        ? "bg-white/[0.08] text-white"
        : outcome
          ? "bg-white/[0.03] text-zinc-400"
          : "bg-white/[0.08] text-zinc-100";
  const border =
    state === "active" || selected
      ? "border-white shadow-[0_0_0_4px_rgb(255_255_255/0.08),0_0_40px_-6px_rgb(255_255_255/0.35)]"
      : state === "visited"
        ? "border-white/30"
        : outcome
          ? "border-dashed border-white/15"
          : "border-white/10";
  const Tag = onSelect ? "button" : "div";
  return (
    <Tag
      type={onSelect ? "button" : undefined}
      onClick={onSelect ? () => onSelect(node.id) : undefined}
      onPointerDown={onSelect ? (e: React.PointerEvent) => e.stopPropagation() : undefined}
      style={{ left: node.x, top: node.y, width: NODE_W, height: NODE_H }}
      className={`absolute flex items-center gap-3 rounded-2xl border bg-[#141517] px-3 text-left transition-[border-color,box-shadow] duration-500 ${border} ${
        onSelect ? "cursor-pointer hover:border-white/40 focus-visible:outline-2 focus-visible:outline-white" : ""
      }`}
    >
      <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${tile}`}>
        <KindIcon kind={node.kind} />
      </span>
      <span className="min-w-0">
        <span className="block font-mono text-[9px] tracking-[0.2em] text-zinc-500 uppercase">{KIND[node.kind].tag}</span>
        <span className={`block truncate text-[13.5px] leading-tight font-semibold ${outcome ? "text-zinc-300" : "text-white"}`}>{node.title}</span>
        <span className="mt-0.5 block truncate text-[11.5px] text-zinc-500">{node.sub}</span>
      </span>
      {/* n8n-style connection points */}
      {!outcome && <span className="absolute top-1/2 -left-[5px] h-2.5 w-2.5 -translate-y-1/2 rounded-full border border-zinc-500 bg-[#141517]" />}
      {!outcome && node.kind !== "end" && (
        <span className="absolute top-1/2 -right-[5px] h-2.5 w-2.5 -translate-y-1/2 rounded-full border border-zinc-400 bg-zinc-300" />
      )}
    </Tag>
  );
}

/* The drawing: groups, wires, labels, nodes */

function Graph({ step, selected, onSelect }: { step: number; selected: string | null; onSelect?: (id: string) => void }) {
  const visited = useMemo(() => new Set(RUN.slice(0, step + 1)), [step]);
  const current = RUN[step];
  const entering = step > 0 ? `${RUN[step - 1]}>${current}` : null;
  const geometry = useMemo(() => EDGES.map((e) => ({ e, ...edgeGeometry(e) })), []);

  return (
    <div className="relative" style={{ width: CANVAS_W, height: CANVAS_H }}>
      <svg width={CANVAS_W} height={CANVAS_H} className="absolute inset-0" aria-hidden="true">
        {GROUPS.map((g) => (
          <g key={g.label}>
            <rect x={g.x} y={g.y} width={g.w} height={g.h} rx={24} fill="rgb(255 255 255 / 0.015)" stroke="rgb(255 255 255 / 0.07)" strokeDasharray="4 6" />
          </g>
        ))}
        {geometry.map(({ e, d }) => {
          const key = `${e.from}>${e.to}`;
          const lit = visited.has(e.from) && visited.has(e.to) && RUN.indexOf(e.to) === RUN.indexOf(e.from) + 1;
          const now = key === entering;
          return (
            <g key={key}>
              <path
                d={d}
                fill="none"
                stroke={now ? "#ffffff" : lit ? "rgb(255 255 255 / 0.45)" : "rgb(255 255 255 / 0.14)"}
                strokeWidth={now ? 2.2 : 1.6}
                strokeDasharray={e.dashed ? "5 6" : undefined}
                style={{ transition: "stroke 0.5s" }}
              />
              {now && (
                <circle r={4.5} fill="#fff" style={{ filter: "drop-shadow(0 0 6px #fff)" }}>
                  <animateMotion dur={`${STEP_MS / 1000}s`} repeatCount="1" fill="freeze" path={d} />
                </circle>
              )}
            </g>
          );
        })}
      </svg>

      {GROUPS.map((g) => (
        <span key={g.label} className="absolute font-mono text-[11px] tracking-[0.22em] text-zinc-500 uppercase" style={{ left: g.x + 22, top: g.y + 18 }}>
          {g.label}
        </span>
      ))}

      {geometry
        .filter(({ e }) => e.label)
        .map(({ e, label }) => (
          <span
            key={`${e.from}>${e.to}:label`}
            className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/10 bg-[#0b0b0c] px-2 py-0.5 font-mono text-[10px] tracking-wider text-zinc-400 uppercase"
            style={{ left: label.x, top: label.y }}
          >
            {e.label}
          </span>
        ))}

      {NODES.map((n) => (
        <NodeCard
          key={n.id}
          node={n}
          state={n.id === current ? "active" : visited.has(n.id) ? "visited" : "idle"}
          selected={selected === n.id}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

/* Shared run clock */

const REDUCED = "(prefers-reduced-motion: reduce)";
function subscribeReduced(onChange: () => void) {
  const query = window.matchMedia(REDUCED);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
function useReduced() {
  return useSyncExternalStore(subscribeReduced, () => window.matchMedia(REDUCED).matches, () => false);
}

function useRun(playing: boolean, loop: boolean, onEnd?: () => void): [number, (n: number) => void] {
  const [step, setStep] = useState(0);
  const end = useRef(onEnd);
  useEffect(() => {
    end.current = onEnd;
  }, [onEnd]);
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setStep((s) => {
        if (s + 1 < RUN.length) return s + 1;
        if (loop) return 0;
        end.current?.();
        return s;
      });
    }, STEP_MS);
    return () => window.clearInterval(id);
  }, [playing, loop]);
  return [step, setStep];
}

/* Home page preview: the whole flow, scaled to fit, running on its own */

export function FlowPreview() {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(CANVAS_W);
  const [inView, setInView] = useState(false);
  const reduced = useReduced();
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    const io = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { threshold: 0.2 });
    io.observe(el);
    return () => {
      ro.disconnect();
      io.disconnect();
    };
  }, []);
  const [step] = useRun(inView && !reduced, true);
  const scale = Math.min(1, (width - 32) / CANVAS_W);

  return (
    <div ref={box} className="cz-dots relative overflow-hidden rounded-[28px] border border-white/10 bg-[#0b0b0c] p-4">
      <div style={{ height: CANVAS_H * scale }}>
        <div className="origin-top-left" style={{ transform: `scale(${scale})`, width: CANVAS_W }}>
          <Graph step={reduced ? RUN.length - 1 : step} selected={null} />
        </div>
      </div>
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-[#0b0b0c] to-transparent" />
      <div className="absolute inset-x-0 bottom-6 flex justify-center">
        <Link
          href="/how-it-works"
          className="group inline-flex items-center gap-3 rounded-full bg-white py-1.5 pr-1.5 pl-5 text-sm font-medium text-black shadow-[0_0_40px_-8px_rgb(255_255_255/0.35)] transition hover:bg-zinc-200"
        >
          Open the full flow
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-black text-white transition-transform duration-300 group-hover:rotate-45">
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M7 17 17 7M8 7h9v9" />
            </svg>
          </span>
        </Link>
      </div>
    </div>
  );
}

/* The full page: pan, zoom, run, and a panel explaining the chosen step */

function ToolButton({ label, onClick, children, wide = false }: { label: string; onClick: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`flex h-10 items-center justify-center gap-2 rounded-full border whitespace-nowrap border-white/10 bg-[#141517]/90 text-sm text-zinc-200 backdrop-blur transition-colors hover:border-white/30 hover:text-white ${
        wide ? "px-4" : "w-10"
      }`}
    >
      {children}
    </button>
  );
}

export function FlowExplorer() {
  const viewport = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 0.6 });
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const reduced = useReduced();
  const [step, setStep] = useRun(playing && !reduced, false, () => setPlaying(false));

  const fit = useCallback(() => {
    const el = viewport.current;
    if (!el) return;
    // Phones: start readable at the first steps (drag for the rest). Wider: the whole flow.
    if (el.clientWidth < 700) {
      setView({ k: 0.62, x: -10, y: 110 });
      return;
    }
    const k = Math.min(el.clientWidth / (CANVAS_W + 80), el.clientHeight / (CANVAS_H + 80), 1);
    setView({ k, x: (el.clientWidth - CANVAS_W * k) / 2, y: (el.clientHeight - CANVAS_H * k) / 2 });
  }, []);

  useEffect(() => {
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [fit]);

  // Wheel zooms around the pointer (needs a non-passive listener to stop page scroll)
  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const mx = e.clientX - r.left;
      const my = e.clientY - r.top;
      setView((v) => {
        const k = Math.min(1.6, Math.max(0.25, v.k * Math.exp(-e.deltaY * 0.0015)));
        return { k, x: mx - ((mx - v.x) / v.k) * k, y: my - ((my - v.y) / v.k) * k };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const zoom = (factor: number) => {
    const el = viewport.current;
    if (!el) return;
    const mx = el.clientWidth / 2;
    const my = el.clientHeight / 2;
    setView((v) => {
      const k = Math.min(1.6, Math.max(0.25, v.k * factor));
      return { k, x: mx - ((mx - v.x) / v.k) * k, y: my - ((my - v.y) / v.k) * k };
    });
  };

  const run = () => {
    if (playing) {
      setPlaying(false);
      return;
    }
    if (step >= RUN.length - 1) setStep(0);
    setSelected(null);
    setPlaying(true);
  };

  const shown = selected ?? (playing || step > 0 ? RUN[step] : null);
  const node = shown ? byId(shown) : null;
  const next = node ? EDGES.filter((e) => e.from === node.id) : [];

  return (
    <div className="flex h-full w-full">
      <div className="relative min-w-0 flex-1">
      <div
        ref={viewport}
        className="cz-dots absolute inset-0 cursor-grab touch-none overflow-hidden bg-[#0b0b0c] active:cursor-grabbing"
        onPointerDown={(e) => {
          drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
          (e.target as Element).setPointerCapture?.(e.pointerId);
        }}
        onPointerMove={(e) => {
          const d = drag.current;
          if (!d) return;
          setView((v) => ({ ...v, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y }));
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        <div className="absolute top-0 left-0 origin-top-left" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})` }}>
          <Graph step={step} selected={selected} onSelect={(id) => setSelected((s) => (s === id ? null : id))} />
        </div>
      </div>

      {/* Toolbar */}
      <div className="absolute bottom-5 left-1/2 flex -translate-x-1/2 items-center gap-2">
        <ToolButton label={playing ? "Pause" : "Run the flow"} onClick={run} wide>
          <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="currentColor" aria-hidden="true">
            {playing ? <path d="M6 4h4v16H6zM14 4h4v16h-4z" /> : <path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5Z" />}
          </svg>
          {playing ? "Pause" : step > 0 ? "Run again" : "Run the flow"}
        </ToolButton>
        <ToolButton label="Zoom out" onClick={() => zoom(1 / 1.2)}>
          −
        </ToolButton>
        <ToolButton label="Zoom in" onClick={() => zoom(1.2)}>
          +
        </ToolButton>
        <ToolButton label="Fit to screen" onClick={fit}>
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" aria-hidden="true">
            <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
          </svg>
        </ToolButton>
      </div>

      </div>

      {/* Explanation panel: a column on wide screens, a sheet from the bottom on phones */}
      <aside
        aria-live="polite"
        className={`absolute inset-x-3 bottom-20 z-20 max-h-[60%] overflow-y-auto rounded-3xl border border-white/10 bg-[#141517]/95 p-6 shadow-2xl shadow-black/60 backdrop-blur transition-[opacity,translate] duration-300 lg:static lg:inset-auto lg:z-auto lg:max-h-none lg:w-[360px] lg:shrink-0 lg:translate-y-0 lg:rounded-none lg:border-0 lg:border-l lg:bg-black lg:opacity-100 lg:shadow-none ${
          node ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-3 opacity-0 lg:pointer-events-auto"
        }`}
      >
        {node ? (
          <>
            <div className="flex items-start justify-between gap-3">
              <p className="font-mono text-[10px] tracking-[0.22em] text-zinc-500 uppercase">{KIND[node.kind].panel}</p>
              {selected && (
                <button type="button" onClick={() => setSelected(null)} aria-label="Close" className="-mt-1 -mr-2 rounded-lg px-2 text-zinc-500 hover:text-white">
                  ✕
                </button>
              )}
            </div>
            <h2 className="font-display mt-3 text-2xl font-semibold tracking-[-0.03em]">{node.title}</h2>
            <p className="mt-1 text-sm text-zinc-500">{node.sub}</p>
            <p className="mt-4 text-[15px] leading-relaxed text-zinc-300">{node.detail}</p>
            {next.length > 0 && (
              <div className="mt-6 border-t border-white/10 pt-4">
                <p className="mb-2 font-mono text-[10px] tracking-[0.22em] text-zinc-500 uppercase">Next</p>
                <ul className="space-y-1.5">
                  {next.map((e) => (
                    <li key={e.to}>
                      <button
                        type="button"
                        onClick={() => setSelected(e.to)}
                        className="flex w-full items-center justify-between gap-3 rounded-xl bg-white/[0.04] px-3 py-2.5 text-left text-sm text-zinc-200 transition-colors hover:bg-white/[0.08]"
                      >
                        <span>{byId(e.to).title}</span>
                        {e.label && <span className="font-mono text-[10px] tracking-wider text-zinc-500 uppercase">{e.label}</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <>
            <p className="font-mono text-[10px] tracking-[0.22em] text-zinc-500 uppercase">Start here</p>
            <h2 className="font-display mt-3 text-2xl font-semibold tracking-[-0.03em]">Click any step</h2>
            <p className="mt-3 text-[15px] leading-relaxed text-zinc-400">
              Each box is one step. Press Run to watch a candidate go from your list to a scored
              shortlist, or click a box to read what happens there.
            </p>
            <ul className="mt-6 space-y-3 border-t border-white/10 pt-5 text-sm text-zinc-300">
              <li className="flex items-center gap-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-black"><KindIcon kind="you" /></span>
                You do this
              </li>
              <li className="flex items-center gap-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/[0.08]"><KindIcon kind="auto" /></span>
                CallZest does it for you
              </li>
              <li className="flex items-center gap-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/[0.08]"><KindIcon kind="decision" /></span>
                A check, with more than one way out
              </li>
              <li className="flex items-center gap-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-dashed border-white/25 text-zinc-400"><KindIcon kind="outcome" /></span>
                What happens on the other path
              </li>
            </ul>
          </>
        )}
      </aside>
    </div>
  );
}

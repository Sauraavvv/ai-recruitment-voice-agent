"use client";

import { type ReactNode, useEffect, useRef } from "react";

const BG = "#202226";
const WAVE = "#000000";
const SAMPLES = 72;
// Rendered at a fraction of the panel size: the blur hides the resolution and it's cheaper.
const SCALE = 0.35;
// The canvas overhangs the panel by this fraction on each side so the blur doesn't fade at
// the edges.
const BLEED = 0.08;

const bump = (x: number, center: number, width: number) => Math.exp(-(((x - center) / width) ** 2));

/**
 * Two blurred black waves on dark grey. They flow sideways on their own (travelling waves,
 * not just swaying), and the cursor pushes them away like a finger in water. Static when the
 * user prefers reduced motion.
 */
export function WavePanel({ children }: { children?: ReactNode }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!wrap || !canvas || !ctx) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Pointer in 0..1 canvas coordinates, eased toward its target; `hover` fades 0..1
    const pointer = { x: 0.5, y: 0.5, tx: 0.5, ty: 0.5, hover: 0, targetHover: 0 };
    let width = 0;
    let height = 0;
    let frame = 0;
    const start = performance.now();

    const resize = () => {
      const rect = wrap.getBoundingClientRect();
      width = Math.max(1, Math.round(rect.width * (1 + 2 * BLEED) * SCALE));
      height = Math.max(1, Math.round(rect.height * (1 + 2 * BLEED) * SCALE));
      canvas.width = width;
      canvas.height = height;
    };

    // Top wave: a lobe that hangs down, its crest travelling left → right and wrapping round
    const topEdge = (x: number, t: number) => {
      const crest = ((t * 0.035 + 0.15) % 1.4) - 0.2;
      return (
        0.16 +
        0.11 * bump(x, crest, 0.24) +
        0.05 * bump(x, crest - 0.7, 0.22) +
        0.018 * Math.sin(x * 7 - t * 0.9) +
        0.008 * Math.sin(x * 13 - t * 1.6)
      );
    };

    // Bottom wave: a hill whose crest travels right → left, with ripples running the other way
    const bottomEdge = (x: number, t: number) => {
      const crest = 1.2 - ((t * 0.03 + 0.35) % 1.4);
      return (
        0.86 -
        0.16 * bump(x, crest, 0.28) -
        0.07 * bump(x, crest + 0.7, 0.24) +
        0.015 * Math.sin(x * 6 + t * 0.8) +
        0.008 * Math.sin(x * 11 + t * 1.4)
      );
    };

    // The cursor pushes an edge away from itself, strongest right under it.
    const push = (x: number, edge: number) => {
      const gap = edge - pointer.y;
      const strength = pointer.hover * bump(x, pointer.x, 0.16) * bump(gap, 0, 0.28);
      return Math.sign(gap || 1) * 0.08 * strength;
    };

    const draw = (now: number) => {
      const t = reduceMotion ? 6 : (now - start) / 1000;
      pointer.x += (pointer.tx - pointer.x) * 0.07;
      pointer.y += (pointer.ty - pointer.y) * 0.07;
      pointer.hover += (pointer.targetHover - pointer.hover) * 0.05;

      ctx.fillStyle = BG;
      ctx.fillRect(0, 0, width, height);
      ctx.fillStyle = WAVE;

      ctx.beginPath();
      ctx.moveTo(0, 0);
      for (let i = 0; i <= SAMPLES; i++) {
        const x = i / SAMPLES;
        const edge = topEdge(x, t);
        ctx.lineTo(x * width, (edge + push(x, edge)) * height);
      }
      ctx.lineTo(width, 0);
      ctx.closePath();
      ctx.fill();

      ctx.beginPath();
      ctx.moveTo(0, height);
      for (let i = 0; i <= SAMPLES; i++) {
        const x = i / SAMPLES;
        const edge = bottomEdge(x, t);
        ctx.lineTo(x * width, (edge + push(x, edge)) * height);
      }
      ctx.lineTo(width, height);
      ctx.closePath();
      ctx.fill();

      if (!reduceMotion) frame = requestAnimationFrame(draw);
    };

    const onMove = (event: PointerEvent) => {
      const rect = wrap.getBoundingClientRect();
      // panel coordinates → canvas coordinates (the canvas is larger by BLEED on each side)
      pointer.tx = ((event.clientX - rect.left) / rect.width + BLEED) / (1 + 2 * BLEED);
      pointer.ty = ((event.clientY - rect.top) / rect.height + BLEED) / (1 + 2 * BLEED);
      pointer.targetHover = 1;
    };
    const onLeave = () => {
      pointer.targetHover = 0;
    };

    resize();
    const observer = new ResizeObserver(() => {
      resize();
      if (reduceMotion) draw(performance.now());
    });
    observer.observe(wrap);
    wrap.addEventListener("pointermove", onMove);
    wrap.addEventListener("pointerleave", onLeave);
    frame = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      wrap.removeEventListener("pointermove", onMove);
      wrap.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  return (
    <div
      ref={wrapRef}
      className="relative h-full w-full overflow-hidden"
      style={{ background: BG }}
    >
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className="absolute top-[-8%] left-[-8%] h-[116%] w-[116%] blur-[44px]"
      />
      <div className="pointer-events-none relative flex h-full items-center justify-center">
        {children}
      </div>
    </div>
  );
}

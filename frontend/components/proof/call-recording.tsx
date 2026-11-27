"use client";

import { useEffect, useRef, useState } from "react";

import { MOMENTS } from "./build-log";

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** The recorded test call, with buttons that jump to its key moments. */
export function CallRecording() {
  const video = useRef<HTMLVideoElement>(null);
  const [now, setNow] = useState(0);

  useEffect(() => {
    const el = video.current;
    if (!el) return;
    const update = () => setNow(el.currentTime);
    el.addEventListener("timeupdate", update);
    return () => el.removeEventListener("timeupdate", update);
  }, []);

  const current = MOMENTS.reduce((acc, m, i) => (now >= m.at ? i : acc), 0);

  function jump(at: number) {
    const el = video.current;
    if (!el) return;
    el.currentTime = at;
    void el.play().catch(() => undefined);
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
      <div className="overflow-hidden rounded-[22px] border border-white/10 bg-black shadow-[0_50px_140px_-40px_rgb(0_0_0/0.95)]">
        <video
          ref={video}
          controls
          playsInline
          preload="metadata"
          poster="/proof/live-call-poster.jpg"
          className="block aspect-video w-full bg-black"
        >
          <source src="/proof/live-call.mp4" type="video/mp4" />
          Your browser can&apos;t play this video.
        </video>
      </div>
      <ol className="space-y-1" aria-label="Key moments">
        {MOMENTS.map((m, i) => (
          <li key={m.at}>
            <button
              type="button"
              onClick={() => jump(m.at)}
              className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition-colors ${
                i === current && now > 0 ? "bg-white/[0.08] text-white" : "text-zinc-400 hover:bg-white/[0.04] hover:text-white"
              }`}
            >
              <span className="w-10 shrink-0 font-mono text-xs text-zinc-500 tabular-nums">{clock(m.at)}</span>
              {m.label}
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

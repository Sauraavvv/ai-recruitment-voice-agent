"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { fieldLabel, fieldValue } from "@/lib/labels";

import { DemoAudio } from "./demo-audio";

type Line = { seq: number; speaker: "assistant" | "candidate"; text: string; interrupted?: boolean };
type Field = { key: string; value: unknown; status: string; quote?: string | null };
type Phase = "intro" | "connecting" | "live" | "ended" | "error";

const DEMO_KEYS = ["interested", "total_experience", "notice_period", "current_ctc"];

/** Where the demo's WebSocket lives. Vercel can't proxy WebSockets, so the browser goes straight
 * to the backend: NEXT_PUBLIC_DEMO_WS_URL when set, else api.callzest.in in production. */
function demoUrl(): string {
  const configured = process.env.NEXT_PUBLIC_DEMO_WS_URL;
  if (configured) return configured;
  const { protocol, hostname } = window.location;
  if (hostname === "callzest.in" || hostname.endsWith(".callzest.in")) {
    return "wss://api.callzest.in/api/v1/demo/stream";
  }
  return `${protocol === "https:" ? "wss" : "ws"}://${hostname}:8000/api/v1/demo/stream`;
}

const clock = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

function PhoneIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />
    </svg>
  );
}

/** The button that opens the demo. `variant` matches the page's pill buttons. */
export function DemoCallButton({ large = false, variant = "ghost" }: { large?: boolean; variant?: "ghost" | "primary" }) {
  const [open, setOpen] = useState(false);
  const base = large ? "px-6 py-3.5 text-base" : "px-5 py-2.5 text-sm";
  const look =
    variant === "primary"
      ? "bg-white text-black hover:bg-zinc-200 shadow-[0_0_40px_-8px_rgb(255_255_255/0.35)]"
      : "border border-white/15 text-white hover:border-white/30 hover:bg-white/5";
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`inline-flex items-center gap-2.5 rounded-full font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white ${base} ${look}`}
      >
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
        </span>
        Try a demo call
      </button>
      {/* In <body>: the button sits inside animated (transformed) sections, which would trap a
          fixed overlay inside them */}
      {open && createPortal(<DemoCallDialog onClose={() => setOpen(false)} />, document.body)}
    </>
  );
}

function DemoCallDialog({ onClose }: { onClose: () => void }) {
  const [phase, setPhase] = useState<Phase>("intro");
  const [name, setName] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [fields, setFields] = useState<Field[]>([]);
  const [error, setError] = useState("");
  const [seconds, setSeconds] = useState(0);
  const [maxSeconds, setMaxSeconds] = useState(150);
  const [level, setLevel] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const ws = useRef<WebSocket | null>(null);
  const audio = useRef<DemoAudio | null>(null);
  const listRef = useRef<HTMLOListElement>(null);
  const ended = useRef(false);

  const teardown = useCallback(() => {
    audio.current?.stop();
    audio.current = null;
    const socket = ws.current;
    ws.current = null;
    if (socket && socket.readyState <= WebSocket.OPEN) socket.close();
  }, []);

  useEffect(() => teardown, [teardown]);

  // Timer and meters while live
  useEffect(() => {
    if (phase !== "live") return;
    const started = Date.now();
    const tick = window.setInterval(() => {
      setSeconds(Math.floor((Date.now() - started) / 1000));
      setLevel(audio.current?.level ?? 0);
      setSpeaking(audio.current?.speaking ?? false);
    }, 120);
    return () => window.clearInterval(tick);
  }, [phase]);

  // Newest line in view
  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [lines]);

  const fail = useCallback(
    (message: string) => {
      setError(message);
      setPhase("error");
      teardown();
    },
    [teardown],
  );

  async function start() {
    setPhase("connecting");
    setLines([]);
    setFields([]);
    ended.current = false;
    const send = (message: unknown) => {
      const open = ws.current;
      if (open?.readyState === WebSocket.OPEN) open.send(JSON.stringify(message));
    };
    const engine = new DemoAudio(send);
    audio.current = engine;
    try {
      await engine.start(); // microphone permission is asked here, before the call connects
    } catch {
      fail("We need your microphone for the demo. Allow it in your browser and try again.");
      return;
    }
    let socket: WebSocket;
    try {
      socket = new WebSocket(demoUrl());
    } catch {
      fail("Couldn't reach the demo. Please try again.");
      return;
    }
    ws.current = socket;

    socket.onopen = () => send({ event: "start", name });
    socket.onmessage = (event) => {
      let message: Record<string, unknown>;
      try {
        message = JSON.parse(String(event.data));
      } catch {
        return;
      }
      switch (message.event) {
        case "ready":
          setMaxSeconds(Number(message.max_seconds) || 150);
          setPhase("live");
          break;
        case "media":
          engine.play(String((message.media as { payload?: string })?.payload ?? ""));
          break;
        case "mark":
          engine.mark(String((message.mark as { name?: string })?.name ?? ""));
          break;
        case "clear":
          engine.clear();
          break;
        case "transcript":
          setLines((message.lines as Line[]) ?? []);
          break;
        case "answers":
          setFields((message.fields as Field[]) ?? []);
          break;
        case "ended":
          ended.current = true;
          setFields((message.fields as Field[]) ?? []);
          // Let the goodbye finish playing before the microphone and speaker close
          window.setTimeout(() => {
            setPhase("ended");
            teardown();
          }, 1200);
          break;
        case "error":
          ended.current = true;
          fail(String(message.message ?? "The demo call couldn't start."));
          break;
      }
    };
    socket.onclose = () => {
      if (!ended.current) fail("The call was cut off. Please try again.");
    };
    socket.onerror = () => {
      if (!ended.current) fail("Couldn't reach the demo. Please try again in a minute.");
    };
  }

  function hangUp() {
    const socket = ws.current;
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ event: "stop" }));
    audio.current?.clear();
  }

  function close() {
    if (phase === "live") hangUp();
    teardown();
    onClose();
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const byKey = new Map(fields.map((f) => [f.key, f]));

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Demo call">
      <div className="relative flex max-h-[calc(100dvh-2rem)] w-full max-w-[520px] flex-col overflow-hidden rounded-3xl border border-white/10 bg-[#101113] shadow-2xl shadow-black/70">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-4">
          <div className="flex items-center gap-3">
            <span className={`flex h-9 w-9 items-center justify-center rounded-full ${phase === "live" ? "bg-emerald-500/15 text-emerald-400" : "bg-white/[0.06] text-zinc-300"}`}>
              <PhoneIcon />
            </span>
            <div>
              <p className="text-sm font-medium">CallZest AI recruiter</p>
              <p className="text-xs text-zinc-500">Demo · Backend Developer, Pune</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {phase === "live" && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-400 tabular-nums">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                On call · {clock(seconds)}
              </span>
            )}
            <button type="button" onClick={close} aria-label="Close demo" className="rounded-lg px-2 py-1 text-zinc-500 hover:text-white">
              ✕
            </button>
          </div>
        </div>

        {phase === "intro" && (
          <form
            className="px-6 py-6"
            onSubmit={(e) => {
              e.preventDefault();
              void start();
            }}
          >
            <h2 className="font-display text-2xl font-semibold tracking-[-0.03em]">Take a screening call</h2>
            <p className="mt-2 text-sm leading-relaxed text-zinc-400">
              Talk to CallZest&apos;s AI recruiter right here in your browser. It asks a few quick
              questions about a demo Backend Developer role, then shows you the answers it
              captured. About two minutes, one demo call per visitor. Nothing is saved.
            </p>
            <label className="mt-6 block text-sm">
              <span className="mb-2 block text-zinc-300">Your first name</span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={40}
                required
                autoFocus
                placeholder="Asha"
                className="h-11 w-full rounded-xl border border-white/10 bg-white/[0.04] px-4 text-white outline-none placeholder:text-zinc-600 focus:border-white/30"
              />
            </label>
            <ul className="mt-5 space-y-1.5 text-xs text-zinc-500">
              <li>• Your browser will ask for the microphone.</li>
              <li>• Headphones work best, so the AI doesn&apos;t hear itself.</li>
              <li>• Answer as if you were a candidate. Any answers are fine.</li>
            </ul>
            <button
              type="submit"
              className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-full bg-white py-3 text-sm font-medium text-black transition hover:bg-zinc-200"
            >
              <PhoneIcon /> Start the call
            </button>
          </form>
        )}

        {phase === "connecting" && (
          <div className="flex flex-col items-center px-6 py-16 text-center">
            <span className="h-8 w-8 animate-spin rounded-full border-2 border-white/15 border-t-white" />
            <p className="font-display mt-5 font-semibold">Connecting the call…</p>
            <p className="mt-1 text-sm text-zinc-500">Allow the microphone if your browser asks.</p>
          </div>
        )}

        {(phase === "live" || phase === "ended") && (
          <>
            <ol ref={listRef} aria-live="polite" className="flex h-[300px] flex-col gap-2 overflow-y-auto px-4 py-4">
              {lines.length === 0 && phase === "live" && (
                <li className="m-auto text-sm text-zinc-500">The AI recruiter is about to speak…</li>
              )}
              {lines.map((line) => {
                const ai = line.speaker === "assistant";
                return (
                  <li key={line.seq} className={`cz-rise flex flex-col ${ai ? "items-start" : "items-end"}`}>
                    <span className="mb-0.5 px-1 text-[10px] text-zinc-500">{ai ? "CallZest AI" : name || "You"}</span>
                    <span
                      className={`max-w-[86%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                        ai ? "rounded-tl-md bg-white/[0.06] text-zinc-200" : "rounded-tr-md bg-[#1d4ed8]/25 text-blue-50"
                      }`}
                    >
                      {line.text}
                      {line.interrupted && <span className="ml-1 text-[11px] text-amber-300">(interrupted)</span>}
                    </span>
                  </li>
                );
              })}
            </ol>

            <div className="grid grid-cols-2 gap-px border-t border-white/[0.06] bg-white/[0.06] sm:grid-cols-4">
              {DEMO_KEYS.map((key) => {
                const field = byKey.get(key);
                const has = field && field.value !== null && field.value !== undefined && field.value !== "";
                return (
                  <div key={key} className="bg-[#101113] px-3 py-3">
                    <p className="text-[10px] tracking-wide text-zinc-500 uppercase">{fieldLabel(key)}</p>
                    <p className={`mt-0.5 truncate text-sm font-medium ${has ? "text-white" : "text-zinc-700"}`} title={field?.quote ?? undefined}>
                      {has ? fieldValue(key, field?.value) : "—"}
                    </p>
                  </div>
                );
              })}
            </div>

            {phase === "live" ? (
              <div className="flex items-center justify-between border-t border-white/[0.06] px-5 py-4">
                <div className="flex items-center gap-3 text-xs text-zinc-500">
                  <span className="flex h-5 items-end gap-0.5" aria-hidden="true">
                    {[0.5, 0.8, 1, 0.8, 0.5].map((k, i) => (
                      <span
                        key={i}
                        className={`w-1 rounded-full transition-[height] duration-100 ${speaking ? "bg-zinc-600" : "bg-emerald-400"}`}
                        style={{ height: `${Math.max(15, Math.min(100, level * 260 * k))}%` }}
                      />
                    ))}
                  </span>
                  {speaking ? "AI is speaking" : "Listening"} · ends by {clock(maxSeconds)}
                </div>
                <button
                  type="button"
                  onClick={hangUp}
                  className="rounded-full border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm font-medium text-red-300 transition hover:bg-red-500/20"
                >
                  End call
                </button>
              </div>
            ) : (
              <div className="border-t border-white/[0.06] px-6 py-5">
                <p className="font-display text-lg font-semibold">That&apos;s a CallZest screening call.</p>
                <p className="mt-1 text-sm text-zinc-400">
                  Your recruiters get these answers, the transcript and a summary for every
                  candidate, without making the first call themselves.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Link href="/signup" className="rounded-full bg-white px-5 py-2.5 text-sm font-medium text-black transition hover:bg-zinc-200">
                    Create your account
                  </Link>
                  <a
                    href="#walkthrough"
                    onClick={close}
                    className="rounded-full border border-white/15 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-white/5"
                  >
                    Watch the walkthrough
                  </a>
                </div>
              </div>
            )}
          </>
        )}

        {phase === "error" && (
          <div className="px-6 py-10 text-center">
            <p className="font-display text-lg font-semibold">The demo couldn&apos;t run</p>
            <p className="mx-auto mt-2 max-w-sm text-sm text-zinc-400">{error}</p>
            <button
              type="button"
              onClick={() => setPhase("intro")}
              className="mt-6 rounded-full border border-white/15 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-white/5"
            >
              Back
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

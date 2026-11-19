"use client";

import { useState } from "react";

import type { CallsOnDay } from "@/types";

// Validated on the dark card surface #18191c (dataviz validate_palette.js, all checks pass)
export const SERIES = { connected: "#3987e5", notConnected: "#d95926" };
// Status colours are reserved for call outcomes and always shown with a text label
export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
  live: "#3987e5",
  neutral: "#71717a",
};

const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

/** Rect with only the top corners rounded: data ends rounded, baseline square. */
function topRounded(x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${
    x + w
  },${y + rr}V${y + h}Z`;
}

function niceMax(value: number) {
  if (value <= 4) return 4;
  const step = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / step) * step;
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap gap-4 text-xs text-zinc-400">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  );
}

/** Calls per day, stacked: connected (bottom) + not connected. Hover a day for its numbers. */
export function CallsByDayChart({ days }: { days: CallsOnDay[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const W = 640;
  const H = 220;
  const pad = { top: 12, right: 8, bottom: 26, left: 28 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;
  const max = niceMax(Math.max(1, ...days.map((d) => d.total)));
  const slot = plotW / days.length;
  const barW = Math.min(22, slot * 0.6);
  const y = (v: number) => pad.top + plotH - (v / max) * plotH;
  const ticks = [0, max / 2, max];

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-3">
        <Legend
          items={[
            { label: "Connected", color: SERIES.connected },
            { label: "Not connected", color: SERIES.notConnected },
          ]}
        />
        <button
          type="button"
          onClick={() => setAsTable((v) => !v)}
          className="rounded-md px-2 py-1 text-xs text-zinc-400 hover:bg-white/5 hover:text-white"
        >
          {asTable ? "Chart" : "Table"}
        </button>
      </div>
      {asTable ? (
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-zinc-500">
            <tr>
              <th className="py-1 font-medium">Day</th>
              <th className="py-1 text-right font-medium">Calls</th>
              <th className="py-1 text-right font-medium">Connected</th>
            </tr>
          </thead>
          <tbody className="text-zinc-300">
            {days.map((d) => (
              <tr key={d.date} className="border-t border-white/5">
                <td className="py-1">{shortDate(d.date)}</td>
                <td className="py-1 text-right tabular-nums">{d.total}</td>
                <td className="py-1 text-right tabular-nums">{d.connected}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="relative">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="h-auto w-full"
            role="img"
            aria-label="Calls per day for the last 14 days, connected and not connected"
          >
            {ticks.map((t) => (
              <g key={t}>
                <line
                  x1={pad.left}
                  x2={W - pad.right}
                  y1={y(t)}
                  y2={y(t)}
                  stroke="rgba(255,255,255,0.06)"
                />
                <text
                  x={pad.left - 8}
                  y={y(t) + 4}
                  textAnchor="end"
                  className="fill-zinc-500 text-[11px]"
                >
                  {t}
                </text>
              </g>
            ))}
            {days.map((d, i) => {
              const cx = pad.left + slot * i + slot / 2;
              const x = cx - barW / 2;
              const missed = d.total - d.connected;
              const connectedTop = y(d.connected);
              const totalTop = y(d.total);
              const dim = hover !== null && hover !== i;
              return (
                <g key={d.date} opacity={dim ? 0.45 : 1}>
                  {d.connected > 0 && (
                    <path
                      d={
                        missed > 0
                          ? `M${x},${y(0)}V${connectedTop}H${x + barW}V${y(0)}Z`
                          : topRounded(x, connectedTop, barW, y(0) - connectedTop, 4)
                      }
                      fill={SERIES.connected}
                    />
                  )}
                  {missed > 0 && (
                    <path
                      // 2px surface gap between the stacked segments
                      d={topRounded(
                        x,
                        totalTop,
                        barW,
                        Math.max(0, connectedTop - totalTop - (d.connected > 0 ? 2 : 0)),
                        4,
                      )}
                      fill={SERIES.notConnected}
                    />
                  )}
                  {(i % 2 === days.length % 2 || days.length <= 7) && (
                    <text
                      x={cx}
                      y={H - 8}
                      textAnchor="middle"
                      className="fill-zinc-500 text-[11px]"
                    >
                      {shortDate(d.date)}
                    </text>
                  )}
                  {/* Hit target: the whole column, larger than the bar */}
                  <rect
                    x={pad.left + slot * i}
                    y={pad.top}
                    width={slot}
                    height={plotH}
                    fill="transparent"
                    onMouseEnter={() => setHover(i)}
                    onMouseLeave={() => setHover(null)}
                  />
                </g>
              );
            })}
          </svg>
          {hover !== null && (
            <div
              className={`pointer-events-none absolute top-0 z-10 rounded-lg border border-white/10 bg-[#24262b] px-3 py-2 text-xs whitespace-nowrap shadow-lg ${
                // Near the right edge, open to the left of the bar so it stays inside the card
                hover > days.length * 0.7 ? "-translate-x-[calc(100%+12px)]" : "translate-x-3"
              }`}
              style={{
                left: `${((pad.left + slot * hover + slot / 2) / W) * 100}%`,
              }}
            >
              <div className="mb-1 font-medium text-white">{shortDate(days[hover].date)}</div>
              <div className="text-zinc-300 tabular-nums">{days[hover].total} calls</div>
              <div className="flex items-center gap-1.5 text-zinc-300 tabular-nums">
                <span className="h-2 w-2 rounded-sm" style={{ background: SERIES.connected }} />
                {days[hover].connected} connected
              </div>
              <div className="flex items-center gap-1.5 text-zinc-300 tabular-nums">
                <span className="h-2 w-2 rounded-sm" style={{ background: SERIES.notConnected }} />
                {days[hover].total - days[hover].connected} not connected
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export type BarRow = { key: string; label: string; value: number; color: string; note?: string };

/** Labelled horizontal bars; the label and number carry the meaning, colour supports it. */
export function HorizontalBars({ rows, total }: { rows: BarRow[]; total?: number }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="space-y-3">
      {rows.map((row) => (
        <li key={row.key} title={`${row.label}: ${row.value}${row.note ? ` (${row.note})` : ""}`}>
          <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
            <span className="inline-flex items-center gap-2 text-zinc-300">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: row.color }} />
              {row.label}
            </span>
            <span className="text-white tabular-nums">
              {row.value}
              {total ? (
                <span className="ml-1.5 text-xs text-zinc-500">
                  {Math.round((row.value / total) * 100)}%
                </span>
              ) : null}
              {row.note && <span className="ml-1.5 text-xs text-zinc-500">{row.note}</span>}
            </span>
          </div>
          <div className="h-2 rounded-full bg-white/5">
            <div
              className="h-2 rounded-full transition-[width] duration-500"
              style={{ width: `${(row.value / max) * 100}%`, background: row.color }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

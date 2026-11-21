import type { ReactNode } from "react";

import { initials, prettyPhone } from "./form-kit";

/** What the card shows: a saved client or the form's draft. */
export type CardData = {
  name: string;
  industry: string;
  city: string;
  state: string;
  address?: string;
  email: string;
  website?: string;
  contact_name: string;
  contact_designation?: string;
  contact_phone: string;
};

/**
 * The client's "visiting card": the live preview beside the form, and the client's page.
 * Empty fields show placeholders (the form fills them in as you type).
 */
export function ClientProfileCard({
  data,
  badges,
  footer,
}: {
  data: CardData;
  badges?: ReactNode;
  footer?: ReactNode;
}) {
  const place = [data.city, data.state].filter(Boolean).join(", ");
  const blank = <span className="text-zinc-600">—</span>;
  return (
    <div className="relative flex flex-col overflow-hidden rounded-3xl bg-[#18191c] p-6 ring-1 ring-white/5">
      <div className="relative flex items-center gap-4">
        <span className="font-display flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-white/10 text-lg font-semibold text-white">
          {initials(data.name)}
        </span>
        <div className="min-w-0">
          <div className="font-display truncate text-lg font-semibold text-white">
            {data.name || <span className="text-zinc-600">Company name</span>}
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {data.industry ? (
              <span className="rounded-full bg-white/5 px-2.5 py-0.5 text-[11px] font-medium text-zinc-300">
                {data.industry}
              </span>
            ) : (
              <span className="rounded-full border border-dashed border-white/10 px-2.5 py-0.5 text-[11px] text-zinc-600">
                Industry
              </span>
            )}
            {badges}
          </div>
        </div>
      </div>

      <dl className="relative mt-5 space-y-2 text-sm">
        <Line icon="pin">{place || blank}</Line>
        {data.address && <Line icon="home">{data.address}</Line>}
        <Line icon="mail">{data.email || blank}</Line>
        {data.website && <Line icon="globe">{data.website.replace(/^https?:\/\//, "")}</Line>}
      </dl>

      <div className="relative mt-5 border-t border-dashed border-white/10 pt-4">
        <div className="text-[11px] tracking-wider text-zinc-500 uppercase">Contact</div>
        <div className="mt-1 font-medium text-white">
          {data.contact_name || <span className="text-zinc-600">Contact person</span>}
          {data.contact_designation && (
            <span className="font-normal text-zinc-400"> · {data.contact_designation}</span>
          )}
        </div>
        <div className="mt-0.5 font-mono text-sm text-zinc-300">
          {data.contact_phone ? prettyPhone(data.contact_phone) : blank}
        </div>
      </div>

      {footer && <div className="relative mt-auto pt-6">{footer}</div>}
    </div>
  );
}

const PATHS = {
  pin: (
    <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21Zm0-9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z" />
  ),
  home: <path d="M4 11 12 4l8 7v9H4v-9Zm6 9v-5h4v5" />,
  mail: <path d="M4 6h16v12H4zM4 7l8 6 8-6" />,
  globe: (
    <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-9-9h18M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-5.5-3.5-9s1-6.5 3.5-9Z" />
  ),
};

function Line({ icon, children }: { icon: keyof typeof PATHS; children: ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4 shrink-0 text-zinc-500"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.7}
        strokeLinejoin="round"
        aria-hidden="true"
      >
        {PATHS[icon]}
      </svg>
      <span className="min-w-0 truncate text-zinc-300">{children}</span>
    </div>
  );
}

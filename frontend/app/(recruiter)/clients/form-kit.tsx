"use client";

/**
 * The client form's state and its small building blocks, shared by every layout of the form
 * (the add/edit form and the client card).
 */

import { useState } from "react";

import { Button, inputClass } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { CITIES_BY_STATE, INDUSTRIES, type Industry, type IndianState, STATES } from "@/lib/india";
import type { Client, ClientCreate, ClientStatus } from "@/types";

export const CLIENT_STATUS: Record<ClientStatus, { label: string; tone: string }> = {
  active: { label: "Active", tone: "bg-green-500/10 text-green-300" },
  on_hold: { label: "On hold", tone: "bg-amber-500/10 text-amber-300" },
  closed: { label: "Closed", tone: "bg-white/5 text-zinc-400" },
};

export const OTHER_CITY = "__other__";

export type SaveClient = (body: ClientCreate) => Promise<void>;

// The dropdowns start empty; the forms make sure they're chosen before saving
export type Draft = Omit<ClientCreate, "industry" | "state"> & {
  industry: Industry | "";
  state: IndianState | "";
};

const EMPTY: Draft = {
  name: "",
  industry: "",
  website: "",
  email: "",
  address: "",
  city: "",
  state: "",
  contact_name: "",
  contact_designation: "",
  contact_phone: "",
  is_confidential: false,
  notes: "",
  status: "active",
};

function fromClient(c: Client): Draft {
  return {
    name: c.name,
    // Clients added before the dropdowns may hold other values: those must be chosen again
    industry: (INDUSTRIES as string[]).includes(c.industry) ? (c.industry as Industry) : "",
    website: c.website,
    email: c.email,
    address: c.address,
    city: c.city,
    state: (STATES as string[]).includes(c.state) ? (c.state as IndianState) : "",
    contact_name: c.contact_name,
    contact_designation: c.contact_designation,
    contact_phone: c.contact_phone,
    is_confidential: c.is_confidential,
    notes: c.notes,
    status: c.status,
  };
}

export const REQUIRED: { key: keyof Draft; label: string }[] = [
  { key: "name", label: "Company name" },
  { key: "industry", label: "Industry" },
  { key: "email", label: "Company email" },
  { key: "state", label: "State" },
  { key: "city", label: "City" },
  { key: "contact_name", label: "Contact person" },
  { key: "contact_phone", label: "Contact number" },
];

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Everything a client form needs: the draft, the city's "Other" mode, saving. */
export function useClientDraft(client?: Client) {
  const [draft, setDraft] = useState<Draft>(client ? fromClient(client) : EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cities = draft.state ? CITIES_BY_STATE[draft.state] : [];
  // A city that isn't in the state's list is typed in ("Other")
  const [otherCity, setOtherCity] = useState(draft.city !== "" && !cities.includes(draft.city));

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  return {
    draft,
    set,
    /** value + onChange for a text input bound to `key` */
    text: (key: keyof Draft) => ({
      value: String(draft[key] ?? ""),
      onChange: (e: { target: { value: string } }) => set(key, e.target.value as never),
    }),
    cities,
    otherCity,
    setState(state: IndianState) {
      setDraft((d) => ({ ...d, state, city: "" }));
      setOtherCity(false);
    },
    /** A city from the list, or OTHER_CITY to type one */
    chooseCity(value: string) {
      if (value === OTHER_CITY) {
        setOtherCity(true);
        set("city", "");
      } else {
        setOtherCity(false);
        set("city", value);
      }
    },
    busy,
    error,
    setError,
    /** Labels of the required fields among `keys` that are still empty or invalid */
    missing(keys: (keyof Draft)[] = REQUIRED.map((r) => r.key)) {
      const out: string[] = [];
      for (const { key, label } of REQUIRED) {
        if (!keys.includes(key)) continue;
        const value = String(draft[key] ?? "").trim();
        if (!value) out.push(label);
        else if (key === "email" && !EMAIL.test(value)) out.push("a valid company email");
      }
      return out;
    },
    async save(onSave: SaveClient) {
      setBusy(true);
      setError(null);
      try {
        await onSave(draft as ClientCreate);
        return true;
      } catch (err) {
        setError(errorMessage(err));
        return false;
      } finally {
        setBusy(false);
      }
    },
  };
}

export type ClientDraft = ReturnType<typeof useClientDraft>;

/** "Fill in Company name and City" */
export function missingMessage(labels: string[]) {
  if (labels.length === 0) return null;
  const list =
    labels.length === 1 ? labels[0] : `${labels.slice(0, -1).join(", ")} and ${labels.at(-1)}`;
  return `Fill in ${list}.`;
}

export function initials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  return (words.length > 1 ? words[0][0] + words[1][0] : name.trim().slice(0, 2)).toUpperCase();
}

/** Industry as pill buttons (a radio group). */
export function IndustryChips({
  value,
  onChange,
  size = "md",
}: {
  value: Industry | "";
  onChange: (value: Industry) => void;
  size?: "sm" | "md";
}) {
  return (
    <div role="radiogroup" aria-label="Industry" className="flex flex-wrap gap-2">
      {INDUSTRIES.map((industry) => {
        const on = value === industry;
        return (
          <button
            key={industry}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(industry)}
            className={`rounded-full border transition ${
              size === "sm" ? "px-3 py-1 text-xs" : "px-3.5 py-1.5 text-sm"
            } ${
              on
                ? "border-[#2563eb] bg-[#2563eb]/15 text-white"
                : "border-white/10 text-zinc-400 hover:border-white/25 hover:text-zinc-200"
            }`}
          >
            {industry}
          </button>
        );
      })}
    </div>
  );
}

export function StateSelect({ d, className = inputClass }: { d: ClientDraft; className?: string }) {
  return (
    <select
      required
      aria-label="State"
      value={d.draft.state}
      onChange={(e) => d.setState(e.target.value as IndianState)}
      className={className}
    >
      <option value="" disabled>
        Choose a state
      </option>
      {STATES.map((s) => (
        <option key={s} value={s}>
          {s}
        </option>
      ))}
    </select>
  );
}

/** The state's cities, with "Other" switching to a text box. */
export function CityInput({ d, className = inputClass }: { d: ClientDraft; className?: string }) {
  if (d.otherCity) {
    return (
      <div className="flex gap-2">
        <input
          required
          autoFocus
          aria-label="City"
          maxLength={100}
          placeholder="Type the city"
          className={className}
          {...d.text("city")}
        />
        <Button variant="secondary" onClick={() => d.chooseCity("")} title="Choose from the list">
          List
        </Button>
      </div>
    );
  }
  return (
    <select
      required
      aria-label="City"
      disabled={!d.draft.state}
      value={d.draft.city}
      onChange={(e) => d.chooseCity(e.target.value)}
      className={className}
    >
      <option value="" disabled>
        {d.draft.state ? "Choose a city" : "Choose the state first"}
      </option>
      {d.cities.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
      <option value={OTHER_CITY}>Other (type it)</option>
    </select>
  );
}

/** "+919876543210" → "+91 98765 43210" for display. */
export function prettyPhone(raw: string) {
  const digits = raw.replace(/\D/g, "");
  const local = digits.length === 12 && digits.startsWith("91") ? digits.slice(2) : digits;
  if (local.length === 10) return `+91 ${local.slice(0, 5)} ${local.slice(5)}`;
  return raw;
}

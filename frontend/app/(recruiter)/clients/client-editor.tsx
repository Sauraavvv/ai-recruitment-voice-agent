"use client";

import type { FormEvent } from "react";

import { Alert, Button } from "@/components/ui";

import type { Client, ClientStatus } from "@/types";

import { ClientProfileCard } from "./client-card";
import {
  CLIENT_STATUS,
  CityInput,
  IndustryChips,
  type SaveClient,
  StateSelect,
  useClientDraft,
} from "./form-kit";
import { Pills, Row, Section, line } from "./form-layout";

/** Add or edit a client: a calm form on the left, the client's card building itself live on
 * the right. `onSave` throws on failure; the error is shown above the form. */
export function ClientEditor({
  client,
  submitLabel,
  onSave,
}: {
  client?: Client;
  submitLabel: string;
  onSave: SaveClient;
}) {
  const d = useClientDraft(client);
  const { text } = d;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await d.save(onSave);
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="space-y-9 rounded-3xl bg-[#18191c] p-6 sm:p-8">
        {d.error && <Alert>{d.error}</Alert>}

        <Section n="01" title="The company">
          <Row label="Company name" required>
            <input
              required
              maxLength={200}
              placeholder="Easy Recruitz 365"
              className={line}
              {...text("name")}
            />
          </Row>
          <Row label="Industry" required as="div">
            <div className="py-1">
              <IndustryChips
                size="sm"
                value={d.draft.industry}
                onChange={(v) => d.set("industry", v)}
              />
            </div>
          </Row>
          <Row label="Company email" required>
            <input
              required
              type="email"
              maxLength={320}
              placeholder="hr@company.com"
              className={line}
              {...text("email")}
            />
          </Row>
          <Row label="Website">
            <input
              maxLength={300}
              placeholder="company.com"
              className={line}
              {...text("website")}
            />
          </Row>
        </Section>

        <Section n="02" title="Where it is">
          <Row label="State" required>
            <StateSelect d={d} className={line} />
          </Row>
          <Row label="City" required as="div">
            <CityInput d={d} className={line} />
          </Row>
          <Row label="Address">
            <input
              maxLength={500}
              placeholder="Office 4, Baner Road"
              className={line}
              {...text("address")}
            />
          </Row>
        </Section>

        <Section n="03" title="Who you talk to">
          <Row label="Contact person" required>
            <input
              required
              maxLength={200}
              placeholder="Neha Joshi"
              className={line}
              {...text("contact_name")}
            />
          </Row>
          <Row label="Designation">
            <input
              maxLength={200}
              placeholder="HR Manager"
              className={line}
              {...text("contact_designation")}
            />
          </Row>
          <Row label="Contact number" required>
            <input
              required
              type="tel"
              maxLength={32}
              placeholder="98765 43210"
              className={line}
              {...text("contact_phone")}
            />
          </Row>
        </Section>

        <Section n="04" title="On calls and in your list">
          <Row label="Status" as="div">
            <Pills
              label="Status"
              options={(Object.keys(CLIENT_STATUS) as ClientStatus[]).map((value) => ({
                value,
                label: CLIENT_STATUS[value].label,
              }))}
              value={d.draft.status ?? "active"}
              onChange={(value) => d.set("status", value)}
            />
          </Row>
          <Row label="Confidential">
            <span className="flex items-center gap-3 py-1 text-sm">
              <input
                type="checkbox"
                checked={d.draft.is_confidential ?? false}
                onChange={(e) => d.set("is_confidential", e.target.checked)}
                className="h-4 w-4 accent-[#2563eb]"
              />
              <span className="text-zinc-400">The agent never says this company&apos;s name.</span>
            </span>
          </Row>
          <Row label="Notes">
            <textarea
              rows={2}
              maxLength={5000}
              placeholder="Only your company's super admins see these"
              className={`${line} resize-y`}
              {...text("notes")}
            />
          </Row>
        </Section>

        {/* The industry chips aren't a native input: block saving until one is picked */}
        <div className="flex items-center justify-end gap-3">
          {!d.draft.industry && (
            <span className="text-xs text-zinc-500">Pick an industry to continue</span>
          )}
          <Button type="submit" disabled={d.busy || !d.draft.industry}>
            {d.busy ? "Saving…" : submitLabel}
          </Button>
        </div>
      </div>

      <div className="lg:sticky lg:top-6 lg:self-start">
        <ClientProfileCard data={d.draft} />
        <p className="mt-3 text-center text-xs text-zinc-500">
          Live preview · this is how the client shows up
        </p>
      </div>
    </form>
  );
}

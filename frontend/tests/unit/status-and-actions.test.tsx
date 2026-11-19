import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import {
  CALL_STATUS_FILTERS,
  Row,
  disabledReason,
} from "@/app/(recruiter)/candidates/candidate-list";
import { previewIntroduction } from "@/app/(recruiter)/settings/settings-view";
import { ScreeningAnswers, fieldStatus } from "@/components/screening-answers";
import { StatusBadge, badgeFor } from "@/components/status-badge";
import type { Candidate, CandidateListItem, SettingsPage } from "@/types";

afterEach(cleanup);

describe("StatusBadge", () => {
  it("maps every call status to a label and a tone", () => {
    expect(badgeFor("call", "in_progress")).toEqual({
      label: "On call",
      tone: expect.stringContaining("5fd35f"),
    });
    expect(badgeFor("call", "no_answer").label).toBe("No answer");
    expect(badgeFor("call", "failed").tone).toContain("red");
    expect(badgeFor("screening", "partially_completed").label).toBe("Partially completed");
    expect(badgeFor("field", "conflict").label).toBe("Conflict");
  });

  it("falls back to readable text for an unknown status", () => {
    expect(badgeFor("call", "brand_new_status")).toEqual({
      label: "Brand new status",
      tone: "bg-white/5 text-zinc-400",
    });
  });

  it("shows the status as text, not only colour, with a live dot while on a call", () => {
    const { container } = render(<StatusBadge kind="call" status="ringing" />);
    expect(screen.getByText("Ringing")).toBeTruthy();
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
    cleanup();
    const done = render(<StatusBadge kind="call" status="completed" />);
    expect(done.container.querySelector(".animate-pulse")).toBeNull();
  });
});

describe("filters", () => {
  it("offers 'not called yet' and every call status", () => {
    const values = CALL_STATUS_FILTERS.map(([v]) => v);
    expect(values[0]).toBe("not_called");
    expect(values).toEqual(
      expect.arrayContaining(["queued", "completed", "no_answer", "exhausted"]),
    );
  });
});

const row = (overrides: Partial<CandidateListItem> = {}): CandidateListItem =>
  ({
    id: "c1",
    name: "Asha Verma",
    phone: "+919000000001",
    email: null,
    job_id: "j1",
    applied_role: "Backend Developer",
    total_experience: 4,
    interested: null,
    screening_status: "not_started",
    opted_out: false,
    screening_field_meta: {},
    eligibility: { can_call: true, reason: null, message: null },
    last_call: null,
    last_call_has_transcript: false,
    open_conflicts: 0,
    ...overrides,
  }) as CandidateListItem;

function renderRow(r: CandidateListItem) {
  return render(
    <table>
      <tbody>
        <Row row={r} checked={false} onToggle={vi.fn()} onCall={vi.fn()} onRetry={vi.fn()} />
      </tbody>
    </table>,
  );
}

describe("disabled actions say why", () => {
  it("enables Call for an eligible candidate", () => {
    renderRow(row());
    const call = screen.getByRole("button", { name: "Call Asha Verma" }) as HTMLButtonElement;
    expect(call.disabled).toBe(false);
    expect(disabledReason(row())).toBe("");
  });

  it("disables Call with the API's reason", () => {
    const blocked = row({
      eligibility: {
        can_call: false,
        reason: "opted_out",
        message: "Candidate opted out of calls",
      },
    });
    renderRow(blocked);
    const call = screen.getByRole("button", {
      name: "Call Asha Verma (Candidate opted out of calls)",
    }) as HTMLButtonElement;
    expect(call.disabled).toBe(true);
    expect(call.title).toBe("Candidate opted out of calls");
    const box = screen.getByRole("checkbox", { name: "Select Asha Verma" }) as HTMLInputElement;
    expect(box.disabled).toBe(true);
  });

  it("offers Retry after a finished call, disabled with the reason when paused", () => {
    renderRow(
      row({
        last_call: {
          id: "a1",
          attempt_number: 1,
          call_status: "no_answer",
          end_reason: "no_answer",
          at: "2026-11-19T10:00:00Z",
          terminal: true,
        },
        eligibility: {
          can_call: false,
          reason: "calling_paused",
          message: "Calling is paused on the Settings page",
        },
      }),
    );
    const retry = screen.getByRole("button", { name: /Retry Asha Verma/ }) as HTMLButtonElement;
    expect(retry.disabled).toBe(true);
    expect(retry.title).toBe("Calling is paused on the Settings page");
    expect(screen.getByText("No answer")).toBeTruthy();
  });
});

describe("screening answers", () => {
  it("chooses the chip: conflict, stored status, missing", () => {
    expect(fieldStatus({ status: "confirmed", conflict: { final_value: 1 } }, 1)).toBe("conflict");
    expect(fieldStatus({ status: "declined" }, null)).toBe("declined");
    expect(fieldStatus(undefined, null)).toBe("missing");
  });

  it("shows chips and the candidate's words", () => {
    const candidate = {
      notice_period: "30 days",
      current_ctc: 12,
      expected_ctc: null,
      screening_field_meta: {
        notice_period: {
          status: "confirmed",
          raw_text: "thirty days",
          conflict: { final_value: "60 days" },
        },
        current_ctc: { status: "answered", raw_text: "twelve lakhs" },
        expected_ctc: { status: "declined" },
      },
    } as unknown as Candidate;
    render(<ScreeningAnswers candidate={candidate} />);
    expect(screen.getByText("12 LPA")).toBeTruthy();
    expect(screen.getByText("“twelve lakhs”")).toBeTruthy();
    expect(screen.getByText("Conflict")).toBeTruthy();
    expect(screen.getByText("Declined")).toBeTruthy();
    expect(screen.getByTitle("Candidate said: “thirty days”")).toBeTruthy();
  });
});

describe("introduction preview", () => {
  it("fills the placeholders like the agent does", () => {
    const settings = {
      introduction: {
        sample_first_name: "Asha",
        company: "Test Co",
        job_title: "AI Engineer",
      },
    } as SettingsPage;
    expect(
      previewIntroduction(
        "Hi {first_name}, I'm an AI from {organization} for {job_title} at {company}. Ok? {x}",
        settings,
        "",
      ),
    ).toBe("Hi Asha, I'm an AI from Test Co for AI Engineer at Test Co. Ok? {x}");
  });
});

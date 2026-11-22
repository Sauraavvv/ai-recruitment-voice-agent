import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import {
  RoundRowView,
  byScore,
  canStart,
} from "@/app/(recruiter)/clients/[id]/requirements/[rid]/telephonic-calls";
import { RoundAnswersView } from "@/components/round-answers";
import type { CallAnswers, EvaluationResult, RoundEvaluation, RoundRow } from "@/types";

afterEach(cleanup);

function row(overrides: Partial<RoundRow> = {}): RoundRow {
  return {
    candidate_id: "c1",
    name: "Ravi Kumar",
    phone: "+919876543210",
    status: "not_called",
    last_call: null,
    done_before: false,
    eligibility: { can_call: true, reason: null, message: null },
    ...overrides,
  };
}

const DONE_CALL: NonNullable<RoundRow["last_call"]> = {
  id: "a1",
  attempt_number: 4,
  call_status: "completed",
  end_reason: "agent_completed",
  at: new Date().toISOString(),
  terminal: true,
  next_retry_at: null,
  question_set_id: "s1",
  version: 1,
  finalized: true,
  has_transcript: true,
  answered: 2,
  questions: 3,
};

describe("RoundRowView", () => {
  it("offers the first call to someone not called yet", () => {
    const onCall = vi.fn();
    render(
      <ul>
        <RoundRowView row={row()} current={2} open={false} onToggle={() => {}} onCall={onCall} />
      </ul>,
    );
    expect(screen.getByText("Not called")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Call Ravi Kumar" }));
    expect(onCall).toHaveBeenCalledOnce();
  });

  it("shows a finished round: answers, the version asked (older), and call again", () => {
    const onToggle = vi.fn();
    const done = row({
      status: "done",
      done_before: true,
      last_call: DONE_CALL,
      eligibility: {
        can_call: false,
        reason: "telephonic_done",
        message: "This candidate has already done the telephonic round",
      },
    });
    render(
      <ul>
        <RoundRowView row={done} current={2} open={false} onToggle={onToggle} onCall={() => {}} />
      </ul>,
    );
    expect(screen.getByText("Done")).toBeTruthy();
    expect(screen.getByText("2/3 answered")).toBeTruthy();
    expect(screen.getByText(/v1/).textContent).toContain("older");
    // "Call again" stays enabled: the dialog asks for the confirmation
    const again = screen.getByRole("button", { name: "Call again Ravi Kumar" });
    expect((again as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Answers" }));
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("disables the call with the reason when the rules say no", () => {
    const blocked = row({
      eligibility: {
        can_call: false,
        reason: "screening_not_completed",
        message: "The screening call didn't finish",
      },
    });
    expect(canStart(blocked)).toBe(false);
    render(
      <ul>
        <RoundRowView
          row={blocked}
          current={1}
          open={false}
          onToggle={() => {}}
          onCall={() => {}}
        />
      </ul>,
    );
    const button = screen.getByRole("button", { name: /Call Ravi Kumar/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(button.title).toBe("The screening call didn't finish");
  });
});

describe("RoundAnswersView", () => {
  const data: CallAnswers = {
    call_attempt_id: "a1",
    candidate_id: "c1",
    question_set_id: "s1",
    version: 2,
    answers: [
      {
        question_id: "q1",
        question: "Tell me about a RAG pipeline you built.",
        status: "partial",
        answer: "I built one. With Pinecone.",
        follow_up_asked: true,
        follow_up: "Which parts did you build?",
        checked: true,
        from_earlier_call: false,
      },
      {
        question_id: "q2",
        question: "How do you debug drift?",
        status: "dont_know",
        answer: "I don't know.",
        follow_up_asked: false,
        follow_up: null,
        checked: false,
        from_earlier_call: false,
      },
      {
        question_id: "q3",
        question: "Last question?",
        status: "not_asked",
        answer: "",
        follow_up_asked: false,
        follow_up: null,
        checked: true,
        from_earlier_call: false,
      },
    ],
    candidate_questions: ["salary"],
    summary: "Telephonic round (questions v2). 0 of 3 questions answered.",
    finalized: true,
    call_status: "completed",
    end_reason: "max_duration",
    start_time: null,
    duration_seconds: 300,
  };

  it("shows the candidate's own words with plain statuses", () => {
    render(<RoundAnswersView data={data} transcriptHref="/candidates/c1?call=a1" />);
    expect(screen.getByText("Partly")).toBeTruthy();
    expect(screen.getByText("Didn't know")).toBeTruthy();
    expect(screen.getByText("Not asked")).toBeTruthy();
    expect(screen.getByText("“I built one. With Pinecone.”")).toBeTruthy();
    expect(screen.getByText("Follow-up asked: Which parts did you build?")).toBeTruthy();
    expect(screen.getByText(/Kept as said/)).toBeTruthy();
    expect(screen.getByText("—")).toBeTruthy(); // nothing invented for a question not asked
    expect(screen.getByText(/They asked about: salary/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Transcript" }).getAttribute("href")).toBe(
      "/candidates/c1?call=a1",
    );
  });
});

describe("AI evaluation", () => {
  const badge = (score: number, verdict: "strong_fit" | "possible_fit" | "not_a_fit") => ({
    call_attempt_id: "a1",
    state: "done" as const,
    score,
    verdict,
    incomplete: false,
  });

  it("shows the verdict and score on a row, marked as the AI's", () => {
    render(
      <ul>
        <RoundRowView
          row={row({
            status: "incomplete",
            last_call: DONE_CALL,
            evaluation: { ...badge(58, "possible_fit"), incomplete: true },
          })}
          current={1}
          open={false}
          onToggle={() => {}}
          onCall={() => {}}
        />
      </ul>,
    );
    const shown = screen.getByText(/Possible fit · 58/);
    expect(shown.textContent).toContain("incomplete");
    expect(shown.getAttribute("title")).toMatch(/AI recommendation — the recruiter decides/);
  });

  it("sorts by score, unscored rows last in their order", () => {
    const rows = [
      row({ candidate_id: "none1" }),
      row({ candidate_id: "low", evaluation: badge(30, "not_a_fit") }),
      row({ candidate_id: "none2" }),
      row({ candidate_id: "high", evaluation: badge(82, "strong_fit") }),
    ];
    expect(byScore(rows).map((r) => r.candidate_id)).toEqual(["high", "low", "none1", "none2"]);
  });

  const result: EvaluationResult = {
    score: 47,
    verdict: "possible_fit",
    incomplete: true,
    strengths: "Knows RAG basics.",
    gaps: "No depth on drift.",
    not_covered: ["Last question?"],
    questions: [
      {
        question_id: "q1",
        question: "Tell me about a RAG pipeline you built.",
        weight: 3,
        status: "partial",
        score: 3,
        quote: "with Pinecone",
        reason: "Names a vector store, little else.",
        rule: "model",
        checked: true,
        from_earlier_call: false,
      },
      {
        question_id: "q2",
        question: "How do you debug drift?",
        weight: 2,
        status: "dont_know",
        score: 0,
        quote: "",
        reason: "Said they don't know.",
        rule: "dont_know",
        checked: false,
        from_earlier_call: false,
      },
      {
        question_id: "q3",
        question: "Last question?",
        weight: 1,
        status: "not_asked",
        score: null,
        quote: "",
        reason: "Not asked on the call.",
        rule: "not_asked",
        checked: true,
        from_earlier_call: false,
      },
    ],
    model: "m",
    rubric_version: 2,
    rubric_hash: "h",
    evaluated_at: new Date().toISOString(),
  };

  function answers(evaluation: RoundEvaluation): CallAnswers {
    return {
      call_attempt_id: "a1",
      candidate_id: "c1",
      question_set_id: "s1",
      version: 2,
      answers: result.questions.map((q) => ({
        question_id: q.question_id,
        question: q.question,
        status: q.status,
        answer: q.status === "not_asked" ? "" : "I built one. With Pinecone.",
        follow_up_asked: false,
        follow_up: null,
        checked: q.checked,
        from_earlier_call: false,
      })),
      candidate_questions: [],
      summary: null,
      finalized: true,
      call_status: "completed",
      end_reason: "max_duration",
      start_time: null,
      duration_seconds: 300,
      evaluation,
    };
  }

  it("shows the overall verdict and each answer's score, reason and quote", () => {
    const onReevaluate = vi.fn();
    render(
      <RoundAnswersView
        data={answers({ state: "done", result, error: null, requested_at: null })}
        onReevaluate={onReevaluate}
      />,
    );
    expect(screen.getByText("Possible fit · 47/100")).toBeTruthy();
    expect(screen.getByText("Incomplete")).toBeTruthy();
    expect(screen.getByText("AI recommendation — the recruiter decides")).toBeTruthy();
    expect(screen.getByText("Knows RAG basics.")).toBeTruthy();
    expect(screen.getByText(/Not asked, so not scored: Last question\?/)).toBeTruthy();
    expect(screen.getByText("3/5")).toBeTruthy();
    expect(screen.getByText(/Names a vector store/)).toBeTruthy();
    expect(screen.getByText(/“with Pinecone”/)).toBeTruthy();
    expect(screen.getByText("0/5")).toBeTruthy();
    expect(screen.queryByText("Not asked on the call.")).toBeNull(); // no score for it
    fireEvent.click(screen.getByRole("button", { name: "Re-evaluate" }));
    expect(onReevaluate).toHaveBeenCalledOnce();
  });

  it("keeps the old result while evaluating again, and says when it failed", () => {
    const { rerender } = render(
      <RoundAnswersView
        data={answers({ state: "pending", result, error: null, requested_at: null })}
        onReevaluate={() => {}}
      />,
    );
    expect(screen.getByText("Possible fit · 47/100")).toBeTruthy();
    expect(screen.getByText("Evaluating again…")).toBeTruthy();
    const button = screen.getByRole("button", { name: "Evaluating…" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    rerender(
      <RoundAnswersView
        data={answers({
          state: "failed",
          result: null,
          error: "ai_unavailable",
          requested_at: null,
        })}
        onReevaluate={() => {}}
      />,
    );
    expect(screen.getByText("The AI evaluation didn't finish.")).toBeTruthy();
    expect(screen.getByText(/the AI service was busy/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Evaluate" })).toBeTruthy();
  });
});

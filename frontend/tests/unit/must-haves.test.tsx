import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CallQuestionsView } from "@/app/(recruiter)/clients/[id]/requirements/[rid]/call-questions";
import { questionCount, repeatsDefault } from "@/lib/must-haves";
import type { ScreeningCallQuestion } from "@/types";

afterEach(cleanup);

const DEFAULTS = [
  { key: "interested", prompt: "Are you interested in this opportunity?" },
  { key: "current_location", prompt: "Where are you currently located?" },
  { key: "total_experience", prompt: "How many years of total work experience do you have?" },
  { key: "notice_period", prompt: "What is your notice period?" },
  { key: "current_ctc", prompt: "What is your current CTC?" },
];

describe("repeatsDefault", () => {
  it("flags a must-have that only repeats a default question", () => {
    expect(repeatsDefault("atleas 2 year of experience", DEFAULTS)?.number).toBe(3);
    expect(repeatsDefault("Minimum 3+ yrs experience", DEFAULTS)?.key).toBe("total_experience");
    expect(repeatsDefault("Notice period under 30 days", DEFAULTS)?.key).toBe("notice_period");
    expect(repeatsDefault("Immediate joiner", DEFAULTS)?.key).toBe("notice_period");
    expect(repeatsDefault("Salary up to 8 LPA", DEFAULTS)?.key).toBe("current_ctc");
  });

  it("leaves more specific must-haves alone", () => {
    expect(repeatsDefault("atleast 2 year of experience in python", DEFAULTS)).toBeNull();
    expect(repeatsDefault("have worked on AI pipelines", DEFAULTS)).toBeNull();
    expect(repeatsDefault("Own two-wheeler", DEFAULTS)).toBeNull();
    expect(repeatsDefault("Ready to relocate to Pune", DEFAULTS)).toBeNull();
  });

  it("needs the default question to exist", () => {
    expect(repeatsDefault("2 years of experience", DEFAULTS.slice(0, 2))).toBeNull();
  });

  it("counts the questions", () => {
    expect(questionCount(10, 3)).toBe("10 default + 3 must-haves = 13 questions");
    expect(questionCount(10, 1)).toBe("10 default + 1 must-have = 11 questions");
  });
});

function q(number: number, key: string, prompt: string, mustHave?: string): ScreeningCallQuestion {
  return {
    number,
    key,
    prompt,
    type: mustHave ? "boolean" : "string",
    source: mustHave ? "must_have" : "default",
    must_have: mustHave ?? null,
  };
}

describe("CallQuestionsView", () => {
  const questions = [
    ...DEFAULTS.map((d, i) => q(i + 1, d.key, d.prompt)),
    q(
      6,
      "must_have_1",
      "One requirement for this role: 2 years of experience. Does that apply to you?",
      "2 years of experience",
    ),
    q(7, "must_have_2", "One requirement…", "Worked on AI pipelines"),
  ];

  it("shows the count, and the list in call order with sources and repeats", () => {
    let open = false;
    const { rerender } = render(
      <CallQuestionsView
        questions={questions}
        open={open}
        onToggle={() => (open = !open)}
        editHref="/edit"
      />,
    );
    expect(screen.getByText("7 questions")).toBeTruthy();
    expect(screen.getByText("5 default + 2 must-haves = 7 questions")).toBeTruthy();
    expect(screen.getByText("1 repeats a default question")).toBeTruthy();
    expect(screen.queryByText("Worked on AI pipelines")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /See questions/ }));
    rerender(
      <CallQuestionsView questions={questions} open={open} onToggle={() => {}} editHref="/edit" />,
    );
    expect(screen.getByText("Worked on AI pipelines")).toBeTruthy();
    expect(screen.getAllByText("must-have")).toHaveLength(2);
    expect(
      screen.getByText(
        "Looks like question 3 (How many years of total work experience do you have)",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Edit must-haves" }).getAttribute("href")).toBe(
      "/edit",
    );
  });
});

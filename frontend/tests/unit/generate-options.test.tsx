import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import {
  GenerateOptions,
  MAX_COUNT,
  MIN_COUNT,
} from "@/app/(recruiter)/clients/[id]/requirements/[rid]/telephonic-card";

afterEach(cleanup);

describe("GenerateOptions", () => {
  it("picks the number of questions on a slider, one at a time", () => {
    const onCount = vi.fn();
    render(
      <GenerateOptions
        count={8}
        level="easy"
        focus=""
        onCount={onCount}
        onLevel={() => {}}
        onFocus={() => {}}
      />,
    );
    const slider = screen.getByRole("slider", { name: "How many questions" }) as HTMLInputElement;
    expect([slider.min, slider.max, slider.step, slider.value]).toEqual([
      String(MIN_COUNT),
      String(MAX_COUNT),
      "1",
      "8",
    ]);
    fireEvent.change(slider, { target: { value: "5" } });
    expect(onCount).toHaveBeenCalledWith(5);
  });

  it("picks how hard the questions are, easy being an HR screening call", () => {
    const onLevel = vi.fn();
    render(
      <GenerateOptions
        count={8}
        level="easy"
        focus=""
        onCount={() => {}}
        onLevel={onLevel}
        onFocus={() => {}}
      />,
    );
    expect(screen.getByRole("radio", { name: "Easy" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText(/Like an HR screening call/)).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Hard" }));
    expect(onLevel).toHaveBeenCalledWith("hard");
  });
});

import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

// login → upload → candidates → detail → settings (phase-08 §7), on the isolated E2E stack.
// Data is created through the API and the UI; screenshots go to test-results/screens/.
const EMAIL = "e2e@example.com";
const PASSWORD = "e2e-only-password-123";
const BACKEND = path.resolve(__dirname, "../../../backend");

/** A finished screening call with a conflict (tests/e2e/seed.py), into the E2E database. */
function seedFinishedCall() {
  execFileSync(".venv/bin/python", [path.resolve(__dirname, "seed.py")], {
    cwd: BACKEND,
    env: {
      ...process.env,
      PYTHONPATH: BACKEND,
      APP_ENV: "test",
      APP_SECRET_KEY: "e2e-only-secret-key-0123456789abcdefgh",
      DATABASE_URL: "postgresql+asyncpg://postgres:postgres@localhost:5433/recruitment_ai_e2e",
      REDIS_URL: "redis://localhost:6380/1",
    },
  });
}

const shot = (page: Page, name: string) =>
  page.screenshot({ path: `test-results/screens/${name}.png`, fullPage: true });

test("recruiter flow", async ({ page }) => {
  // Empty database: the dashboard shows zeros, never placeholder numbers (P8-AC5)
  page.on("pageerror", (err) => console.log("pageerror:", err.message));
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/dashboard");
  await expect(page.getByText("Nothing needs attention")).toBeVisible();
  const tiles = page.getByRole("region", { name: "Statistics" });
  await expect(tiles.getByText("Candidates", { exact: true })).toBeVisible();
  for (const value of await tiles.getByTestId("stat-value").allTextContents()) {
    expect(value.trim()).toBe("0");
  }
  await shot(page, "01-dashboard-empty");

  // A client and a job (requirement) through the API: candidates are uploaded to a job
  const origin = { Origin: "http://localhost:3011" };
  const client = await page.request.post("/api/v1/clients", {
    headers: origin,
    data: {
      name: "E2E Co",
      industry: "BPO / KPO",
      email: "hr@e2e.example",
      city: "Pune",
      state: "Maharashtra",
      contact_name: "Neha Joshi",
      contact_phone: "98765 43210",
    },
  });
  expect(client.status()).toBe(201);
  const clientId = (await client.json()).data.id;
  const job = await page.request.post(`/api/v1/clients/${clientId}/requirements`, {
    headers: origin,
    data: { title: "Backend Developer", job_description: "Build APIs.", skills: ["Python"] },
  });
  expect(job.status()).toBe(201);
  const jobId = (await job.json()).data.id;

  // Upload two candidates on the job's page, in the floating upload window
  await page.goto(`/clients/${clientId}/requirements/${jobId}`);
  await page.getByRole("button", { name: "Upload a list" }).click();
  const upload = page.getByRole("dialog", { name: "Upload a list" });
  await expect(upload.getByText("For Backend Developer · E2E Co")).toBeVisible();
  await shot(page, "01b-upload-dialog");
  await upload.getByLabel("List file").setInputFiles({
    name: "candidates.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      "Candidate name,Phone number,Total experience\n" +
        "Asha Verma,+91 98765 00001,4\n" +
        "Ravi Kumar,+91 98765 00002,6\n",
    ),
  });
  await upload.getByLabel(/agreed to be contacted/).check();
  await shot(page, "01c-upload-preview");
  await upload.getByRole("button", { name: "Import 2 valid candidates" }).click();
  await expect(upload.getByText(/Imported 2 candidates\./)).toBeVisible();
  await upload.getByRole("button", { name: "Done" }).click();
  await expect(upload).toBeHidden();
  // The job's list behind it refreshed
  await expect(page.getByRole("link", { name: "Asha Verma" })).toBeVisible();

  // The same number again: nothing new to import, and "view" opens in a new tab while the
  // upload window stays open as a modal (blurred page behind it)
  await page.getByRole("button", { name: "Upload list" }).click();
  await upload.getByLabel("List file").setInputFiles({
    name: "again.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("Candidate name,Phone number\nAsha Verma,+91 98765 00001\n"),
  });
  await expect(upload.getByText(/Nothing new to import/)).toBeVisible();
  await expect(upload.getByRole("button", { name: /^Import/ })).toHaveCount(0);
  const [tab] = await Promise.all([
    page.context().waitForEvent("page"),
    upload.getByRole("link", { name: "view" }).click(),
  ]);
  await tab.close();
  expect(await upload.evaluate((d) => d.matches(":modal"))).toBe(true);
  await shot(page, "01d-upload-nothing-new");
  await upload.getByRole("button", { name: "Close", exact: true }).click();
  await expect(upload).toBeHidden();

  // Candidates: rows with call status and the disabled Call button's reason
  await page.goto("/candidates");
  await expect(page.getByRole("link", { name: "Asha Verma" })).toBeVisible();
  await expect(page.getByText("Not called", { exact: true }).first()).toBeVisible();
  const call = page.getByRole("button", { name: /^Call Asha Verma/ });
  await expect(call).toBeDisabled(); // telephony isn't configured on the E2E stack
  await expect(call).toHaveAttribute("title", "Telephony is not configured");
  await page.getByLabel("Client").selectOption({ label: "E2E Co" });
  await expect(page.getByRole("link", { name: "Asha Verma" })).toBeVisible();
  await page.getByLabel("Call status").selectOption("not_called");
  await expect(page.getByText("Page 1 of 1 · 2 candidates")).toBeVisible();
  await shot(page, "02-candidates");

  // Detail
  await page.getByRole("link", { name: "Asha Verma" }).click();
  await expect(page.getByRole("heading", { name: "Asha Verma" })).toBeVisible();
  await expect(page.getByText("Screening answers")).toBeVisible();
  await expect(page.getByText("A summary appears here after the first call.")).toBeVisible();
  await expect(page.getByText("Can't call now: Telephony is not configured")).toBeVisible();
  await shot(page, "03-candidate");

  // Calls page (empty)
  await page.goto("/calls");
  await expect(page.getByText("No calls yet")).toBeVisible();
  await shot(page, "04-calls");

  // Settings: pause, introduction preview, providers without keys
  await page.goto("/settings");
  await expect(page.getByText("Calling is on")).toBeVisible();
  await page.getByRole("switch", { name: "Calling enabled" }).click();
  await page.getByRole("button", { name: "Pause calling" }).click();
  await expect(page.getByText("Calling is paused")).toBeVisible();
  await page
    .getByLabel("Agent introduction")
    .fill("Hi {first_name}, I'm an AI assistant for {company}. Is now a good time?");
  await expect(
    // {company} comes from the old job config, which requirement uploads don't use
    page.getByText("“Hi Asha, I'm an AI assistant for your company. Is now a good time?”"),
  ).toBeVisible();
  await shot(page, "05-settings");

  // The pause shows on the candidate list too (P8-AC7 in the UI)
  await page.getByRole("button", { name: "Save" }).nth(1).click();
  await page.goto("/candidates");
  await expect(page.getByRole("button", { name: /^Call Asha Verma/ })).toHaveAttribute(
    "title",
    "Calling is paused on the Settings page",
  );

  // Dashboard with data
  await page.goto("/dashboard");
  await expect(tiles.getByTestId("stat-value").first()).toHaveText("2");

  // A finished call: needs attention (conflict), summary, answers, transcript (P8-AC3)
  seedFinishedCall();
  await page.reload();
  await expect(tiles.getByTestId("stat-value").first()).toHaveText("3");
  await expect(page.getByText("Priya Sharma · Notice period: two different answers")).toBeVisible();
  await expect(page.getByText("Screening incomplete")).toBeVisible();
  await shot(page, "06-dashboard");

  await page.goto("/candidates");
  await page.getByRole("link", { name: "Priya Sharma" }).click();
  await expect(page.getByText("Answers that disagree")).toBeVisible();
  await expect(
    page.getByText(/^Priya Sharma is interested in the Data Engineer role/),
  ).toBeVisible();
  await expect(page.getByText("From call #2", { exact: false })).toBeVisible();
  await expect(page.getByText("“Twelve lakhs per annum.”")).toBeVisible();
  await expect(page.getByText("Actually it could be sixty days, I need to check.")).toBeVisible();
  await expect(page.getByText(/Interrupted — heard/)).toBeVisible();
  await shot(page, "07-candidate-with-call");
  await page.getByRole("button", { name: "Use 60 days" }).click();
  await expect(page.getByText("Answers that disagree")).toBeHidden();
  await expect(page.getByText("60 days", { exact: true })).toBeVisible();

  // Older call in the transcript selector: not answered, no conversation
  await page.getByLabel("Choose call").selectOption({ index: 1 });
  await expect(page.getByText(/No conversation on this call/)).toBeVisible();

  // Calls page lists both attempts with the transcript link
  await page.goto("/calls");
  await expect(page.getByText("Page 1 of 1 · 2 calls")).toBeVisible();
  await expect(page.getByRole("link", { name: "Transcript" })).toHaveCount(1);
  await shot(page, "08-calls");
});

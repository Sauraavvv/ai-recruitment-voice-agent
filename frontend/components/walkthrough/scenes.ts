/**
 * The walkthrough script: one scene per feature, following the real app's screens and labels.
 * Times are milliseconds from the start of the scene. `steps` are the how-to lines shown under
 * the stage; each lights up at its time. `cursor` moves the pointer to an element marked
 * `data-target` and, with `click`, presses it.
 */

export type SceneId = "job" | "upload" | "calls" | "live" | "review" | "round";
export type NavId = "dashboard" | "clients" | "jobs" | "candidates" | "calls" | "telephonic" | "questions" | "accounts";

export type Scene = {
  id: SceneId;
  label: string;
  title: string;
  summary: string;
  path: string;
  nav: NavId;
  duration: number;
  steps: { at: number; text: string }[];
  cursor: { at: number; target: string; click?: number }[];
};

export const SCENES: Scene[] = [
  {
    id: "job",
    label: "Add a job",
    title: "Add the job you are hiring for",
    summary: "Pick the client, describe the role and who fits. The preview updates as you type.",
    path: "/jobs/new",
    nav: "jobs",
    duration: 7600,
    steps: [
      { at: 0, text: "In Total jobs, open Add job and pick the client" },
      { at: 1300, text: "Type the role and choose the work mode" },
      { at: 3700, text: "Add experience and the CTC budget" },
      { at: 5300, text: "Save: the call gets your 10 default questions" },
    ],
    cursor: [
      { at: 200, target: "client", click: 800 },
      { at: 1300, target: "title" },
      { at: 2700, target: "mode-hybrid", click: 3250 },
      { at: 3700, target: "exp" },
      { at: 5300, target: "save", click: 5900 },
    ],
  },
  {
    id: "upload",
    label: "Upload a list",
    title: "Upload your candidate list",
    summary: "Drop an Excel or CSV file. Every row is checked before anything is saved.",
    path: "/jobs/backend-developer",
    nav: "jobs",
    duration: 8400,
    steps: [
      { at: 0, text: "On the job page, click Upload list" },
      { at: 1300, text: "Drop your .xlsx or .csv file" },
      { at: 2500, text: "Check the preview: duplicates and bad rows are skipped" },
      { at: 4800, text: "Confirm consent and import the valid rows" },
    ],
    cursor: [
      { at: 200, target: "upload", click: 850 },
      { at: 1300, target: "drop", click: 1950 },
      { at: 4800, target: "consent", click: 5350 },
      { at: 5700, target: "import", click: 6300 },
    ],
  },
  {
    id: "calls",
    label: "Start calls",
    title: "Call everyone with one click",
    summary: "The AI calls each candidate inside your calling hours. The rest wait in line.",
    path: "/jobs/backend-developer",
    nav: "jobs",
    duration: 8000,
    steps: [
      { at: 0, text: "Click Call not-called on the job page" },
      { at: 1300, text: "See your calling hours and who will be called" },
      { at: 3100, text: "Confirm, and the calls are queued" },
      { at: 4300, text: "The Call column follows each call as it happens" },
    ],
    cursor: [
      { at: 200, target: "call-all", click: 850 },
      { at: 2600, target: "confirm", click: 3200 },
      { at: 4400, target: "status-0" },
    ],
  },
  {
    id: "live",
    label: "Watch live",
    title: "Watch a call while it happens",
    summary: "The transcript and the answers fill in line by line, live.",
    path: "/candidates/priya-nair",
    nav: "candidates",
    duration: 8200,
    steps: [
      { at: 0, text: "Open the candidate while the call is on" },
      { at: 1300, text: "Read the transcript as the conversation happens" },
      { at: 4100, text: "Screening answers fill in as they are given" },
      { at: 6500, text: "End the call any time: answers so far are kept" },
    ],
    cursor: [
      { at: 1300, target: "transcript" },
      { at: 4100, target: "answers" },
      { at: 6500, target: "end-call" },
    ],
  },
  {
    id: "review",
    label: "Review answers",
    title: "Read structured answers",
    summary: "A summary, every answer with the candidate's own words, and conflicts to settle.",
    path: "/candidates/priya-nair",
    nav: "candidates",
    duration: 8200,
    steps: [
      { at: 0, text: "Open the candidate once the call ends" },
      { at: 900, text: "Read the summary and every answer" },
      { at: 2600, text: "Hover an answer to see the candidate's own words" },
      { at: 4300, text: "Two different answers? Keep one or use the other" },
    ],
    cursor: [
      { at: 900, target: "summary" },
      { at: 2600, target: "answer-ctc" },
      { at: 4300, target: "keep", click: 5000 },
    ],
  },
  {
    id: "round",
    label: "Telephonic round",
    title: "A scored second round",
    summary: "Questions written from the job description, asked on a second call and scored.",
    path: "/jobs/backend-developer",
    nav: "jobs",
    duration: 9200,
    steps: [
      { at: 0, text: "Choose how many questions and the level" },
      { at: 1400, text: "Generate them from the JD with AI" },
      { at: 3700, text: "Check or edit them, then approve" },
      { at: 5100, text: "Interested candidates are called, and each answer is scored" },
    ],
    cursor: [
      { at: 300, target: "level-medium", click: 850 },
      { at: 1400, target: "generate", click: 1950 },
      { at: 3700, target: "approve", click: 4300 },
      { at: 5400, target: "verdict" },
    ],
  },
];

/** Length of the whole tour, for the section label. */
export const TOTAL_SECONDS = Math.round(SCENES.reduce((sum, s) => sum + s.duration, 0) / 1000);

/** 0 before `start`, 1 after `end`, linear in between. */
export function progress(e: number, start: number, end: number): number {
  if (e <= start) return 0;
  if (e >= end) return 1;
  return (e - start) / (end - start);
}

/** The first characters of `text`, typed at `msPerChar` from `start`. */
export function typed(text: string, e: number, start: number, msPerChar = 45): string {
  return text.slice(0, Math.max(0, Math.floor((e - start) / msPerChar)));
}

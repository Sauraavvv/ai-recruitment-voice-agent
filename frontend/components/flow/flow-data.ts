/**
 * How CallZest works, as a node graph for customers (plain words, no internals).
 * Coordinates are canvas pixels; every node is NODE_W × NODE_H.
 */

export const NODE_W = 210;
export const NODE_H = 76;
export const CANVAS_W = 1890;
export const CANVAS_H = 1140;

export type NodeKind = "you" | "auto" | "decision" | "outcome" | "end";
export type Port = "left" | "right" | "top" | "bottom";

export type FlowNode = {
  id: string;
  x: number;
  y: number;
  kind: NodeKind;
  title: string;
  sub: string;
  detail: string;
};

export type FlowEdge = {
  from: string;
  to: string;
  fromPort?: Port;
  toPort?: Port;
  label?: string;
  dashed?: boolean;
  /** Lane change: route around the rows instead of cutting across them. */
  wrapY?: number;
};

export type FlowGroup = { label: string; x: number; y: number; w: number; h: number };

const L1 = 120;
const L2 = 540;
const L3 = 1000;
const B1 = 280;
const B2 = 700;
const col = (i: number) => 60 + i * 260;

export const NODES: FlowNode[] = [
  // Set up
  { id: "job", x: col(0), y: L1, kind: "you", title: "Add a job", sub: "Role, budget, notice period", detail: "You add the role you are hiring for: the client, location, experience, CTC budget and notice period. The screening call gets your 10 default questions, plus any must-haves you add." },
  { id: "upload", x: col(1), y: L1, kind: "you", title: "Upload your list", sub: "Excel or CSV file", detail: "Drop a spreadsheet of candidates on the job. You see a preview of every row before anything is saved, and you confirm the candidates agreed to be contacted." },
  { id: "rows", x: col(2), y: L1, kind: "decision", title: "Is every row okay?", sub: "Checked before saving", detail: "Each row is checked: a name and a valid phone number are needed, Indian numbers get +91, and duplicates (in the file or already saved) are caught." },
  { id: "skipped", x: col(2), y: B1, kind: "outcome", title: "Row skipped", sub: "Duplicate or bad number", detail: "Rows with a missing name, a wrong phone number or a duplicate are left out, with the reason shown, so nobody is called twice." },

  // Calling
  { id: "start", x: col(3), y: L1, kind: "you", title: "Start the calls", sub: "One click on the job", detail: "Click Call not-called on the job page. You see your calling hours and exactly who will be called, then confirm." },
  { id: "hours", x: col(4), y: L1, kind: "decision", title: "Inside calling hours?", sub: "Your days and times", detail: "CallZest only calls inside the calling days and hours you set. One switch pauses all calling." },
  { id: "wait", x: col(4), y: B1, kind: "outcome", title: "Waits in line", sub: "Until your hours open", detail: "Calls outside your hours wait, and go out when the window opens. If several calls are due, the rest wait their turn." },
  { id: "dial", x: col(5), y: L1, kind: "auto", title: "AI calls the candidate", sub: "A normal phone call", detail: "The candidate gets a normal call on their phone. No app, no link. The AI says it is an AI right at the start." },
  { id: "pickup", x: col(6), y: L1, kind: "decision", title: "Did they pick up?", sub: "Answered, busy or no answer", detail: "If the call is answered, the conversation starts. If not, CallZest tries again later." },
  { id: "retry", x: col(6), y: B1, kind: "outcome", title: "Tries again later", sub: "On a later day, up to 3 tries", detail: "Unanswered or busy calls are tried again on later days, morning and afternoon, up to the number of attempts you allow." },

  // The conversation
  { id: "goodtime", x: col(0), y: L2, kind: "decision", title: "Is now a good time?", sub: "Asked first, every call", detail: "The AI introduces the role and asks if it is a good time to talk. The candidate decides." },
  { id: "callback", x: col(0), y: B2, kind: "outcome", title: "Callback booked", sub: "\"Call me tomorrow at 5\"", detail: "When the candidate asks to be called later, a callback is booked for that time (moved inside your calling hours) and the call happens then." },
  { id: "never", x: col(1), y: B2, kind: "outcome", title: "Never called again", sub: "\"Don't call me\" is final", detail: "If the candidate asks not to be called, they are marked opted out and are never called again." },
  { id: "questions", x: col(1), y: L2, kind: "auto", title: "Asks your questions", sub: "One at a time, like a recruiter", detail: "Experience, CTC, notice period, location, interest and availability, plus your must-haves. The AI waits for the candidate to finish and handles interruptions." },
  { id: "recruiter", x: col(2), y: B2, kind: "outcome", title: "Passed to your team", sub: "Questions only you can answer", detail: "When the candidate asks something only a recruiter can answer, the AI doesn't guess. The question is passed on to your team." },
  { id: "readback", x: col(2), y: L2, kind: "auto", title: "Reads answers back", sub: "The candidate can correct", detail: "At the end the AI reads the answers back so the candidate can confirm or correct them." },

  // After the call
  { id: "checked", x: col(3), y: L2, kind: "auto", title: "Answers checked", sub: "Against their own words", detail: "Every answer is checked against the transcript and kept with the candidate's own words. If two answers disagree, it is flagged for you to choose." },
  { id: "summary", x: col(4), y: L2, kind: "auto", title: "Summary written", sub: "Plus the full transcript", detail: "A short summary of the call is written. The full transcript and every answer are on the candidate's page." },
  { id: "interested", x: col(5), y: L2, kind: "decision", title: "Interested?", sub: "From the conversation", detail: "Candidates who are interested can go on to a second round. The rest are marked, so your team knows where everyone stands." },
  { id: "notinterested", x: col(5), y: B2, kind: "outcome", title: "Marked not interested", sub: "Visible on your dashboard", detail: "Not-interested candidates are marked on the job and the dashboard. Nobody has to call them to find out." },

  // Second round
  { id: "approve", x: col(0), y: L3, kind: "you", title: "Approve round questions", sub: "Written from the JD by AI", detail: "The AI writes questions from the job description, at the level you pick. You check them, change anything, then approve." },
  { id: "round", x: col(1), y: L3, kind: "auto", title: "Second round call", sub: "Interested candidates only", detail: "Interested candidates get a short second call with the approved questions." },
  { id: "scored", x: col(2), y: L3, kind: "auto", title: "Each answer scored", sub: "Out of 5, with a quote", detail: "Each answer gets a score out of 5 with the reason and the candidate's words, and the round gets an overall score out of 100." },
  { id: "verdict", x: col(3), y: L3, kind: "auto", title: "Fit verdict", sub: "Strong, possible or not a fit", detail: "The round ends with a verdict: Strong fit, Possible fit or Not a fit, so your shortlist is easy to read." },
  { id: "decide", x: col(4), y: L3, kind: "end", title: "Your team decides", sub: "Talk to the right people", detail: "Your recruiters pick up from here and spend their time only on the candidates worth talking to." },
];

export const EDGES: FlowEdge[] = [
  { from: "job", to: "upload" },
  { from: "upload", to: "rows" },
  { from: "rows", to: "start", label: "yes" },
  { from: "rows", to: "skipped", fromPort: "bottom", toPort: "top", label: "no" },
  { from: "start", to: "hours" },
  { from: "hours", to: "dial", label: "yes" },
  { from: "hours", to: "wait", fromPort: "bottom", toPort: "top", label: "no" },
  { from: "wait", to: "dial", fromPort: "right", toPort: "bottom", dashed: true },
  { from: "dial", to: "pickup" },
  { from: "pickup", to: "retry", fromPort: "bottom", toPort: "top", label: "no" },
  { from: "retry", to: "dial", fromPort: "left", toPort: "bottom", dashed: true },
  { from: "pickup", to: "goodtime", label: "yes", wrapY: 440 },
  { from: "goodtime", to: "questions", label: "yes" },
  { from: "goodtime", to: "callback", fromPort: "bottom", toPort: "top", label: "later" },
  { from: "goodtime", to: "never", fromPort: "bottom", toPort: "top", label: "stop" },
  { from: "questions", to: "readback" },
  { from: "questions", to: "recruiter", fromPort: "bottom", toPort: "top", dashed: true },
  { from: "readback", to: "checked" },
  { from: "checked", to: "summary" },
  { from: "summary", to: "interested" },
  { from: "interested", to: "notinterested", fromPort: "bottom", toPort: "top", label: "no" },
  { from: "interested", to: "approve", label: "yes", wrapY: 910 },
  { from: "approve", to: "round" },
  { from: "round", to: "scored" },
  { from: "scored", to: "verdict" },
  { from: "verdict", to: "decide" },
];

export const GROUPS: FlowGroup[] = [
  { label: "01 · Set up", x: 30, y: 60, w: 760, h: 330 },
  { label: "02 · Calling", x: 810, y: 60, w: 1050, h: 330 },
  { label: "03 · The conversation", x: 30, y: 480, w: 760, h: 330 },
  { label: "04 · After the call", x: 810, y: 480, w: 790, h: 330 },
  { label: "05 · Second round", x: 30, y: 940, w: 1310, h: 170 },
];

/** The happy path, in order, for "Run the flow". */
export const RUN = ["job", "upload", "rows", "start", "hours", "dial", "pickup", "goodtime", "questions", "readback", "checked", "summary", "interested", "approve", "round", "scored", "verdict", "decide"];

export const byId = (id: string) => NODES.find((n) => n.id === id) as FlowNode;

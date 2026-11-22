/**
 * Must-haves become extra yes / no questions on a requirement's screening call, asked after the
 * default questions. This spots a must-have that only repeats a default question ("At least 2
 * years of experience" when the call already asks for total experience), so the recruiter can
 * drop or sharpen it. Deliberately cautious: anything more specific ("2 years of experience in
 * Python") is not flagged.
 */

type Topic = { keys: string[]; words: string[] };

const TOPICS: Topic[] = [
  {
    keys: ["total_experience", "relevant_experience"],
    words: ["experience", "experienced", "exp", "yr", "yrs", "year", "years"],
  },
  {
    keys: ["notice_period"],
    words: ["notice", "joining", "join", "joiner", "immediate", "immediately"],
  },
  {
    keys: ["current_ctc", "expected_ctc"],
    words: ["ctc", "salary", "package", "lpa", "lakh", "lakhs", "pay"],
  },
  { keys: ["current_location"], words: ["location", "located", "based", "city"] },
  { keys: ["current_company"], words: ["company", "employer", "employed"] },
];

// Words that don't make a must-have more specific than the default question
const FILLER = new Set(
  (
    "a an the at least atleast atleas minimum min max maximum of in on with and or to up upto " +
    "should must have has having be is are total overall relevant under within less than more " +
    "plus above below period day days month months only required needed candidate"
  ).split(" "),
);

export type DefaultQuestion = { key: string; prompt: string };
export type Overlap = { number: number; key: string; prompt: string };

function words(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((w) => w && !/^\d+$/.test(w));
}

/** The default question this must-have only repeats (1-based number in `defaults`), or null. */
export function repeatsDefault(mustHave: string, defaults: DefaultQuestion[]): Overlap | null {
  const said = words(mustHave);
  for (const topic of TOPICS) {
    if (!said.some((w) => topic.words.includes(w))) continue;
    const rest = said.filter((w) => !topic.words.includes(w) && !FILLER.has(w));
    if (rest.length > 0) return null; // says something more specific
    const index = defaults.findIndex((q) => topic.keys.includes(q.key));
    if (index >= 0) return { number: index + 1, ...defaults[index] };
  }
  return null;
}

/** "10 default + 3 must-haves = 13 questions" */
export function questionCount(defaults: number, mustHaves: number): string {
  const total = defaults + mustHaves;
  const musts = `${mustHaves} must-have${mustHaves === 1 ? "" : "s"}`;
  return `${defaults} default + ${musts} = ${total} question${total === 1 ? "" : "s"}`;
}

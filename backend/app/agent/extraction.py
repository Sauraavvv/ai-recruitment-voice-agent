"""Validate and normalize what the LLM extracted (phase plan 5.8, P2-T5).

The LLM normalizes units; this module checks ranges, converts obvious slips (rupees instead of
lakhs), and drops any value whose evidence quote isn't in the candidate's actual words.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from app.agent.schemas import FIELD_TO_KEY, KEY_TO_FIELD, NUMERIC_FIELDS, AgentTurn, FieldName
from app.agent.state import FieldValue, ScreeningState

QUOTE_MATCH_THRESHOLD = 0.8
EXPERIENCE_RANGE = (0.0, 50.0)
CTC_RANGE = (0.5, 500.0)  # LPA
MAX_NOTICE_DAYS = 365
MAX_TEXT_LEN = 200
NUMERIC_KEYS = frozenset(f.value for f in NUMERIC_FIELDS)

_NUMBER_WORDS = {
    w: str(i)
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
} | {"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "ninety": "90"}


def normalize_key(raw: str | None, state: ScreeningState) -> str | None:
    """Map the model's field name (unit-suffixed, internal, or custom) to a state key."""
    if not raw:
        return None
    key = raw.strip().lower()
    if key in KEY_TO_FIELD:
        key = KEY_TO_FIELD[key].value
    return key if key in state.fields else None


def _norm_text(text: str) -> list[str]:
    tokens = re.sub(r"[^a-z0-9.]+", " ", text.lower().replace(",", "")).split()
    return [_NUMBER_WORDS.get(t, t.strip(".")) for t in tokens if t.strip(".")]


def contains_words(quote: str, utterance: str) -> bool:
    """Exact (normalized) containment: stricter than `quote_matches`, which is fuzzy and can
    match "twelve lakhs" against "eighteen lakhs"."""
    q, u = " ".join(_norm_text(quote)), " ".join(_norm_text(utterance))
    return bool(q) and f" {q} " in f" {u} "


def same_words(a: str, b: str) -> bool:
    """Same text once case, punctuation and number words are normalized ("Thirty days." ==
    "30 days")."""
    return _norm_text(a) == _norm_text(b)


def quote_matches(quote: str, utterance: str, threshold: float = QUOTE_MATCH_THRESHOLD) -> bool:
    """True if `quote` appears (fuzzily) in `utterance`. Number words and digits compare equal."""
    q, u = _norm_text(quote), _norm_text(utterance)
    if not q or not u:
        return False
    q_text = " ".join(q)
    if q_text in " ".join(u):
        return True
    best = 0.0
    for size in range(max(1, len(q) - 2), len(q) + 3):
        for start in range(0, max(1, len(u) - size + 1)):
            window = " ".join(u[start : start + size])
            best = max(best, SequenceMatcher(None, q_text, window).ratio())
            if best >= threshold:
                return True
    return False


def normalize_experience(value: float | None) -> float | None:
    if value is None or not EXPERIENCE_RANGE[0] <= value <= EXPERIENCE_RANGE[1]:
        return None
    return round(value, 1)


def normalize_ctc(value: float | None) -> float | None:
    """LPA. A value in rupees (e.g. 1200000) is converted; anything else out of range fails."""
    if value is None:
        return None
    if value >= 10_000:
        value = value / 100_000
    if not CTC_RANGE[0] <= value <= CTC_RANGE[1]:
        return None
    return round(value, 2)


_DAYS = re.compile(r"(\d+(?:\.\d+)?)\s*(day|week|month)s?", re.IGNORECASE)
_IMMEDIATE = re.compile(r"\b(immediate|immediately|right away|already free|no notice)", re.I)


def notice_days(text: str | None, llm_days: int | None) -> int | None:
    if llm_days is not None and 0 <= llm_days <= MAX_NOTICE_DAYS:
        return llm_days
    if not text:
        return None
    if _IMMEDIATE.search(text):
        return 0
    match = _DAYS.search(" ".join(_norm_text(text)))
    if not match:
        return None
    amount, unit = float(match.group(1)), match.group(2).lower()
    days = round(amount * {"day": 1, "week": 7, "month": 30}[unit])
    return days if days <= MAX_NOTICE_DAYS else None


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())[:MAX_TEXT_LEN]
    return value or None


@dataclass
class FieldUpdate:
    key: str
    value: FieldValue
    raw_text: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RangeUpdate:
    key: str
    low: float
    high: float
    raw_text: str


@dataclass
class ExtractionResult:
    updates: list[FieldUpdate] = field(default_factory=list)
    ranges: list[RangeUpdate] = field(default_factory=list)
    invalid: dict[str, str] = field(default_factory=dict)  # key -> reason (failed validation)
    dropped: dict[str, str] = field(default_factory=dict)  # key -> reason (unsupported by quote)
    declined: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    confirmed: list[str] = field(default_factory=list)


# Words that can't be a company or a place on their own ("Working at." was stored as a company
# on a real call when STT lost the name, 2026-11-19)
_FILLER = frozenset(
    """i i'm im am is it it's its my the a an at in with for of from to and so um uh er currently
    current working work works worked company companies office based located live living stay
    staying right now presently job employed here there city place""".split()
)


# A notice period talks about time (eval run 2026-11-19 stored "Any weekday after 4 pm" as one)
_NOTICE_WORDS = re.compile(
    r"\b(day|days|week|weeks|month|months|year|years|immediate|immediately|join|joining|"
    r"joiner|serving|notice|buy ?out|negotiable|lwd|last working|relieved|relieving)\b",
    re.IGNORECASE,
)


def has_name(text: str) -> bool:
    words = re.findall(r"[a-z0-9'&.-]+", text.lower())
    return any(w.strip(".'") not in _FILLER for w in words if w.strip(".'"))


def validate_field(
    name: FieldName, raw: Any, days: int | None
) -> tuple[FieldValue, dict[str, Any]]:
    if name in (FieldName.TOTAL_EXPERIENCE, FieldName.RELEVANT_EXPERIENCE):
        return normalize_experience(raw), {}
    if name in (FieldName.CURRENT_CTC, FieldName.EXPECTED_CTC):
        return normalize_ctc(raw), {}
    if name is FieldName.INTERESTED:
        return (raw if isinstance(raw, bool) else None), {}
    text = _clean_text(raw)
    if name in (FieldName.CURRENT_COMPANY, FieldName.CURRENT_LOCATION) and text:
        if not has_name(text):
            return None, {}  # → invalid: the agent asks again
    if name is FieldName.NOTICE_PERIOD and text:
        d = notice_days(text, days)
        if d is None and not _NOTICE_WORDS.search(text):
            return None, {}  # not a notice period at all
        return text, ({"days": d} if d is not None else {})
    return text, {}


def extract(turn: AgentTurn, utterance: str, state: ScreeningState) -> ExtractionResult:
    result = ExtractionResult()
    quotes: dict[str, str] = {}
    for ev in turn.evidence:
        key = normalize_key(ev.field, state)
        if key and quote_matches(ev.quote, utterance):
            quotes.setdefault(key, ev.quote)

    extracted = turn.extracted_fields.model_dump()
    for name, model_key in FIELD_TO_KEY.items():
        raw = extracted.get(model_key)
        if raw is None or name.value not in state.fields:
            continue
        quote = quotes.get(name.value)
        if quote is None:
            result.dropped[name.value] = "no matching evidence quote"
            continue
        value, meta = validate_field(name, raw, extracted.get("notice_period_days"))
        if value is None:
            result.invalid[name.value] = f"value out of range: {raw!r}"
            continue
        result.updates.append(FieldUpdate(name.value, value, quote, meta))

    for custom in turn.custom_answers:
        key = normalize_key(custom.key, state)
        spec = state.spec(key) if key else None
        if key is None or spec is None or spec.standard is not None:
            continue
        if not quote_matches(custom.quote, utterance):
            result.dropped[key] = "no matching evidence quote"
            continue
        if text := _clean_text(custom.answer):
            result.updates.append(FieldUpdate(key, text, custom.quote))

    updated = {u.key for u in result.updates}
    for r in turn.ranges:
        key = normalize_key(r.field, state)
        if key is None or key in updated or not quote_matches(r.quote, utterance):
            continue
        if key not in NUMERIC_KEYS:
            continue
        is_ctc = key in (FieldName.CURRENT_CTC, FieldName.EXPECTED_CTC)
        norm = normalize_ctc if is_ctc else normalize_experience
        low, high = norm(min(r.low, r.high)), norm(max(r.low, r.high))
        if low is not None and high is not None:
            result.ranges.append(RangeUpdate(key, low, high, r.quote))

    def keys(raw: list[str]) -> list[str]:
        out = []
        for item in raw:
            k = normalize_key(item, state)
            if k and k not in updated and k not in out:
                out.append(k)
        return out

    result.declined = keys(turn.declined_fields)
    result.unknown = keys(turn.unknown_fields)
    result.confirmed = [k for k in (normalize_key(i, state) for i in turn.confirmed_fields) if k]
    return result


def consistency_flags(state: ScreeningState) -> list[str]:
    """Fields whose values look inconsistent and should be confirmed (phase plan 5.8)."""
    flags = []
    f = state.fields
    total, relevant = f.get(FieldName.TOTAL_EXPERIENCE), f.get(FieldName.RELEVANT_EXPERIENCE)
    if (
        total
        and relevant
        and total.has_value
        and relevant.has_value
        and relevant.status.value == "answered"
        and float(relevant.value) > float(total.value)  # type: ignore[arg-type]
    ):
        flags.append(FieldName.RELEVANT_EXPERIENCE.value)
    current, expected = f.get(FieldName.CURRENT_CTC), f.get(FieldName.EXPECTED_CTC)
    if (
        current
        and expected
        and current.has_value
        and expected.has_value
        and expected.status.value == "answered"
        and float(expected.value) > 3 * float(current.value)  # type: ignore[arg-type]
    ):
        flags.append(FieldName.EXPECTED_CTC.value)
    return flags

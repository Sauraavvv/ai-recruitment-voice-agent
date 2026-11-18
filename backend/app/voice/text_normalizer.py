"""Turn agent text into words a TTS model reads correctly (phase-03 plan, P3-T10).

Kitten reads text literally, and its own clean-up follows US conventions, so we normalize here
with Indian ones: 1,20,000 → "one lakh twenty thousand", 12.5 LPA → "twelve point five lakhs per
annum", CTC → "C T C", 5:30 PM → "five thirty P M".

Respellings for names or companies that come out wrong live in `pronunciations.yaml`, which can
be edited without code changes.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from num2words import num2words

DEFAULT_LEXICON_PATH = Path(__file__).with_name("pronunciations.yaml")

MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
_MONTH_FULL = {m[:3].lower(): m for m in MONTHS.split("|")[:12]}
_YEAR_CONTEXT = r"(?:in|since|from|till|until|by|of|year|batch|graduated|passed out in)"
_NUMBER = r"\d+(?:,\d+)*(?:\.\d+)?"

_URL = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.IGNORECASE)
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_MARKS = re.compile(r"(\*\*|__|\*|`+|^#+\s*|^\s*[-•]\s+)", re.MULTILINE)
_SPACES = re.compile(r"\s+")
_TYPOGRAPHY: dict[int, str] = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "…": "..."})


@dataclass(frozen=True)
class Lexicon:
    """Whole-word respellings, plus all-caps words to read as words rather than letters."""

    words: dict[str, str] = field(default_factory=dict)
    acronyms_as_words: frozenset[str] = frozenset()

    def pattern(self) -> re.Pattern[str] | None:
        if not self.words:
            return None
        keys = sorted(self.words, key=len, reverse=True)
        return re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, keys)) + r")(?![\w-])", re.I)


def load_lexicon(path: Path = DEFAULT_LEXICON_PATH) -> Lexicon:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    words = {str(k): str(v) for k, v in (data.get("words") or {}).items()}
    keep = frozenset(str(w).upper() for w in (data.get("acronyms_as_words") or []))
    return Lexicon(words=words, acronyms_as_words=keep)


def _plain(value: str) -> str:
    return value.replace(",", "")


def number_words(value: str) -> str:
    """'1,20,000' → 'one lakh twenty thousand'; '12.5' → 'twelve point five'."""
    text = num2words(float(v) if "." in (v := _plain(value)) else int(v), lang="en_IN")
    return str(text).replace(",", "").replace("-", " ")


def _ordinal(value: str) -> str:
    return str(num2words(int(value), lang="en_IN", to="ordinal")).replace("-", " ")


def _year(value: str) -> str:
    return str(num2words(int(value), lang="en_IN", to="year")).replace("-", " ")


def _time(hour: str, minute: str | None, meridiem: str) -> str:
    words = number_words(hour)
    if minute and minute != "00":
        words += (" oh " if minute.startswith("0") else " ") + number_words(minute.lstrip("0"))
    return f"{words} {meridiem.upper()[0]} M"


def _month(name: str) -> str:
    return _MONTH_FULL.get(name[:3].lower(), name)


def _spell_digits(digits: str) -> str:
    names = "zero one two three four five six seven eight nine".split()
    return " ".join(names[int(d)] for d in digits if d.isdigit())


def _strip_emoji(text: str) -> str:
    return "".join(
        ch
        for ch in text
        if not (unicodedata.category(ch) in {"So", "Cs", "Co"} or 0xFE00 <= ord(ch) <= 0xFE0F)
        or ch == "₹"
    )


class TextNormalizer:
    def __init__(self, lexicon: Lexicon | None = None) -> None:
        self.lexicon = lexicon if lexicon is not None else default_lexicon()
        self._lexicon_re = self.lexicon.pattern()
        self._lexicon_lower = {k.lower(): v for k, v in self.lexicon.words.items()}

    def __call__(self, text: str) -> str:
        t = unicodedata.normalize("NFKC", text)
        t = t.translate(_TYPOGRAPHY)
        t = _MD_LINK.sub(r"\1", t)
        t = _URL.sub("", t)
        t = _MD_MARKS.sub("", t)
        t = _strip_emoji(t)
        if self._lexicon_re is not None:
            t = self._lexicon_re.sub(lambda m: self._lexicon_lower[m.group(1).lower()], t)
        t = self._money(t)
        t = self._dates_and_times(t)
        t = self._numbers(t)
        t = self._acronyms(t)
        t = t.replace("&", " and ").replace("@", " at ").replace("#", "").replace("*", "")
        t = re.sub(r"\s+([,.?!])", r"\1", t)
        return _SPACES.sub(" ", t).strip()

    # --- money and units ---------------------------------------------------------------------

    def _money(self, t: str) -> str:
        unit = r"(?:\s*(lakhs?|lacs?|crores?|cr|k|thousand))?"
        # ₹12.5 lakh / Rs. 50,000 / INR 50000 → "twelve point five lakh rupees"
        t = re.sub(
            rf"(?:₹|\bRs\.?|\bINR)\s*({_NUMBER}){unit}\b",
            lambda m: f"{number_words(m.group(1))}{self._unit(m.group(2))} rupees",
            t,
            flags=re.I,
        )
        # 12.5 LPA / 12 L.P.A. → "twelve point five lakhs per annum"
        t = re.sub(
            rf"\b({_NUMBER})\s*(?:LPA|L\.P\.A\.?)(?![\w])",
            lambda m: f"{number_words(m.group(1))} lakhs per annum",
            t,
            flags=re.I,
        )
        t = re.sub(r"\bLPA\b", "lakhs per annum", t)
        t = re.sub(r"\bp\.a\.(?=\s|$)", "per annum", t, flags=re.I)
        t = re.sub(r"\b(\d+)\s*(?:yrs?|years?)\b", lambda m: f"{m.group(1)} years", t, flags=re.I)
        t = re.sub(rf"\b({_NUMBER})\s*%", lambda m: f"{number_words(m.group(1))} percent", t)
        return t

    @staticmethod
    def _unit(raw: str | None) -> str:
        if not raw:
            return ""
        u = raw.lower()
        if u.startswith(("lakh", "lac")):
            return " lakh"
        if u.startswith(("crore", "cr")):
            return " crore"
        return " thousand"

    # --- dates and times ---------------------------------------------------------------------

    def _dates_and_times(self, t: str) -> str:
        # 5 PM / 5:30 pm / 9:05 a.m. A dotted "a.m." at a sentence end keeps the full stop.
        t = re.sub(
            r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])(?:\.\s?m\.(\s*$|\s+(?=(?-i:[A-Z])))?|\s?m\b)",
            lambda m: (
                _time(m.group(1), m.group(2), m.group(3))
                + ("." + m.group(4) if m.group(4) is not None else "")
            ),
            t,
            flags=re.I,
        )
        t = re.sub(
            rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTHS})\b\.?",
            lambda m: f"{_ordinal(m.group(1))} {_month(m.group(2))}",
            t,
        )
        t = re.sub(
            rf"\b({MONTHS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!:)",
            lambda m: f"{_month(m.group(1))} {_ordinal(m.group(2))}",
            t,
        )
        t = re.sub(
            rf"\b((?:{MONTHS})\s+)((?:19|20)\d\d)\b", lambda m: m.group(1) + _year(m.group(2)), t
        )
        t = re.sub(
            rf"\b({_YEAR_CONTEXT}\s+)((?:19|20)\d\d)\b",
            lambda m: m.group(1) + _year(m.group(2)),
            t,
            flags=re.I,
        )
        return t

    # --- other numbers -----------------------------------------------------------------------

    def _numbers(self, t: str) -> str:
        # phone numbers and other long digit strings are read digit by digit
        t = re.sub(r"\+?\b\d[\d\s-]{8,}\d\b", lambda m: _spell_digits(m.group()), t)
        t = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", lambda m: _ordinal(m.group(1)), t)
        # 5-7 years / 5 – 7 → "5 to 7"
        t = re.sub(rf"\b({_NUMBER})\s*(?:-|–|—|to)\s*({_NUMBER})\b", r"\1 to \2", t)
        t = re.sub(rf"(?<![\w.]){_NUMBER}(?![\w])", lambda m: number_words(m.group()), t)
        return t

    # --- acronyms ----------------------------------------------------------------------------

    def _acronyms(self, t: str) -> str:
        def spell(m: re.Match[str]) -> str:
            word, plural = m.group(1), m.group(2)
            if word in self.lexicon.acronyms_as_words:
                return m.group()
            return " ".join(word) + ("s" if plural else "")

        # CTC → "C T C", MNCs → "M N Cs"; single capitals like "I" and "A" are left alone
        return re.sub(r"\b([A-Z]{2,5})(s?)\b", spell, t)


@lru_cache
def default_lexicon() -> Lexicon:
    return load_lexicon(DEFAULT_LEXICON_PATH)


@lru_cache
def default_normalizer() -> TextNormalizer:
    return TextNormalizer()


def normalize_for_speech(text: str) -> str:
    return default_normalizer()(text)

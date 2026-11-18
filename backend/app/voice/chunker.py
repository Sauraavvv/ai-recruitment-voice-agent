"""Split agent replies into speakable chunks for TTS.

Rules (phase-03 plan, P3-T8):
- Split at sentence ends (. ? !) but not inside decimals (5.5), after abbreviations (Mr., Pvt.,
  e.g.) or after initials (A. P. J.).
- Keep chunks to about MAX_WORDS words; longer sentences split at a comma, semicolon or
  conjunction near the middle.
- Merge fragments shorter than MIN_WORDS into a neighbour, except a complete first sentence
  ("Got it.", "Thanks, Rahul."): a short first chunk starts audio sooner.

`split_into_chunks` handles a whole reply. `StreamingChunker` takes text as it arrives (if LLM
streaming is added later) and only releases chunks whose end is certain.
"""

import re

MAX_WORDS = 20
MIN_WORDS = 3
# A first chunk this long or longer is split at an early comma ("Got it, ...") if there is one.
LONG_FIRST_WORDS = 10
EARLY_BREAK_WORDS = 4

ABBREVIATIONS = frozenset(
    {
        "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "vs", "etc", "approx",
        "pvt", "ltd", "inc", "co", "corp", "dept", "est", "no", "nos", "ph", "ref",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
        "e.g", "i.e", "a.m", "p.m",
    }
)  # fmt: skip

_SENTENCE_END = re.compile(r"[.?!]+[\"')\]]*(?=\s|$)")
_SOFT_BREAK = re.compile(r"[,;:—–]\s+|\s+(?=(?:and|but|so|or|because|which)\s)", re.IGNORECASE)
_WORD = re.compile(r"\S+")


def _word_count(text: str) -> int:
    return len(_WORD.findall(text))


def _is_false_end(text: str, end: int) -> bool:
    """Is the '.' that ends at `end` part of an abbreviation, initial or number?"""
    if text[end - 1] != ".":
        return False
    before = text[: end - 1]
    token = before.rsplit(None, 1)[-1] if before.strip() else ""
    token = token.lstrip("(\"'")
    if not token:
        return False
    if len(token) == 1 and token.isalpha() and token.isupper():
        return True  # an initial: "A. P. J. Abdul Kalam"
    if token.lower() in ABBREVIATIONS:
        return True
    # "e.g." / "i.e." / "a.m." have an inner dot: the token before the final "." is "e.g"
    return token.lower().rstrip(".") in ABBREVIATIONS


def split_sentences(text: str) -> list[str]:
    text = " ".join(text.split())
    sentences, start = [], 0
    for match in _SENTENCE_END.finditer(text):
        end = match.end()
        # Only a lone "." can belong to an abbreviation or initial; "?", "!" and "..." always end.
        if match.group().rstrip("\"')]") == "." and _is_false_end(text, match.start() + 1):
            continue
        sentence = text[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = end
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _split_long(sentence: str, max_words: int) -> list[str]:
    """Split at the soft break closest to the middle, recursively, until every piece fits."""
    words = _word_count(sentence)
    if words <= max_words:
        return [sentence]
    best: tuple[int, int] | None = None  # (distance from the middle, split index)
    for match in _SOFT_BREAK.finditer(sentence):
        cut = match.end() if match.group().strip() else match.start()
        left = _word_count(sentence[:cut])
        if left < MIN_WORDS or words - left < MIN_WORDS:
            continue
        distance = abs(left - words / 2)
        if best is None or distance < best[0]:
            best = (int(distance), cut)
    if best is None:
        # no natural break: cut at the word limit
        tokens = sentence.split()
        head, rest = " ".join(tokens[:max_words]), " ".join(tokens[max_words:])
        return [head, *_split_long(rest, max_words)]
    cut = best[1]
    return [
        *_split_long(sentence[:cut].strip(), max_words),
        *_split_long(sentence[cut:].strip(), max_words),
    ]


def _early_break(sentence: str) -> list[str]:
    """'Got it, so what is your notice period?' → ['Got it,', 'so what is your notice period?']."""
    if _word_count(sentence) < LONG_FIRST_WORDS:
        return [sentence]
    match = re.search(r",\s+", sentence)
    if match and 1 <= _word_count(sentence[: match.start()]) <= EARLY_BREAK_WORDS:
        return [sentence[: match.start() + 1], sentence[match.end() :]]
    return [sentence]


def _merge_short(chunks: list[str], keep_first: bool) -> list[str]:
    """Fold a short chunk into the next one (a short last chunk into the one before)."""
    merged: list[str] = []
    for chunk in chunks:
        first_is_locked = keep_first and len(merged) == 1
        if merged and _word_count(merged[-1]) < MIN_WORDS and not first_is_locked:
            merged[-1] = f"{merged[-1]} {chunk}"
        else:
            merged.append(chunk)
    if len(merged) > 1 and _word_count(merged[-1]) < MIN_WORDS:
        tail = merged.pop()
        merged[-1] = f"{merged[-1]} {tail}"
    return merged


def split_into_chunks(text: str, *, max_words: int = MAX_WORDS) -> list[str]:
    sentences = split_sentences(text)
    if not sentences:
        return []
    first, *rest = sentences
    pieces = [*_early_break(first), *rest]
    chunks: list[str] = []
    for piece in pieces:
        chunks.extend(_split_long(piece, max_words))
    # A complete short first sentence ("Got it.", "Okay.") stays on its own.
    keep_first = bool(re.search(r"[.?!,]$", chunks[0]))
    return _merge_short(chunks, keep_first)


class StreamingChunker:
    """Feed text as it arrives; get chunks back once a later sentence proves they're complete.

    Only whole sentences are released, so earlier output never changes. The short-first-chunk
    rule applies to the first release only.
    """

    def __init__(self, *, max_words: int = MAX_WORDS) -> None:
        self._max_words = max_words
        self._buffer = ""
        self._started = False

    def _chunk(self, text: str) -> list[str]:
        chunks = split_into_chunks(text, max_words=self._max_words)
        if self._started and len(chunks) > 1 and _word_count(chunks[0]) < MIN_WORDS:
            chunks[:2] = [f"{chunks[0]} {chunks[1]}"]
        self._started = self._started or bool(chunks)
        return chunks

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        sentences = split_sentences(self._buffer)
        # The last sentence may still grow, and a trailing "." may turn out to be "Mr."
        if len(sentences) < 2:
            return []
        trailing_space = " " if self._buffer[-1:].isspace() else ""
        self._buffer = sentences[-1] + trailing_space
        return self._chunk(" ".join(sentences[:-1]))

    def flush(self) -> list[str]:
        rest, self._buffer = self._buffer, ""
        return self._chunk(rest)

"""Text normalization for speech (phase-03 plan, P3-T10)."""

from pathlib import Path

import pytest

from app.voice.text_normalizer import (
    Lexicon,
    TextNormalizer,
    load_lexicon,
    normalize_for_speech,
    number_words,
)


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("12.5", "twelve point five"),
        ("1,20,000", "one lakh twenty thousand"),
        ("1,00,00,000", "one crore"),
        ("60", "sixty"),
        ("0.5", "zero point five"),
    ],
)
def test_number_words_use_indian_conventions(raw: str, spoken: str) -> None:
    assert number_words(raw) == spoken


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        # salary and units
        ("Your current CTC is 12.5 lakhs per annum.",
         "Your current C T C is twelve point five lakhs per annum."),
        ("Expected 18 LPA.", "Expected eighteen lakhs per annum."),
        ("That's ₹1,20,000 a month.", "That's one lakh twenty thousand rupees a month."),
        ("Rs. 15 lakh", "fifteen lakh rupees"),
        ("INR 2 crore", "two crore rupees"),
        ("a 20% hike", "a twenty percent hike"),
        ("5-7 years", "five to seven years"),
        ("60 days", "sixty days"),
        # times and dates
        ("tomorrow at 5 PM", "tomorrow at five P M"),
        ("at 5:30 pm.", "at five thirty P M."),
        ("at 9:05 a.m. Thanks.", "at nine oh five A M. Thanks."),
        ("10 a.m. tomorrow", "ten A M tomorrow"),
        ("on Thursday, 19 November at 5:30 PM.",
         "on Thursday, nineteenth November at five thirty P M."),
        ("on Dec 3rd", "on December third"),
        ("the 2nd round", "the second round"),
        ("joined in 2019", "joined in twenty nineteen"),
        # acronyms, symbols, clean-up
        ("I'm an AI assistant from HR.", "I'm an A I assistant from H R."),
        ("TCS and other MNCs", "T C S and other M N Cs"),
        ("R&D", "R and D"),
        ("**Great** news 😊", "Great news"),
        ("See https://example.com now", "See now"),
        ("Call +91 98765 43210", "Call nine one nine eight seven six five four three two one zero"),
        ("“Fine,” she said…", '"Fine," she said...'),
    ],
)  # fmt: skip
def test_normalize_for_speech(text: str, spoken: str) -> None:
    assert normalize_for_speech(text) == spoken


def test_plain_sentences_are_unchanged() -> None:
    text = "Hello, am I speaking with Priya Iyer?"
    assert normalize_for_speech(text) == text


def test_default_lexicon_respells_known_words() -> None:
    assert normalize_for_speech("I work at HCLTech.") == "I work at H C L Tech."
    assert normalize_for_speech("Is that ok?") == "Is that okay?"


def test_lexicon_is_whole_word_and_case_insensitive() -> None:
    norm = TextNormalizer(Lexicon(words={"Gurgaon": "Gurgaaon"}))
    assert norm("I live in gurgaon.") == "I live in Gurgaaon."
    assert norm("Gurgaonite") == "Gurgaonite"


def test_acronyms_as_words_are_not_spelled() -> None:
    norm = TextNormalizer(Lexicon(acronyms_as_words=frozenset({"NASA"})))
    assert norm("NASA and ISRO") == "NASA and I S R O"


def test_load_lexicon_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "lex.yaml"
    path.write_text("words:\n  Venkatesh: Venkatesh\n  Iyer: Eye-er\nacronyms_as_words: [covid]\n")
    lexicon = load_lexicon(path)
    assert lexicon.words["Iyer"] == "Eye-er"
    assert lexicon.acronyms_as_words == frozenset({"COVID"})


def test_empty_lexicon_file(tmp_path: Path) -> None:
    path = tmp_path / "lex.yaml"
    path.write_text("# nothing yet\n")
    assert load_lexicon(path) == Lexicon()


def test_shipped_lexicon_loads() -> None:
    lexicon = load_lexicon()
    assert lexicon.words  # the file in the repo parses and isn't empty

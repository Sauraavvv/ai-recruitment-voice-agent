"""Sentence chunking for TTS (phase-03 plan, P3-T8)."""

import pytest

from app.voice.chunker import MAX_WORDS, StreamingChunker, split_into_chunks, split_sentences


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello. How are you?", ["Hello.", "How are you?"]),
        ("You have 5.5 years. Right?", ["You have 5.5 years.", "Right?"]),
        ("Mr. Sharma called. Dr. Iyer did too.", ["Mr. Sharma called.", "Dr. Iyer did too."]),
        ("It's with Wipro Pvt. Ltd. in Pune.", ["It's with Wipro Pvt. Ltd. in Pune."]),
        ("Languages, e.g. Java, are fine.", ["Languages, e.g. Java, are fine."]),
        ("A. P. J. Abdul Kalam spoke.", ["A. P. J. Abdul Kalam spoke."]),
        ("Wait! Really?! Yes...", ["Wait!", "Really?!", "Yes..."]),
        ('He said "fine." Then left.', ['He said "fine."', "Then left."]),
        ("  no   final punctuation  ", ["no final punctuation"]),
        ("", []),
    ],
)
def test_split_sentences(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


def test_short_first_sentence_stays_alone() -> None:
    assert split_into_chunks("Got it. What is your notice period?") == [
        "Got it.",
        "What is your notice period?",
    ]


def test_long_first_sentence_breaks_at_an_early_comma() -> None:
    chunks = split_into_chunks("Got it, so what is your current notice period at Infosys, in days?")
    assert chunks[0] == "Got it,"
    assert " ".join(chunks) == "Got it, so what is your current notice period at Infosys, in days?"


def test_short_later_fragments_are_merged() -> None:
    chunks = split_into_chunks("Thanks for that, Priya. Okay. And what is your expected CTC?")
    assert chunks == ["Thanks for that, Priya.", "Okay. And what is your expected CTC?"]


def test_short_last_fragment_joins_the_previous_chunk() -> None:
    chunks = split_into_chunks("We'll call you back on Thursday at five. Thanks!")
    assert chunks == ["We'll call you back on Thursday at five. Thanks!"]


def test_long_sentence_splits_at_a_comma_near_the_middle() -> None:
    text = (
        "Thanks. Just to confirm, you have 5.5 years of experience, a current CTC of 12.5 lakhs, "
        "an expected CTC of 18 lakhs and a notice period of 60 days. Is that correct?"
    )
    chunks = split_into_chunks(text)
    assert chunks[0] == "Thanks."
    assert all(len(c.split()) <= MAX_WORDS for c in chunks)
    assert " ".join(chunks) == text
    assert "12.5" in " ".join(chunks)  # decimals never split


def test_sentence_without_breaks_is_cut_at_the_word_limit() -> None:
    text = " ".join(f"w{i}" for i in range(45)) + "."
    chunks = split_into_chunks(text, max_words=20)
    assert [len(c.split()) for c in chunks] == [20, 20, 5]


def test_every_word_is_kept_in_order() -> None:
    text = (
        "Great, thank you. It's a Backend Developer position with Northwind Labs based in Pune. "
        "Could you tell me about your current role, the team you work with, the main technologies "
        "you use day to day, and why you are looking for a change right now?"
    )
    assert " ".join(split_into_chunks(text)).split() == text.split()


def test_streaming_releases_only_complete_sentences() -> None:
    chunker = StreamingChunker()
    out: list[str] = []
    assert chunker.feed("Got it") == []
    out += chunker.feed(". Mr. Sha")
    out += chunker.feed("rma said hello. What is ")
    out += chunker.feed("your notice period?")
    out += chunker.flush()
    assert out == ["Got it.", "Mr. Sharma said hello.", "What is your notice period?"]


def test_streaming_matches_batch_for_whole_text() -> None:
    text = "Thanks, Rahul. And what is your notice period, in days?"
    chunker = StreamingChunker()
    assert chunker.feed(text) + chunker.flush() == split_into_chunks(text)

"""Kitten's English BART grapheme-to-phoneme fallback, run with ONNX Runtime instead of PyTorch.

Upstream (`kittenml.kittentts2_tiny.frontend.english.Fallback`) loads the BART with PyTorch and
transformers. `OnnxFallback` is a drop-in replacement: the same CMUdict-then-BART lookup and the
same greedy decoding, on a graph exported by `app.scripts.export_g2p_onnx` (verified identical
to PyTorch on a word list; see docs/benchmarks/tts.md).
"""

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort

DEFAULT_G2P_ONNX = Path(__file__).resolve().parents[2] / "voice" / "g2p" / "g2p_bart_en_us.onnx"


class OnnxBartG2P:
    """Greedy decoding, matching transformers' generate(num_beams=1, do_sample=False) for this
    model: start from decoder_start_token_id, stop at eos, force eos at max_length - 1."""

    def __init__(self, onnx_path: Path = DEFAULT_G2P_ONNX) -> None:
        meta = json.loads(onnx_path.with_suffix(".json").read_text(encoding="utf-8"))
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1  # a tiny graph: extra threads only add overhead
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(onnx_path), options, providers=["CPUExecutionProvider"]
        )
        self.g2i = {c: i for i, c in enumerate(meta["grapheme_chars"]) if i > 3}
        self.i2p = {i: c for i, c in enumerate(meta["phoneme_chars"]) if i > 3}
        self.max_len = int(meta["max_length"])
        self._start = int(meta["decoder_start_token_id"])
        self._eos = int(meta["eos_token_id"])

    def _decode(self, ids: list[int]) -> list[int]:
        src = np.array([ids], dtype=np.int64)
        out = [self._start]
        while len(out) < self.max_len:
            logits = self._session.run(
                None, {"input_ids": src, "decoder_input_ids": np.array([out], dtype=np.int64)}
            )[0]
            token = self._eos if len(out) == self.max_len - 1 else int(np.argmax(logits[0]))
            out.append(token)
            if token == self._eos:
                break
        return out

    def phonemes(self, word: str) -> str:
        step = self.max_len - 2  # room for <s> and </s>
        parts = []
        for i in range(0, len(word), step):
            ids = [1] + [self.g2i[c] for c in word[i : i + step]] + [2]
            parts.append("".join(self.i2p.get(t, "") for t in self._decode(ids)))
        return "".join(parts)


def make_fallback_class(base: type) -> type:
    """Subclass upstream's Fallback, replacing only its PyTorch parts (__init__ and _bart)."""

    class OnnxFallback(base):  # type: ignore[misc]
        def __init__(self, model_dir: str, cmu_lexicon: str) -> None:
            with open(cmu_lexicon, encoding="utf-8") as f:
                self.cmu = json.load(f)
            self._g2p = OnnxBartG2P()
            self.g2i = self._g2p.g2i
            self.i2p = self._g2p.i2p
            self.max_len = self._g2p.max_len
            letters = re.escape("".join(self.g2i))
            self._pieces = re.compile(rf"(\d+)|([{letters}]+)|(.)", re.S)
            self._memo: dict[str, str] = {}
            self.used: list[tuple[str, str, str]] = []
            self.skipped: list[str] = []

        def _bart(self, word: str) -> str:
            if word not in self._memo:
                # same final substitution upstream applies
                self._memo[word] = self._g2p.phonemes(word).replace("ɾ", "T").replace("ʔ", "t")
            return self._memo[word]

    return OnnxFallback


def install() -> None:
    """Make kittenml's English front end use the ONNX fallback. Call before loading a model."""
    from kittenml.kittentts2_tiny.frontend import english

    if getattr(english.Fallback, "_rcai_onnx", False):
        return
    cls: Any = make_fallback_class(english.Fallback)
    cls._rcai_onnx = True
    english.Fallback = cls

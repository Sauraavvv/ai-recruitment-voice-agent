"""Export Kitten's English BART grapheme-to-phoneme model to ONNX, so the backend needs no PyTorch.

Kitten-TTS 2 guesses the pronunciation of words missing from its dictionaries (most Indian names)
with a 0.75M-parameter BART. Upstream runs it in PyTorch, which would add about 700 MB to the
image. This script exports the same weights once; `app.providers.tts.g2p_onnx` runs them with
ONNX Runtime and is checked against PyTorch by `--verify`.

Run it outside the backend environment (it needs torch and transformers), for example:

    uv venv /tmp/g2p && uv pip install -p /tmp/g2p torch transformers onnx onnxruntime numpy
    /tmp/g2p/bin/python -m app.scripts.export_g2p_onnx --model-dir <repo>/g2p/g2p_bart_en_us \
        --out app/voice/g2p/g2p_bart_en_us.onnx --verify words.txt

The output is committed. Re-export only when the Kitten model revision changes.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def export(model_dir: Path, out: Path) -> None:
    import torch
    from transformers import BartForConditionalGeneration

    model = BartForConditionalGeneration.from_pretrained(model_dir, local_files_only=True).eval()

    class NextTokenLogits(torch.nn.Module):
        def __init__(self, bart: Any) -> None:
            super().__init__()
            self.bart = bart

        def forward(self, input_ids: Any, decoder_input_ids: Any) -> Any:
            out = self.bart(
                input_ids=input_ids, decoder_input_ids=decoder_input_ids, use_cache=False
            )
            return out.logits[:, -1, :]

    wrapper = NextTokenLogits(model).eval()
    ids = torch.tensor([[1, 10, 11, 12, 2]])
    dec = torch.tensor([[1, 5]])
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        wrapper,
        (ids, dec),
        str(out),
        input_names=["input_ids", "decoder_input_ids"],
        output_names=["logits"],
        dynamic_axes={"input_ids": {1: "src"}, "decoder_input_ids": {1: "tgt"}},
        opset_version=17,
        dynamo=False,
    )
    # Keep only what the runtime decoder needs next to the graph.
    cfg = model.config
    meta = {
        "grapheme_chars": cfg.grapheme_chars,
        "phoneme_chars": cfg.phoneme_chars,
        "max_length": cfg.max_position_embeddings,
        "decoder_start_token_id": cfg.decoder_start_token_id,
        "eos_token_id": cfg.eos_token_id,
    }
    out.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB) and {out.with_suffix('.json').name}")


def verify(model_dir: Path, onnx_path: Path, words_file: Path) -> int:
    import torch
    from transformers import BartForConditionalGeneration

    from app.providers.tts.g2p_onnx import OnnxBartG2P

    model = BartForConditionalGeneration.from_pretrained(model_dir, local_files_only=True).eval()
    cfg = model.config
    g2i = {c: i for i, c in enumerate(cfg.grapheme_chars) if i > 3}
    i2p = {i: c for i, c in enumerate(cfg.phoneme_chars) if i > 3}
    step = cfg.max_position_embeddings - 2

    def reference(word: str) -> str:  # upstream kittenml Fallback._bart, unchanged
        out = []
        for i in range(0, len(word), step):
            ids = torch.tensor([[1] + [g2i[c] for c in word[i : i + step]] + [2]])
            with torch.no_grad():
                gen = model.generate(
                    input_ids=ids,
                    max_length=cfg.max_position_embeddings,
                    num_beams=1,
                    do_sample=False,
                )
            out.append("".join(i2p.get(int(t), "") for t in gen[0]))
        return "".join(out)

    g2p = OnnxBartG2P(onnx_path)
    words = [w for w in words_file.read_text().split() if w and all(c in g2i for c in w)]
    mismatches = [(w, a, b) for w in words if (a := reference(w)) != (b := g2p.phonemes(w))]
    for w, a, b in mismatches[:20]:
        print(f"MISMATCH {w!r}: torch={a!r} onnx={b!r}")
    print(f"{len(words) - len(mismatches)}/{len(words)} words identical")
    return 1 if mismatches else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model-dir", type=Path, required=True, help="<repo>/g2p/g2p_bart_en_us")
    parser.add_argument("--out", type=Path, default=Path("app/voice/g2p/g2p_bart_en_us.onnx"))
    parser.add_argument("--verify", type=Path, help="file of words to compare against PyTorch")
    parser.add_argument("--skip-export", action="store_true")
    args = parser.parse_args()
    if not args.skip_export:
        export(args.model_dir, args.out)
    if args.verify:
        sys.exit(verify(args.model_dir, args.out, args.verify))


if __name__ == "__main__":
    main()

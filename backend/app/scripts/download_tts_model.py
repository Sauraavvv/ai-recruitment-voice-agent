"""Download the Kitten TTS 2 nano English model files into a local directory.

Runs at image build time (backend/Dockerfile) and for local development (`make tts-model`), so a
call never waits on a download. Only the English files are fetched, at a pinned revision.

Standalone on purpose (huggingface_hub only): the Dockerfile runs it before the app code is copied,
so the download layer stays cached across code changes.

    python app/scripts/download_tts_model.py --dest models/kitten-tts-2-nano
"""

import argparse
import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ID = "KittenML/kitten-tts-2-nano"
# Pinned revision (2026-11-18). Change deliberately, then re-run the Phase 3 checks
# (make test-tts, make bench-tts, a listening check) and re-export the G2P graph if g2p/ changed.
REVISION = "54526b8d8e45333cd720d3a082c106aacf416064"
FILES = (
    "config.json",
    "vocab.json",
    "kitten_tts_2_nano_en.onnx",
    "voices_en.npz",
    "g2p/cmu_misaki_us.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=REPO_ID, revision=REVISION, allow_patterns=list(FILES), local_dir=str(dest)
    )
    missing = [f for f in FILES if not (dest / f).is_file()]
    if missing:
        raise SystemExit(f"download incomplete, missing: {missing}")
    manifest = {"repo_id": REPO_ID, "revision": REVISION, "sha256": {}}
    for f in FILES:
        manifest["sha256"][f] = sha256(dest / f)  # type: ignore[index]
    (dest / "MODEL_MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"{REPO_ID}@{REVISION[:10]} → {dest}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dest", type=Path, required=True)
    download(parser.parse_args().dest)


if __name__ == "__main__":
    main()

"""Talk into the microphone and watch Deepgram transcribe it live (plan P4-T3, T4, T5).

    make stt-mic [RATE=8000]      # on the Mac host; Ctrl+C to stop

Partials update in place; each finished utterance is printed with its confidence, what ended it
(speech_final or UtteranceEnd) and its latency from the end of speech. While you're quiet, the
time since the last speech is shown, which is what Phase 6's silence timeouts will use.
`RATE=8000` sends the phone-band version of your voice.
"""

import argparse
import asyncio
import contextlib
import sys
import time
import uuid

from app.config import get_settings
from app.providers.stt import create_stt_provider
from app.providers.stt.base import STTError
from app.utils.log import configure_logging
from app.voice import pcm
from app.voice.local_loop import mic_frames
from app.voice.utterance import UtteranceAssembler

MIC_RATE = 16000


async def run(args: argparse.Namespace) -> int:
    stt = create_stt_provider(get_settings(), keyterms=args.keyterm)
    session_id = f"mic-{uuid.uuid4().hex[:8]}"
    assembler = UtteranceAssembler(session_id)
    try:
        await stt.start_stream(session_id=session_id, encoding="linear16", sample_rate=args.rate)
    except STTError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"session {session_id}, {args.rate} Hz. Speak; Ctrl+C to stop.\n")

    async def pump() -> None:
        async for frame in mic_frames(MIC_RATE):
            if args.rate == 8000:
                frame = pcm.phone_band(frame, MIC_RATE)
            await stt.send_audio(frame)

    async def show() -> None:
        async for event in stt.events():
            utterance = assembler.feed(event)
            if event.kind == "partial":
                print(f"\r\033[K\033[2m… {assembler.preview}\033[0m", end="", flush=True)
            elif event.kind == "error":
                print(f"\r\033[K[error] {event.detail}")
            if utterance is not None:
                spoken = stt.sent_at(utterance.ended_at) if utterance.ended_at else None
                ms = f"{(utterance.completed_at - spoken) * 1000:.0f} ms" if spoken else "?"
                print(
                    f"\r\033[K\033[1m» {utterance.text}\033[0m  \033[2m[conf "
                    f"{utterance.confidence or 0:.2f}, {utterance.trigger}, {ms}]\033[0m"
                )

    async def quiet_timer() -> None:
        while True:
            await asyncio.sleep(0.5)
            if not assembler.in_speech and assembler.last_speech_at is not None:
                idle = time.monotonic() - assembler.last_speech_at
                print(f"\r\033[K\033[2m(quiet for {idle:.1f} s)\033[0m", end="", flush=True)

    tasks = [asyncio.create_task(t) for t in (pump(), show(), quiet_timer())]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await stt.close()
        print(f"\naudio sent {stt.stats.audio_s_sent:.0f} s, reconnects {stt.stats.reconnects}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live microphone transcription")
    parser.add_argument("--rate", type=int, default=16000, choices=(8000, 16000))
    parser.add_argument("--keyterm", action="append", default=[])
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging("INFO" if args.verbose else "WARNING")
    with contextlib.suppress(KeyboardInterrupt):
        return asyncio.run(run(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())

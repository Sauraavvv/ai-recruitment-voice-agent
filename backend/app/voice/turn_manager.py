"""Whose turn it is (phase-06 §5.2): a transition table, no I/O.

`voice/pipeline.py` turns everything that happens on a call into a `TurnEvent`, asks
`TurnManager.handle()` what to do and runs the returned actions in order. Keeping the rules in
one table makes them easy to read and to test row by row.

    LISTENING ──utterance──► THINKING ──first audio──► SPEAKING ──played──► LISTENING
        ▲   │silence             │ utterance: cancel, merge, rerun   │ barge-in
        │   └──► THINKING        └─ reply with end_call ─► ENDING    ▼
        └───────────────────────────────────────────────────────── LISTENING
    ENDING ──played──► ENDED (hang up).  Caller hang-up from anywhere → ENDED.

The wrap-up after CALL_WRAP_UP_S isn't a turn event: the pipeline asks the agent to read back
at its next reply (`ConversationManager.request_wrap_up`).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum


class TurnState(StrEnum):
    STARTING = "starting"  # stream up, greeting not played yet
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ENDING = "ending"  # closing line playing; hang up when it has played
    ENDED = "ended"


class TurnEvent(StrEnum):
    STREAM_STARTED = "stream_started"
    UTTERANCE = "utterance"  # the candidate finished an utterance (not a held backchannel)
    BACKCHANNEL = "backchannel"  # a short "yes"/"okay" while the agent speaks
    SPEECH_STARTED = "speech_started"  # VAD: the candidate started talking
    AGENT_REPLY = "agent_reply"  # reply text ready (or a template)
    END_REPLY = "end_reply"  # reply ready, and it ends the call
    FIRST_AUDIO = "first_audio"  # the reply's first frame went out
    PLAYBACK_DONE = "playback_done"  # mark came back (or its timeout)
    BARGE_IN = "barge_in"
    SILENCE = "silence"  # no speech for SILENCE_TIMEOUT_S after the agent finished
    TIME_UP = "time_up"  # hard call limit: closing line now
    CALLER_HANGUP = "caller_hangup"
    FAILURE = "failure"  # STT/TTS/LLM gave up: apologise and end


class Act(StrEnum):
    WAIT_HELLO_THEN_GREET = "wait_hello_then_greet"
    RUN_AGENT = "run_agent"  # handle_utterance in a task
    PLAY_ACK = "play_ack"  # cached "Okay." while the agent thinks
    CANCEL_AGENT = "cancel_agent"  # and stop the reply if it was already playing
    MERGE_AND_RERUN = "merge_and_rerun"  # roll the turn back, run it on both utterances
    SPEAK_REPLY = "speak_reply"
    STOP_PLAYBACK = "stop_playback"  # clear + heard portion + handle_interruption
    REDISPATCH = "redispatch"  # handle the same event again in the new state
    HOLD_BACKCHANNEL = "hold_backchannel"
    RELEASE_BACKCHANNEL = "release_backchannel"  # a held "yes" answers a yes/no question
    START_SILENCE_TIMER = "start_silence_timer"
    STOP_SILENCE_TIMER = "stop_silence_timer"
    RUN_SILENCE_PROMPT = "run_silence_prompt"
    SPEAK_TIME_UP = "speak_time_up"
    PLAY_APOLOGY = "play_apology"
    HANG_UP = "hang_up"
    FINISH = "finish"  # stop everything (the caller is gone)
    IGNORE = "ignore"


S, E, A = TurnState, TurnEvent, Act

TABLE: dict[tuple[TurnState, TurnEvent], tuple[TurnState, tuple[Act, ...]]] = {
    (S.STARTING, E.STREAM_STARTED): (S.THINKING, (A.WAIT_HELLO_THEN_GREET,)),
    # Listening
    (S.LISTENING, E.UTTERANCE): (S.THINKING, (A.STOP_SILENCE_TIMER, A.RUN_AGENT, A.PLAY_ACK)),
    (S.LISTENING, E.BACKCHANNEL): (S.THINKING, (A.STOP_SILENCE_TIMER, A.RUN_AGENT, A.PLAY_ACK)),
    (S.LISTENING, E.SPEECH_STARTED): (S.LISTENING, (A.STOP_SILENCE_TIMER,)),
    (S.LISTENING, E.SILENCE): (S.THINKING, (A.RUN_SILENCE_PROMPT,)),
    # Thinking (the agent works on a reply; an acknowledgement may be playing)
    (S.THINKING, E.UTTERANCE): (S.THINKING, (A.CANCEL_AGENT, A.MERGE_AND_RERUN)),
    (S.THINKING, E.BACKCHANNEL): (S.THINKING, (A.CANCEL_AGENT, A.MERGE_AND_RERUN)),
    (S.THINKING, E.AGENT_REPLY): (S.THINKING, (A.SPEAK_REPLY,)),
    (S.THINKING, E.END_REPLY): (S.ENDING, (A.SPEAK_REPLY,)),
    (S.THINKING, E.FIRST_AUDIO): (S.SPEAKING, ()),
    (S.THINKING, E.PLAYBACK_DONE): (S.LISTENING, (A.START_SILENCE_TIMER,)),  # empty reply
    # Speaking
    (S.SPEAKING, E.PLAYBACK_DONE): (
        S.LISTENING,
        (A.START_SILENCE_TIMER, A.RELEASE_BACKCHANNEL),
    ),
    (S.SPEAKING, E.BARGE_IN): (S.LISTENING, (A.STOP_PLAYBACK, A.START_SILENCE_TIMER)),
    (S.SPEAKING, E.UTTERANCE): (S.LISTENING, (A.STOP_PLAYBACK, A.REDISPATCH)),
    (S.SPEAKING, E.BACKCHANNEL): (S.SPEAKING, (A.HOLD_BACKCHANNEL,)),
    # Ending: the closing line plays to the end, whatever the candidate says
    (S.ENDING, E.FIRST_AUDIO): (S.ENDING, ()),
    (S.ENDING, E.PLAYBACK_DONE): (S.ENDED, (A.HANG_UP,)),
}

# From any live state
ANY: dict[TurnEvent, tuple[TurnState, tuple[Act, ...]]] = {
    E.CALLER_HANGUP: (S.ENDED, (A.FINISH,)),
    E.FAILURE: (S.ENDING, (A.CANCEL_AGENT, A.STOP_SILENCE_TIMER, A.PLAY_APOLOGY)),
    E.TIME_UP: (S.ENDING, (A.CANCEL_AGENT, A.STOP_SILENCE_TIMER, A.SPEAK_TIME_UP)),
}


@dataclass
class TurnManager:
    state: TurnState = TurnState.STARTING
    history: list[tuple[TurnState, TurnEvent, TurnState]] = field(default_factory=list)

    def handle(self, event: TurnEvent) -> tuple[Act, ...]:
        if self.state is TurnState.ENDED:
            return (Act.IGNORE,)
        row = TABLE.get((self.state, event))
        if row is None:
            # Once the closing line is playing, a failure or the time limit changes nothing
            if event in ANY and not (event is not E.CALLER_HANGUP and self.state is S.ENDING):
                row = ANY[event]
            else:
                return (Act.IGNORE,)
        new_state, acts = row
        self.history.append((self.state, event, new_state))
        self.state = new_state
        return acts

    def handled(self) -> Iterable[str]:
        return (f"{a}-{e}->{b}" for a, e, b in self.history)

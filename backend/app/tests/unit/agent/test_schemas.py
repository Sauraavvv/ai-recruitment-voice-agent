"""AgentTurn must stay valid for OpenAI strict structured outputs; changes must be deliberate.

Regenerate the snapshot after an intended change:
    UPDATE_SNAPSHOTS=1 pytest app/tests/unit/agent/test_schemas.py
"""

import json
import os
from pathlib import Path
from typing import Any

from openai.lib._pydantic import to_strict_json_schema

from app.agent.prompts import PROMPT_VERSION
from app.agent.schemas import AgentTurn

SNAPSHOT = Path(__file__).parent / "agent_turn.schema.json"


def _walk(node: Any) -> list[dict[str, Any]]:
    found = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            found.append(node)
        for v in node.values():
            found += _walk(v)
    elif isinstance(node, list):
        for v in node:
            found += _walk(v)
    return found


def test_every_object_is_strict() -> None:
    schema = to_strict_json_schema(AgentTurn)
    objects = _walk(schema)
    assert objects
    for obj in objects:
        assert obj.get("additionalProperties") is False
        assert set(obj.get("required", [])) == set(obj.get("properties", {}))


def test_schema_snapshot() -> None:
    schema = to_strict_json_schema(AgentTurn)
    if os.getenv("UPDATE_SNAPSHOTS") or not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    assert schema == json.loads(SNAPSHOT.read_text()), (
        "AgentTurn schema changed. If intended, bump PROMPT_VERSION "
        f"(now {PROMPT_VERSION}) and regenerate with UPDATE_SNAPSHOTS=1."
    )

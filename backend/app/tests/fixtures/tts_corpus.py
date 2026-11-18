"""Agent replies for TTS tests and benchmarks (P3-AC1: at least 100 replies synthesize).

Two sources: every assistant line in the Phase 2 live-eval results, and the Phase 2 templates
rendered over a matrix of Indian names, companies, cities and values.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.agent import prompts
from app.agent.prompts import CandidateContext, JobConfig

FIXTURES = Path(__file__).parent
EVAL_RESULTS = FIXTURES.parent / "agent_eval" / "results"
SENTENCES_FILE = FIXTURES / "tts_sentences.txt"

NAMES = [
    "Rahul Sharma",
    "Priya Iyer",
    "Venkatesh Subramanian",
    "Ananya Chatterjee",
    "Siddharth Gaikwad",
    "Fatima Siddiqui",
    "Gurpreet Kaur",
    "Arjun Nair",
]
JOBS = [
    ("Backend Developer", "Infosys", "Bengaluru"),
    ("QA Engineer", "TCS", "Hyderabad"),
    ("Data Analyst", "Wipro", "Noida"),
    ("Site Reliability Engineer", "HCLTech", "Gurgaon"),
]  # fmt: skip


def listening_sentences() -> list[str]:
    lines = SENTENCES_FILE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def eval_replies() -> list[str]:
    replies: list[str] = []
    for path in sorted(EVAL_RESULTS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):  # latency benchmark files are lists
            continue
        for run in data.get("runs", []):
            replies += [t["text"] for t in run.get("transcript", []) if t["speaker"] == "assistant"]
    return replies


def template_replies() -> list[str]:
    out: list[str] = []
    for i, name in enumerate(NAMES):
        title, company, city = JOBS[i % len(JOBS)]
        job = JobConfig.from_dict({"job_title": title, "company_name": company, "location": city})
        cand = CandidateContext(name=name)
        out += [
            prompts.greeting(cand),
            prompts.introduction(cand, job),
            prompts.role_line(job),
            prompts.closing(cand),
            prompts.declined_close(cand),
            prompts.max_turns_close(cand),
        ]
        for spec in job.questions:
            out += [prompts.ask(spec), prompts.clarify(spec)]
            out.append(prompts.ask(spec, prefix=f"Thanks, {cand.first_name}."))
        by_key = {q.key: q for q in job.questions}
        values: dict[str, list[Any]] = {
            "total_experience": [2, 5.5, 12],
            "current_ctc": [4.5, 12.5, 30],
            "expected_ctc": [6, 18, 42.5],
            "notice_period": ["immediate", "30 days", "90 days"],
            "interested": [True, False],
        }
        for key, options in values.items():
            if key in by_key:
                out.append(prompts.confirm_value(by_key[key], options[i % len(options)]))
        if "total_experience" in by_key:
            out.append(prompts.range_clarify(by_key["total_experience"], 4, 6))
        if "current_ctc" in by_key:
            out.append(prompts.range_clarify(by_key["current_ctc"], 12, 15))
        out.append(
            prompts.callback_confirm(
                datetime(2026, 11, 19 + i % 5, 10 + i, 30 * (i % 2), tzinfo=prompts.IST)
            )
        )
    return out


def agent_corpus() -> list[str]:
    """Unique replies, in a stable order."""
    return list(
        dict.fromkeys(r.strip() for r in [*eval_replies(), *template_replies()] if r.strip())
    )

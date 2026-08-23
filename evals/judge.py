"""LLM judge — subordinate to the oracle, sees TRANSCRIPTS ONLY.

One judge invocation per call transcript (never the whole ladder). The rubric
is the scenario's yes/no questions; every answer must carry a verbatim quote,
which keeps the judge grounded in the transcript instead of vibes. Model is
pinned via JUDGE_MODEL (default anthropic — a different family from the
gpt-4.1-mini generator, per the locked design).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel
from pydantic_ai import Agent

from evals.contracts import CallTranscript

# The judge key (ANTHROPIC_API_KEY) lives in the repo .env; JUDGE_MODEL in
# evals/.env.eval. Neither load overrides real env vars.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env.eval")

INSTRUCTIONS = (
    "You are grading ONE conversation transcript between a home-health agency "
    "assistant and a nurse. Answer each rubric question with a strict yes/no "
    "verdict and quote the exact transcript line that decides it. Judge only "
    "what the transcript shows — never assume unstated behavior."
)


class RubricAnswer(BaseModel):
    question: str
    verdict: bool
    quote: str


class JudgeResult(BaseModel):
    answers: list[RubricAnswer]
    model: str

    @property
    def all_yes(self) -> bool:
        return all(a.verdict for a in self.answers)


def _render(transcript: CallTranscript) -> str:
    lines = [f"[{t.role}] {t.text}" for t in transcript.turns]
    return "\n".join(lines) or "(empty transcript)"


async def judge_transcript(transcript: CallTranscript, rubric: list[str]) -> JudgeResult:
    model = os.getenv("JUDGE_MODEL", "anthropic:claude-sonnet-4-6")
    agent = Agent(model, output_type=list[RubricAnswer], instructions=INSTRUCTIONS)
    questions = "\n".join(f"- {q}" for q in rubric)
    result = await agent.run(
        f"TRANSCRIPT ({transcript.channel}, prospect {transcript.prospect_id}):\n"
        f"{_render(transcript)}\n\nRUBRIC QUESTIONS:\n{questions}"
    )
    return JudgeResult(answers=result.output, model=model)


def agreement(judge_all_yes: list[bool], oracle_confirmed: list[bool]) -> dict:
    """Judge-vs-oracle calibration across k runs of one scenario.

    UNSTABLE (quarantine, never averaged) when the judge flips across runs or
    disagrees with the oracle on 2+ runs — per the locked design §4.6/4.7.
    """
    pairs = list(zip(judge_all_yes, oracle_confirmed, strict=True))
    agree = sum(1 for j, o in pairs if j == o)
    disagreements = len(pairs) - agree
    flipped = len(set(judge_all_yes)) > 1
    return {
        "runs": len(pairs),
        "agreement_pct": round(100.0 * agree / len(pairs), 1) if pairs else None,
        "stability": "UNSTABLE" if (flipped or disagreements >= 2) else "stable",
    }

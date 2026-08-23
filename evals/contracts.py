"""Data contracts — every shape the harness passes around, in one file.

Flow: a runner produces RunArtifacts (transcripts + tool spans + timings)
and a DbSnapshot (the eval DB rows for one run). The oracle consumes both
and returns CheckResults. Scenario is the parsed *.scenario.yaml.
Nothing here talks to the network or the database.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class Turn(BaseModel):
    role: Literal["user", "agent"]
    text: str
    ts: datetime | None = None


class Span(BaseModel):
    """One tool execution, captured at the tool boundary by a runner."""
    span_id: str
    parent_id: str | None = None
    agent: str                      # front_desk | offer_agent | sms_agent
    tool: str | None = None
    args: dict[str, Any] | None = None
    ts: datetime | None = None
    duration_ms: float | None = None


class CallTranscript(BaseModel):
    prospect_id: str                # nurse slug (e.g. CG-101)
    channel: str                    # voice | sms | whatsapp
    turns: list[Turn] = Field(default_factory=list)
    # The exact instructions the agent was built with — read by the
    # no_context_bleed check, never by the judge.
    agent_instructions: str | None = None

    def agent_turns(self) -> int:
        return sum(1 for t in self.turns if t.role == "agent")


class Timings(BaseModel):
    ttfa_ms: float | None = None            # first reply latency (per channel defn)
    per_turn_ms: list[float] = Field(default_factory=list)
    total_ms: float | None = None
    # Keys match livekit ChatMessage.metrics: transcription_delay,
    # end_of_turn_delay, llm_node_ttft, tts_node_ttfb, e2e_latency.
    # Absent keys mean "not measured" and are reported as MISSING, never faked.
    stage_ms: dict[str, float] | None = None


class RunArtifacts(BaseModel):
    scenario_id: str
    run_idx: int = 0
    engine_profile: str = "cascade"
    transcripts: list[CallTranscript] = Field(default_factory=list)
    spans: list[Span] = Field(default_factory=list)
    timings: Timings = Field(default_factory=Timings)
    db_ref: str = ""                # path to this run's snapshot.json


class DbSnapshot(BaseModel):
    """All rows of one eval run, dumped post-run (or hand-crafted in tests).

    The oracle reads ONLY this + RunArtifacts, so a live dump and a
    hand-written fixture are interchangeable. events are ordered by (at, id).
    """
    run_agency_id: str = ""
    agencies: list[dict] = Field(default_factory=list)
    nurses: list[dict] = Field(default_factory=list)
    patients: list[dict] = Field(default_factory=list)
    shifts: list[dict] = Field(default_factory=list)
    offers: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    slug_map: dict[str, str] = Field(default_factory=dict)   # "CG-101" -> uuid

    def uuid(self, slug: str) -> str:
        return self.slug_map.get(slug, slug)

    def slug(self, uuid: str) -> str:
        for s, u in self.slug_map.items():
            if u == uuid:
                return s
        return uuid

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.model_dump_json(indent=1))

    @classmethod
    def load(cls, path: str | Path) -> DbSnapshot:
        return cls.model_validate_json(Path(path).read_text())


class CheckResult(BaseModel):
    name: str
    status: Literal["pass", "fail", "skip"]
    evidence: str = ""


class EndState(BaseModel):
    """Machine-checkable end state (replaces the brief's prose form)."""
    shift: str | None = None        # shift slug; None = the run's only shift
    status: str                     # filled | escalated | offers_out | ...
    winner: str | None = None       # nurse slug; None = seat must stay empty


class Scenario(BaseModel):
    """Parsed *.scenario.yaml — the single source of truth for one scenario."""
    model_config = ConfigDict(extra="allow")   # forward-compatible extras

    scenario_id: str
    schema_version: int = 1
    scenario_version: int = 1
    description: str = ""
    layer: str = "e2e"                          # unit|component|simulation|e2e
    purpose: list[str] = Field(default_factory=lambda: ["regression"])
    channel: str = "sms"                        # voice|sms|ladder
    engine_profile: str = "cascade"             # never gemma_phi
    callout_fixture: dict = Field(default_factory=dict)
    roster_fixture: list[dict] = Field(default_factory=list)
    persona: dict = Field(default_factory=dict)     # {style, policy: [...]}
    expected_end_state: EndState | None = None
    expected_rank_order: list[str] = Field(default_factory=list)
    max_turn_budget: int | None = None
    invariants: list[str] = Field(default_factory=list)
    judge_rubric: list[str] = Field(default_factory=list)
    gates: list[str] = Field(default_factory=list)
    tolerances: dict = Field(default_factory=dict)
    k_trials: int = 1
    seed: int = 0
    tags: list[str] = Field(default_factory=list)
    # Ladder-scenario extras (see ARCHITECTURE.md §4.3):
    frozen_now: str | None = None               # freeze workers.rungs.now at this ISO time
    quiet_hours_expect: Literal["none", "defer", "escalate"] = "none"
    expected_memory: dict = Field(default_factory=dict)   # {slug: {avoid_dows: [5,6]}}

    @classmethod
    def load(cls, path: str | Path) -> Scenario:
        data = yaml.safe_load(Path(path).read_text())
        if data.get("engine_profile") == "gemma_phi":
            raise ValueError(f"{data.get('scenario_id')}: gemma_phi is never evaluated")
        return cls.model_validate(data)

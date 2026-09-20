"""EMR client contract — one interface, every backend behind it.

A driver turns one queued EmrJob into idempotent writes on a system of
record. Drivers are selected per agency by the registry (emr_backend picks
the protocol family; emr_profile picks vendor config inside the FHIR
driver). Rock's domain code never imports a driver — only the outbox
drainer (workers/outbox_worker.py) builds and calls one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

EmrKind = Literal[
    "seed_agency", "upsert_practitioner", "upsert_patient", "upsert_appointment",
    "callout_documented", "shift_reassigned", "escalated", "shift_cancelled",
    "encounter_start", "encounter_end",  # designed, not wired
]

EMR_KINDS: tuple[str, ...] = (
    "seed_agency", "upsert_practitioner", "upsert_patient", "upsert_appointment",
    "callout_documented", "shift_reassigned", "escalated", "shift_cancelled",
    "encounter_start", "encounter_end",
)


@dataclass(frozen=True)
class EmrJob:
    """One outbox row, as the driver sees it. Ids only — data rides EmrContext."""
    kind: EmrKind
    agency_id: str
    shift_id: str | None = None
    nurse_id: str | None = None
    patient_id: str | None = None
    idempotency_key: str = ""          # set by the enqueue RPCs (data/emr.sql)
    attempt: int = 0                   # 1-based try number, for logs


@dataclass
class EmrResult:
    ok: bool
    external_ids: dict[str, str] = field(default_factory=dict)  # {"Appointment": "123"}
    detail: str = ""                    # short, PHI-free
    retry_after_seconds: int | None = None


class EmrTransientError(Exception):
    """Network, 5xx, 408, 429, or an ambiguous timeout. Retry with backoff."""


class EmrPermanentError(Exception):
    """4xx other than 409/412/429, validation failure, unsupported resource,
    unknown backend. Dead-letter immediately so misconfig is visible fast."""


@dataclass
class EmrContext:
    """Fresh rows read by the drainer at execute time. Never persisted.

    links maps (rock_kind, rock_id, external_type) -> external id for this
    agency; external_type is part of the key because one nurse maps to BOTH
    a Practitioner and a PractitionerRole on a FHIR backend.
    """
    agency: dict
    shift: dict | None
    nurse: dict | None
    patient: dict | None
    links: dict[tuple[str, str, str], str]
    secret: str | None                  # resolved from agencies.emr_secret_ref


class EmrClient(Protocol):
    backend: str                                      # "mock" | "fhir" | ...

    async def capabilities(self) -> dict: ...         # what this backend can do

    async def execute(self, job: EmrJob, ctx: EmrContext) -> EmrResult:
        """The only write entry point. MUST be safe to call twice per job."""
        ...

    async def pull_changes(self, since_iso: str | None,
                           ctx: EmrContext) -> list[dict]:
        """Sync-in (EHR -> Rock); [] when the backend is push-based or mock."""
        ...

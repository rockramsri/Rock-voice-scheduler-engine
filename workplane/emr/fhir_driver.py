"""One FHIR R4 driver. Profiles change defaults; this file is the write path.

Every write is: conditional-create by Rock identifier, then update by id
with If-Match. Replaying a job hits the same identifiers and does not
create a second resource. Links are stored after each step so a crash
mid-job resumes as no-ops.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from urllib.parse import quote

import aiohttp

from data import db
from workplane.emr import mapping
from workplane.emr.auth import make_auth
from workplane.emr.base import (
    EmrContext, EmrJob, EmrPermanentError, EmrResult, EmrTransientError,
)
from workplane.emr.profiles import FhirProfile, load_profile

_TIMEOUT = aiohttp.ClientTimeout(total=20)


def _token_url(fhir_base: str) -> str:
    """Medplum's token endpoint lives on the server root, not under /fhir/R4."""
    base = fhir_base.rstrip("/")
    if base.endswith("/fhir/R4"):
        return base[: -len("/fhir/R4")] + "/oauth2/token"
    if "/fhir" in base:
        return base.split("/fhir", 1)[0] + "/oauth2/token"
    return base + "/oauth2/token"


def _id_from(data: Any, headers: dict) -> str | None:
    if isinstance(data, dict):
        # OpenEMR create returns {id: numeric, uuid: fhir-id}. Prefer uuid.
        if data.get("uuid"):
            return str(data["uuid"])
        if data.get("id"):
            return str(data["id"])
        if data.get("pid"):
            return str(data["pid"])
    loc = headers.get("Location") or headers.get("location") or ""
    parts = loc.rstrip("/").split("/")
    if "_history" in parts:
        parts = parts[: parts.index("_history")]
    return parts[-1] if parts and parts[-1] else None


def _issue(data: Any) -> str:
    if isinstance(data, dict) and data.get("issue"):
        first = data["issue"][0]
        details = first.get("details")
        text = details.get("text") if isinstance(details, dict) else None
        return str(text or first.get("diagnostics") or first.get("code") or "")[:160]
    if isinstance(data, dict):
        if data.get("validationErrors"):
            return str(data["validationErrors"])[:160]
        return str(data.get("message") or data.get("error") or "")[:160]
    return ""


class FhirDriver:
    def __init__(self, agency: dict, profile: FhirProfile | None = None):
        self.profile = profile or load_profile(agency.get("emr_profile"))
        self.backend = self.profile.name
        self.base = (agency.get("emr_base_url") or self.profile.default_base_url).rstrip("/")
        if not self.base:
            raise EmrPermanentError("emr_base_url is empty")
        kind = agency.get("emr_auth_kind") or self.profile.default_auth_kind
        self.auth = make_auth(
            kind, client_id=agency.get("emr_client_id"),
            token_url=self.profile.token_url(self.base),
            verify_tls=self.profile.verify_tls)

    async def capabilities(self) -> dict:
        status, data, _ = await self._request("GET", "metadata", secret=None)
        if status >= 400:
            raise EmrTransientError(f"metadata {status}")
        return {"fhirVersion": data.get("fhirVersion"), "software": data.get("software")}

    async def read(self, rtype: str, rid: str, ctx: EmrContext) -> dict | None:
        status, data, _ = await self._request(
            "GET", f"{rtype}/{rid}", secret=ctx.secret)
        if status == 404:
            return None
        if status >= 400:
            self._raise(status, data)
        return data

    async def pull_changes(self, since_iso: str | None, ctx: EmrContext) -> list[dict]:
        """Practitioner + Patient resources newer than `since` (raw FHIR)."""
        out: list[dict] = []
        for rtype in ("Practitioner", "Patient"):
            path = f"{rtype}?_count=200"
            if since_iso:
                instant = mapping.fhir_instant(since_iso)
                try:
                    overlap = datetime.fromisoformat(
                        instant.replace("Z", "+00:00")) - timedelta(seconds=5)
                    instant = overlap.strftime("%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    pass
                path += f"&_lastUpdated=gt{quote(instant, safe='')}"
            status, data, _ = await self._request("GET", path, secret=ctx.secret)
            if status >= 500:
                raise EmrTransientError(f"pull {rtype} {status}")
            if status >= 400:
                raise EmrPermanentError(f"pull {rtype} {status}: {_issue(data)}")
            for entry in (data.get("entry") or []) if isinstance(data, dict) else []:
                resource = entry.get("resource")
                if resource:
                    out.append(resource)
        return out

    async def execute(self, job: EmrJob, ctx: EmrContext) -> EmrResult:
        handler = {
            "seed_agency": self._seed_agency,
            "upsert_practitioner": self._upsert_practitioner,
            "upsert_patient": self._upsert_patient,
            "upsert_appointment": self._upsert_appointment,
            "callout_documented": self._callout,
            "shift_reassigned": self._reassigned,
            "escalated": self._escalated,
            "shift_cancelled": self._cancelled,
        }.get(job.kind)
        if handler is None:
            raise EmrPermanentError(f"unsupported kind: {job.kind}")
        ids = await handler(job, ctx)
        return EmrResult(ok=True, external_ids=ids, detail=self.backend)

    # ---- kinds ----

    async def _seed_agency(self, job: EmrJob, ctx: EmrContext) -> dict:
        return {"Organization": await self._ensure_org(ctx)}

    async def _upsert_practitioner(self, job: EmrJob, ctx: EmrContext) -> dict:
        if not ctx.nurse:
            raise EmrPermanentError("nurse row missing")
        org = await self._ensure_org(ctx)
        prac = await self._ensure_pract(ctx, ctx.nurse)
        return {"Organization": org, "Practitioner": prac}

    async def _upsert_patient(self, job: EmrJob, ctx: EmrContext) -> dict:
        if not ctx.patient:
            raise EmrPermanentError("patient row missing")
        org = await self._ensure_org(ctx)
        pat = await self._ensure_patient(ctx)
        return {"Organization": org, "Patient": pat}

    async def _upsert_appointment(self, job: EmrJob, ctx: EmrContext) -> dict:
        ids = await self._ensure_people(ctx)
        ids["Appointment"] = await self._ensure_appt(ctx, ids.get("Patient"),
                                                     ids.get("Practitioner"))
        return ids

    async def _callout(self, job: EmrJob, ctx: EmrContext) -> dict:
        ids = await self._ensure_people(ctx)
        appt = await self._ensure_appt(ctx, ids.get("Patient"), ids.get("Practitioner"))
        ids["Appointment"] = appt
        await self._update(ctx, "Appointment", appt,
                           lambda r: _mark_callout(r, ids.get("Practitioner")))
        task_key = f"{ctx.shift['id']}.{mapping.compact_ts(ctx.shift.get('callout_at'))}"
        if "Task" in self.profile.skip_types:
            await self._skip(ctx, "Task")
        else:
            ids["Task"] = await self._ensure(
                ctx, "Task", task_key,
                mapping.task(task_key, status="requested",
                             focus_ref=f"Appointment/{appt}"),
                "shift", ctx.shift["id"])
        return ids

    async def _reassigned(self, job: EmrJob, ctx: EmrContext) -> dict:
        if not ctx.nurse or not ctx.shift:
            raise EmrPermanentError("winner nurse or shift missing")
        ids = {"Organization": await self._ensure_org(ctx),
               "Practitioner": await self._ensure_pract(ctx, ctx.nurse)}
        if ctx.patient:
            ids["Patient"] = await self._ensure_patient(ctx)
        appt = ctx.links.get(("shift", str(ctx.shift["id"]), "Appointment"))
        if not appt:
            appt = await self._ensure_appt(ctx, ids.get("Patient"), ids["Practitioner"])
        ids["Appointment"] = appt
        await self._update(ctx, "Appointment", appt,
                           lambda r: _mark_filled(r, ids["Practitioner"]))
        task_key = f"{ctx.shift['id']}.{mapping.compact_ts(ctx.shift.get('callout_at'))}"
        if "Task" in self.profile.skip_types:
            await self._skip(ctx, "Task")
        else:
            task_id = ctx.links.get(("shift", str(ctx.shift["id"]), "Task"))
            if task_id:
                await self._update(ctx, "Task", task_id, _mark_task_done)
            else:
                task_id = await self._ensure(
                    ctx, "Task", task_key,
                    mapping.task(task_key, status="completed",
                                 focus_ref=f"Appointment/{appt}"),
                    "shift", ctx.shift["id"])
            ids["Task"] = task_id
        if "Provenance" in self.profile.skip_types:
            await self._skip(ctx, "Provenance")
        else:
            recorded = str(ctx.shift.get("callout_at") or datetime.now(UTC).isoformat())
            ids["Provenance"] = await self._ensure(
                ctx, "Provenance", task_key,
                mapping.provenance(task_key, target_ref=f"Appointment/{appt}",
                                   recorded=recorded),
                "shift", ctx.shift["id"])
        return ids

    async def _escalated(self, job: EmrJob, ctx: EmrContext) -> dict:
        if not ctx.shift:
            raise EmrPermanentError("shift row missing")
        ids = {"Organization": await self._ensure_org(ctx)}
        if "Task" in self.profile.skip_types:
            await self._skip(ctx, "Task")
            return ids
        task_id = ctx.links.get(("shift", str(ctx.shift["id"]), "Task"))
        if task_id:
            await self._update(ctx, "Task", task_id, _mark_task_hold)
        else:
            key = f"{ctx.shift['id']}.escalated"
            task_id = await self._ensure(
                ctx, "Task", key, mapping.task(key, status="on-hold"),
                "shift", ctx.shift["id"])
        ids["Task"] = task_id
        return ids

    async def _cancelled(self, job: EmrJob, ctx: EmrContext) -> dict:
        if not ctx.shift:
            raise EmrPermanentError("shift row missing")
        appt = ctx.links.get(("shift", str(ctx.shift["id"]), "Appointment"))
        if not appt:
            return {}
        await self._update(ctx, "Appointment", appt,
                           lambda r: r.update(status="cancelled"))
        return {"Appointment": appt}

    # ---- ensure helpers ----

    async def _ensure_org(self, ctx: EmrContext) -> str:
        agency = ctx.agency
        return await self._ensure(ctx, "Organization", agency["id"],
                                  mapping.organization(agency),
                                  "agency", agency["id"])

    async def _ensure_pract(self, ctx: EmrContext, nurse: dict) -> str:
        _, _, send_phone = mapping.send_flags(ctx.agency)
        return await self._ensure(ctx, "Practitioner", nurse["id"],
                                  mapping.practitioner(nurse, send_phone=send_phone),
                                  "nurse", nurse["id"])

    async def _ensure_patient(self, ctx: EmrContext) -> str:
        send_name, send_address, _ = mapping.send_flags(ctx.agency)
        row = ctx.patient
        return await self._ensure(ctx, "Patient", row["id"],
                                  mapping.patient(row, send_name=send_name,
                                                  send_address=send_address),
                                  "patient", row["id"])

    async def _ensure_appt(self, ctx: EmrContext, patient_id: str | None,
                           pract_id: str | None) -> str:
        if self.profile.rest_appointment:
            return await self._ensure_rest_appt(ctx)
        pref = f"Patient/{patient_id}" if patient_id else None
        nref = f"Practitioner/{pract_id}" if pract_id else None
        return await self._ensure(
            ctx, "Appointment", ctx.shift["id"],
            mapping.appointment(ctx.shift, patient_ref=pref, practitioner_ref=nref),
            "shift", ctx.shift["id"])

    async def _ensure_rest_appt(self, ctx: EmrContext) -> str:
        existing = ctx.links.get(("shift", str(ctx.shift["id"]), "Appointment"))
        if existing:
            return existing
        pid = None
        if ctx.patient:
            pid = ctx.links.get(("patient", str(ctx.patient["id"]), "PatientPid"))
        if not pid:
            raise EmrPermanentError("OpenEMR appointment needs a patient pid")
        start = mapping.fhir_instant(ctx.shift.get("starts_at"))
        end = mapping.fhir_instant(ctx.shift.get("ends_at"))
        payload = {
            "pc_catid": "5",
            "pc_title": "Home Visit",
            "pc_duration": "60",
            "pc_hometext": "rock-shift",
            "pc_apptstatus": "-",
            "pc_eventDate": start[:10],
            "pc_startTime": start[11:16],
            "pc_endTime": end[11:16],
            "pc_facility": "3",
            "pc_billing_location": "3",
        }
        url = (f"{self.profile.rest_base(self.base)}/patient/{pid}/appointment")
        status, data, _ = await self._request(
            "POST", url, payload=payload, secret=ctx.secret, fhir=False)
        rid = _id_from(data, {})
        if status >= 400 or not rid:
            self._raise(status, data)
        await self._remember(ctx, "shift", ctx.shift["id"], "Appointment", rid)
        return rid

    async def _ensure_people(self, ctx: EmrContext) -> dict:
        ids = {"Organization": await self._ensure_org(ctx)}
        if ctx.nurse:
            ids["Practitioner"] = await self._ensure_pract(ctx, ctx.nurse)
        if ctx.patient:
            ids["Patient"] = await self._ensure_patient(ctx)
        return ids

    async def _ensure(self, ctx: EmrContext, rtype: str, value: str,
                      resource: dict, rock_kind: str, rock_id: str) -> str:
        existing = ctx.links.get((rock_kind, str(rock_id), rtype))
        if existing:
            return existing
        can_cond = (self.profile.supports_conditional_create
                    and rtype not in self.profile.no_identifier_search)
        if not can_cond:
            found = await self._search_id(ctx, rtype, value)
            if found:
                await self._remember(ctx, rock_kind, rock_id, rtype, found)
                return found
        extra = {}
        if can_cond:
            extra["If-None-Exist"] = (
                f"identifier={quote(mapping.IDENT_SYSTEM, safe='')}|"
                f"{quote(str(value), safe='')}"
            )
        body = self.profile.before_create(dict(resource))
        status, data, headers = await self._request(
            "POST", rtype, payload=body, extra=extra, secret=ctx.secret)
        if status in (200, 201):
            rid = _id_from(data, headers)
            if not rid:
                rid = await self._search_id(ctx, rtype, value)
            if not rid:
                raise EmrTransientError(f"{rtype} create {status} had no id")
            await self._remember(ctx, rock_kind, rock_id, rtype, rid)
            if rtype == "Patient" and isinstance(data, dict) and data.get("pid"):
                await self._remember(ctx, rock_kind, rock_id, "PatientPid",
                                     str(data["pid"]))
            return rid
        if status in self.profile.conflict_statuses or status in (400, 412):
            rid = await self._search_id(ctx, rtype, value)
            if rid:
                await self._remember(ctx, rock_kind, rock_id, rtype, rid)
                return rid
        self._raise(status, data)

    async def _search_id(self, ctx: EmrContext, rtype: str, value: str) -> str | None:
        q = quote(f"{mapping.IDENT_SYSTEM}|{value}", safe="")
        status, data, _ = await self._request(
            "GET", f"{rtype}?identifier={q}", secret=ctx.secret)
        if status >= 500:
            raise EmrTransientError(f"search {rtype} {status}")
        if status >= 400 or not isinstance(data, dict):
            return None
        entries = data.get("entry") or []
        if not entries:
            return None
        return (entries[0].get("resource") or {}).get("id")

    async def _remember(self, ctx: EmrContext, rock_kind: str, rock_id: str,
                        rtype: str, rid: str) -> None:
        await db.upsert_emr_link(ctx.agency["id"], rock_kind, str(rock_id),
                                 rtype, str(rid), self.backend)
        ctx.links[(rock_kind, str(rock_id), rtype)] = str(rid)

    async def _skip(self, ctx: EmrContext, resource_type: str) -> None:
        await db.log_event(
            "emr", "emr_unsupported", agency_id=ctx.agency["id"],
            shift_id=(ctx.shift or {}).get("id"),
            payload={"resource": resource_type, "backend": self.backend})

    async def _update(self, ctx: EmrContext, rtype: str, rid: str,
                      mutate: Callable[[dict], None]) -> None:
        if rtype == "Appointment" and self.profile.rest_appointment:
            await self._skip(ctx, "Appointment.update")
            return
        resource = await self._get(ctx, rtype, rid)
        mutate(resource)
        if await self._put(ctx, resource) == "conflict":
            resource = await self._get(ctx, rtype, rid)
            mutate(resource)
            if await self._put(ctx, resource) == "conflict":
                raise EmrTransientError(f"{rtype}/{rid} version conflict twice")

    async def _get(self, ctx: EmrContext, rtype: str, rid: str) -> dict:
        status, data, _ = await self._request("GET", f"{rtype}/{rid}", secret=ctx.secret)
        if status == 404:
            raise EmrPermanentError(f"{rtype}/{rid} missing")
        if status >= 400:
            self._raise(status, data)
        return data

    async def _put(self, ctx: EmrContext, resource: dict) -> str | dict:
        rtype, rid = resource["resourceType"], resource["id"]
        vid = (resource.get("meta") or {}).get("versionId")
        extra = {"If-Match": f'W/"{vid}"'} if vid else {}
        status, data, _ = await self._request(
            "PUT", f"{rtype}/{rid}", payload=resource, extra=extra, secret=ctx.secret)
        if status in self.profile.conflict_statuses:
            return "conflict"
        if status >= 400:
            self._raise(status, data)
        return data

    # ---- transport ----

    async def _request(self, method: str, path: str, *, payload=None,
                       extra: dict | None = None, secret: str | None,
                       fhir: bool = True) -> tuple[int, Any, dict]:
        mime = "application/fhir+json" if fhir else "application/json"
        headers = {"Accept": mime, **await self.auth.headers(secret)}
        if extra:
            headers.update(extra)
        body = None
        if payload is not None:
            headers["Content-Type"] = mime
            body = json.dumps(payload).encode()
        url = path if path.startswith("http") else f"{self.base}/{path.lstrip('/')}"
        ssl = False if not self.profile.verify_tls else None
        try:
            async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
                async with session.request(method, url, headers=headers,
                                          data=body, ssl=ssl) as resp:
                    raw = await resp.read()
                    hdrs = {k: v for k, v in resp.headers.items()}
                    status = resp.status
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise EmrTransientError(str(exc)[:160]) from exc
        try:
            data = json.loads(raw.decode() or "null")
        except json.JSONDecodeError:
            data = {"_raw": raw[:200].decode(errors="replace")}
        if data is None:
            data = {}
        return status, data, hdrs

    def _raise(self, status: int, data: Any) -> None:
        msg = f"FHIR {status}: {_issue(data) or 'error'}"
        if status in (408, 429) or status >= 500:
            raise EmrTransientError(msg)
        raise EmrPermanentError(msg)


def _set_participant(appt: dict, reference: str, status: str) -> None:
    parts = appt.setdefault("participant", [])
    for part in parts:
        if (part.get("actor") or {}).get("reference") == reference:
            part["status"] = status
            return
    parts.append({"actor": {"reference": reference}, "status": status})


def _mark_callout(appt: dict, pract_id: str | None) -> None:
    appt["status"] = "pending"
    if pract_id:
        _set_participant(appt, f"Practitioner/{pract_id}", "declined")


def _mark_filled(appt: dict, pract_id: str) -> None:
    appt["status"] = "booked"
    _set_participant(appt, f"Practitioner/{pract_id}", "accepted")


def _mark_task_done(task: dict) -> None:
    task["status"] = "completed"
    task["businessStatus"] = {"text": "filled"}


def _mark_task_hold(task: dict) -> None:
    task["status"] = "on-hold"

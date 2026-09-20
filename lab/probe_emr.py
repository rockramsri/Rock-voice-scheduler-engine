"""Probe the local EMR lab. Prints a PHI-free capability report.

  python lab/probe_emr.py
"""

from __future__ import annotations

import json
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

HAPI = "http://localhost:8080/fhir"
MEDPLUM = "http://localhost:8103"
OPENEMR = "https://localhost:9300"
ROCK_SYS = "https://rockscheduler.dev/ids/probe"
TLS = ssl._create_unverified_context()  # OpenEMR lab cert is self-signed

NEEDED = ("Organization", "Practitioner", "PractitionerRole", "Patient",
          "Appointment", "Task", "Provenance", "Subscription")


def http(method: str, url: str, *, headers: dict | None = None, body: bytes | None = None,
         timeout: int = 20, context=None) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


def json_req(method: str, url: str, *, headers=None, payload=None, context=None,
             timeout=20) -> tuple[int, Any]:
    hdrs = dict(headers or {})
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        hdrs.setdefault("Content-Type", "application/fhir+json")
    hdrs.setdefault("Accept", "application/fhir+json")
    status, hdr, raw = http(method, url, headers=hdrs, body=body, timeout=timeout, context=context)
    try:
        data = json.loads(raw.decode() or "null")
    except json.JSONDecodeError:
        data = {"_raw": raw[:400].decode(errors="replace")}
    data = data if data is not None else {}
    if isinstance(data, dict):
        data["_headers"] = {k.lower(): v for k, v in hdr.items()}
    return status, data


def wait(url: str, *, timeout=180, context=None, ok=lambda s, b: s < 500) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            status, _, raw = http("GET", url, timeout=8, context=context)
            if ok(status, raw):
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def cap_table(metadata: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    rest = (metadata.get("rest") or [{}])[0]
    for res in rest.get("resource") or []:
        typ = res.get("type")
        if not typ:
            continue
        interactions = {i.get("code") for i in (res.get("interaction") or []) if i.get("code")}
        out[typ] = {
            "create": "create" in interactions,
            "update": "update" in interactions,
            "read": "read" in interactions,
            "search": "search-type" in interactions,
            "conditionalCreate": bool(res.get("conditionalCreate")),
        }
    return out


def try_conditional_create(base: str, headers: dict, rtype: str, identifier: str,
                           extra: dict | None = None, context=None) -> dict:
    resource = {"resourceType": rtype,
                "identifier": [{"system": ROCK_SYS, "value": identifier}]}
    if extra:
        resource.update(extra)
    status, data = json_req(
        "POST", f"{base}/{rtype}",
        headers={**headers, "If-None-Exist": f"identifier={ROCK_SYS}|{identifier}"},
        payload=resource, context=context)
    loc = (data.get("_headers") or {}).get("location", "")
    rid = data.get("id")
    if not rid and "/fhir" in loc:
        rid = loc.rstrip("/").split("/")[-1].split("/_history")[0]
    # replay
    status2, data2 = json_req(
        "POST", f"{base}/{rtype}",
        headers={**headers, "If-None-Exist": f"identifier={ROCK_SYS}|{identifier}"},
        payload=resource, context=context)
    rid2 = data2.get("id")
    loc2 = (data2.get("_headers") or {}).get("location", "")
    if not rid2 and loc2:
        rid2 = loc2.rstrip("/").split("/")[-1].split("/_history")[0]
    search_status, search = json_req(
        "GET", f"{base}/{rtype}?identifier={ROCK_SYS}|{identifier}",
        headers=headers, context=context)
    count = search.get("total") if isinstance(search, dict) else None
    if count is None and isinstance(search, dict):
        count = len(search.get("entry") or [])
    return {
        "first": status, "replay": status2,
        "id": rid, "replay_id": rid2,
        "same_id": bool(rid and rid == rid2),
        "search_total": count, "search_status": search_status,
    }


def try_write(base: str, headers: dict, resource: dict, context=None) -> dict:
    rtype = resource["resourceType"]
    status, data = json_req("POST", f"{base}/{rtype}", headers=headers,
                            payload=resource, context=context)
    issue = ""
    if isinstance(data, dict) and data.get("issue"):
        issue = str(data["issue"][0].get("diagnostics") or data["issue"][0].get("code") or "")[:120]
    elif status >= 400:
        issue = str(data.get("error") or data.get("message") or data.get("_raw") or "")[:120]
    rid = None
    if isinstance(data, dict):
        rid = data.get("id") or data.get("uuid")
        inner = data.get("data")
        if not rid and isinstance(inner, dict):
            rid = inner.get("id") or inner.get("uuid") or inner.get("pid")
    return {"status": status, "id": rid,
            "ok": 200 <= status < 300, "issue": issue}


def print_section(title: str) -> None:
    print(f"\n=== {title} ===")


def form_post(url: str, fields: dict, context=None) -> tuple[int, dict]:
    status, _, raw = http(
        "POST", url,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        body=urlencode(fields).encode(), context=context)
    try:
        data = json.loads(raw.decode() or "{}")
    except json.JSONDecodeError:
        data = {"_raw": raw[:400].decode(errors="replace")}
    return status, data if isinstance(data, dict) else {"_raw": data}


class HookCatcher:
    def __init__(self) -> None:
        self.hits: list[dict] = []
        self.httpd: HTTPServer | None = None
        self.thread: threading.Thread | None = None

    @classmethod
    def start(cls, port: int) -> "HookCatcher":
        c = cls()
        catcher = c

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n)
                catcher.hits.append({
                    "path": self.path,
                    "x_signature": self.headers.get("X-Signature"),
                    "x_medplum_interaction": self.headers.get("X-Medplum-Interaction"),
                    "header_keys": sorted(k.lower() for k in self.headers.keys()),
                    "body_len": len(body),
                    "body_resource": (json.loads(body).get("resourceType") if body else None),
                })
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, fmt, *args) -> None:
                return

        c.httpd = HTTPServer(("0.0.0.0", port), Handler)
        c.thread = threading.Thread(target=c.httpd.serve_forever, daemon=True)
        c.thread.start()
        return c

    def wait(self, seconds: float) -> dict:
        t0 = time.time()
        while time.time() - t0 < seconds:
            if self.hits:
                return {"delivered": True, **self.hits[0]}
            time.sleep(0.4)
        return {"delivered": False, "hits": len(self.hits)}

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()


def medplum_try_cc(client_id: str, secret: str) -> dict:
    status, tok = form_post(f"{MEDPLUM}/oauth2/token", {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": secret,
    })
    return {
        "ok": bool(tok.get("access_token")),
        "status": status,
        "expires_in": tok.get("expires_in"),
        "token": tok.get("access_token"),
        "error": (tok.get("error_description") or tok.get("error") or tok.get("issue") or "")[:160],
        "client_id": client_id,
    }


def medplum_client_credentials(auth: dict) -> dict:
    st, me = json_req("GET", f"{MEDPLUM}/auth/me",
                      headers={**auth, "Accept": "application/json"})
    proj = ((me.get("project") or {}).get("id"))
    print("auth/me project:", proj, (me.get("project") or {}).get("name"))
    if not proj:
        return {"ok": False, "source": "no_project"}
    status, app = json_req(
        "POST", f"{MEDPLUM}/admin/projects/{proj}/client",
        headers={**auth, "Content-Type": "application/json", "Accept": "application/json"},
        payload={"name": "Rock Lab Drainer"})
    print("admin/projects client:", status, app.get("id"), "secret", bool(app.get("secret")))
    if not (app.get("id") and app.get("secret")):
        return {"ok": False, "source": "admin_client_failed", "status": status}
    cc = medplum_try_cc(app["id"], app["secret"])
    cc["source"] = "admin_projects_client"
    print("  client_credentials:", {k: cc.get(k) for k in ("ok", "status", "expires_in", "error")})
    return cc


# ---------- HAPI ----------

def probe_hapi() -> dict:
    print_section("HAPI")
    ready = wait(f"{HAPI}/metadata")
    print(f"reachable: {ready}")
    if not ready:
        return {"ok": False, "error": "unreachable"}
    status, meta = json_req("GET", f"{HAPI}/metadata")
    caps = cap_table(meta)
    print(f"software: {(meta.get('software') or {}).get('name')} {(meta.get('software') or {}).get('version')}")
    print("needed resources:")
    for name in NEEDED:
        row = caps.get(name)
        print(f"  {name:18} {row or 'MISSING'}")
    hdrs = {"Content-Type": "application/fhir+json"}
    cond = try_conditional_create(HAPI, hdrs, "Organization", "org-hapi-1",
                                  extra={"name": "Rock Lab Org", "active": True})
    print("conditional create Organization:", cond)
    writes = {}
    writes["Practitioner"] = try_write(HAPI, hdrs, {
        "resourceType": "Practitioner", "active": True,
        "identifier": [{"system": ROCK_SYS, "value": "nurse-hapi-1"}],
        "name": [{"text": "Lab Nurse"}],
    })
    writes["Patient"] = try_write(HAPI, hdrs, {
        "resourceType": "Patient", "active": True,
        "identifier": [{"system": ROCK_SYS, "value": "pt-hapi-1"}],
        "name": [{"text": "Lab Patient"}],
    })
    prac_id = writes["Practitioner"].get("id")
    pat_id = writes["Patient"].get("id")
    writes["Appointment"] = try_write(HAPI, hdrs, {
        "resourceType": "Appointment", "status": "booked",
        "identifier": [{"system": ROCK_SYS, "value": "shift-hapi-1"}],
        "start": "2026-09-21T12:00:00Z", "end": "2026-09-21T20:00:00Z",
        "participant": (
            [{"actor": {"reference": f"Patient/{pat_id}"}, "status": "accepted"}] if pat_id else []
        ) + (
            [{"actor": {"reference": f"Practitioner/{prac_id}"}, "status": "accepted"}] if prac_id else []
        ),
    })
    appt_id = writes["Appointment"].get("id")
    writes["Task"] = try_write(HAPI, hdrs, {
        "resourceType": "Task", "status": "requested", "intent": "order",
        "identifier": [{"system": ROCK_SYS, "value": "task-hapi-1"}],
        "code": {"text": "backfill-shift"},
        **({"focus": {"reference": f"Appointment/{appt_id}"}} if appt_id else {}),
    })
    writes["Provenance"] = try_write(HAPI, hdrs, {
        "resourceType": "Provenance",
        "recorded": "2026-09-21T12:00:00Z",
        "target": [{"reference": f"Appointment/{appt_id}"}] if appt_id else [{"reference": "Appointment/0"}],
        "agent": [{"who": {"display": "Rock Scheduler"}}],
    })
    for k, v in writes.items():
        print(f"  write {k:18} status={v['status']} id={v['id']} issue={v['issue']!r}")
    etag = {}
    if appt_id:
        st, got = json_req("GET", f"{HAPI}/Appointment/{appt_id}", headers=hdrs)
        tag = (got.get("_headers") or {}).get("etag") or (got.get("meta") or {}).get("versionId")
        print(f"  GET Appointment etag={tag} status={st}")
        body = {k: v for k, v in got.items() if k != "_headers"}
        body["status"] = "pending"
        st_ok, _ = json_req(
            "PUT", f"{HAPI}/Appointment/{appt_id}",
            headers={**hdrs, "If-Match": f'W/"{got.get("meta", {}).get("versionId", "1")}"'},
            payload=body)
        st_412, err412 = json_req(
            "PUT", f"{HAPI}/Appointment/{appt_id}",
            headers={**hdrs, "If-Match": 'W/"1"'},
            payload=body)
        etag = {"fresh_if_match": st_ok, "stale_if_match": st_412,
                "stale_issue": str((err412.get("issue") or [{}])[0])[:120]}
        print("  If-Match:", etag)
    return {"ok": True, "caps": {k: caps.get(k) for k in NEEDED},
            "conditional": cond, "writes": writes, "if_match": etag}


# ---------- Medplum ----------

def medplum_login() -> str | None:
    status, data = json_req("POST", f"{MEDPLUM}/auth/login", payload={
        "email": "admin@example.com", "password": "medplum_admin",
        "codeChallengeMethod": "plain", "codeChallenge": "lab_challenge",
    }, headers={"Content-Type": "application/json", "Accept": "application/json"})
    if status >= 400 or not data.get("code"):
        print("default admin login failed:", status, str(data)[:200])
        return None
    status, tok = json_req("POST", f"{MEDPLUM}/oauth2/token",
                           headers={"Content-Type": "application/x-www-form-urlencoded",
                                    "Accept": "application/json"},
                           payload=None)
    # urllib json_req always json-encodes; token endpoint wants form. Do it raw.
    raw_status, _, raw = http(
        "POST", f"{MEDPLUM}/oauth2/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=f"grant_type=authorization_code&code={data['code']}&code_verifier=lab_challenge".encode())
    try:
        tok = json.loads(raw.decode())
    except json.JSONDecodeError:
        tok = {}
    print("admin token exchange:", raw_status, "has_access_token", bool(tok.get("access_token")))
    return tok.get("access_token")


def medplum_register() -> str | None:
    status, data = json_req("POST", f"{MEDPLUM}/auth/newuser", payload={
        "firstName": "Rock", "lastName": "Lab",
        "email": "rock-lab@example.com", "password": "RockLab_pass1!",
        "projectName": "Rock Lab", "recaptchaToken": "local",
    }, headers={"Content-Type": "application/json", "Accept": "application/json"})
    print("newuser:", status, str({k: data.get(k) for k in ("id", "code", "login", "issue", "message") if k in data or True})[:240])
    if data.get("code"):
        raw_status, _, raw = http(
            "POST", f"{MEDPLUM}/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=f"grant_type=authorization_code&code={data['code']}&code_verifier=".encode())
        tok = json.loads(raw.decode() or "{}")
        return tok.get("access_token")
    # maybe returns login that still needs /auth/login
    status, login = json_req("POST", f"{MEDPLUM}/auth/login", payload={
        "email": "rock-lab@example.com", "password": "RockLab_pass1!",
        "codeChallengeMethod": "plain", "codeChallenge": "lab_challenge",
    }, headers={"Content-Type": "application/json", "Accept": "application/json"})
    print("registered user login:", status, str(login)[:200])
    if not login.get("code"):
        return None
    raw_status, _, raw = http(
        "POST", f"{MEDPLUM}/oauth2/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=f"grant_type=authorization_code&code={login['code']}&code_verifier=lab_challenge".encode())
    tok = json.loads(raw.decode() or "{}")
    print("registered token:", raw_status, bool(tok.get("access_token")))
    return tok.get("access_token")


def probe_medplum() -> dict:
    print_section("Medplum")
    ready = wait(f"{MEDPLUM}/healthcheck", ok=lambda s, b: s == 200)
    print(f"healthcheck: {ready}")
    if not ready:
        return {"ok": False, "error": "unreachable"}
    token = medplum_login() or medplum_register()
    if not token:
        return {"ok": False, "error": "could not get token"}
    auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/fhir+json"}
    status, meta = json_req("GET", f"{MEDPLUM}/fhir/R4/metadata", headers=auth)
    caps = cap_table(meta)
    print(f"metadata: {status} software={(meta.get('software') or {}).get('name')}")
    for name in NEEDED:
        print(f"  {name:18} {caps.get(name) or 'MISSING'}")

    cc = medplum_client_credentials(auth)
    if cc.get("token"):
        auth = {"Authorization": f"Bearer {cc['token']}",
                "Content-Type": "application/fhir+json"}

    cond = try_conditional_create(f"{MEDPLUM}/fhir/R4", auth, "Organization", "org-med-1",
                                  extra={"name": "Rock Lab Org", "active": True})
    print("conditional create Organization:", cond)
    writes = {}
    writes["Practitioner"] = try_write(f"{MEDPLUM}/fhir/R4", auth, {
        "resourceType": "Practitioner", "active": True,
        "identifier": [{"system": ROCK_SYS, "value": "nurse-med-1"}],
        "name": [{"text": "Lab Nurse"}],
    })
    writes["Patient"] = try_write(f"{MEDPLUM}/fhir/R4", auth, {
        "resourceType": "Patient", "active": True,
        "identifier": [{"system": ROCK_SYS, "value": "pt-med-1"}],
        "name": [{"text": "Lab Patient"}],
    })
    writes["Appointment"] = try_write(f"{MEDPLUM}/fhir/R4", auth, {
        "resourceType": "Appointment", "status": "booked",
        "identifier": [{"system": ROCK_SYS, "value": "shift-med-1"}],
        "start": "2026-09-21T12:00:00Z", "end": "2026-09-21T20:00:00Z",
        "participant": [{"status": "accepted", "actor": {"display": "Lab Nurse"}}],
    })
    writes["Task"] = try_write(f"{MEDPLUM}/fhir/R4", auth, {
        "resourceType": "Task", "status": "requested", "intent": "order",
        "identifier": [{"system": ROCK_SYS, "value": "task-med-1"}],
        "code": {"text": "backfill-shift"},
    })
    writes["Provenance"] = try_write(f"{MEDPLUM}/fhir/R4", auth, {
        "resourceType": "Provenance",
        "recorded": "2026-09-21T12:00:00Z",
        "target": [{"reference": f"Appointment/{writes['Appointment'].get('id')}"}]
        if writes["Appointment"].get("id") else [{"display": "Appointment"}],
        "agent": [{"who": {"display": "Rock Scheduler"}}],
    })
    hook = HookCatcher.start(8765)
    writes["Subscription"] = try_write(f"{MEDPLUM}/fhir/R4", auth, {
        "resourceType": "Subscription", "status": "active",
        "reason": "lab probe", "criteria": "Practitioner",
        "channel": {"type": "rest-hook",
                    "endpoint": "http://host.docker.internal:8765/emr/medplum/hook"},
        "extension": [{
            "url": "https://www.medplum.com/fhir/StructureDefinition/subscription-secret",
            "valueString": "lab-secret",
        }],
    })
    ping = try_write(f"{MEDPLUM}/fhir/R4", auth, {
        "resourceType": "Practitioner", "active": True,
        "identifier": [{"system": ROCK_SYS, "value": "nurse-med-hook-1"}],
        "name": [{"text": "Hook Nurse"}],
    })
    print("  hook ping Practitioner:", ping)
    delivered = hook.wait(12)
    print("  subscription delivery:", delivered)
    hook.stop()
    for k, v in writes.items():
        print(f"  write {k:18} status={v['status']} id={v['id']} issue={v['issue']!r}")
    return {"ok": True, "caps": {k: caps.get(k) for k in NEEDED},
            "client_credentials": {k: cc.get(k) for k in ("ok", "status", "expires_in", "source")},
            "conditional": cond, "writes": writes, "subscription_delivery": delivered}


# ---------- OpenEMR ----------

OEMR_SCOPES = (
    "openid offline_access api:oemr api:fhir "
    "user/Patient.cruds user/Practitioner.cruds user/Organization.cruds "
    "user/Patient.read user/Patient.write user/Practitioner.read user/Practitioner.write "
    "user/Organization.read user/Organization.write "
    "user/patient.read user/patient.write user/patient.crus user/patient.cruds user/patient.s "
    "user/appointment.read user/appointment.write user/appointment.cruds "
    "user/facility.read user/facility.write user/facility.crus "
    "user/practitioner.read user/practitioner.write user/practitioner.crus"
)
OEMR_SCOPES_V1 = (
    "openid offline_access api:oemr api:fhir "
    "user/Patient.read user/Patient.write user/Practitioner.read user/Practitioner.write "
    "user/Organization.read user/Organization.write"
)


def enable_openemr_client(client_id: str) -> str:
    sql = (
        "UPDATE oauth_clients SET is_enabled=1 "
        f"WHERE client_id='{client_id}'; "
        "SELECT client_id, is_enabled FROM oauth_clients;"
    )
    p = subprocess.run(
        ["docker", "compose", "-f", "lab/docker-compose.emr.yml", "exec", "-T",
         "openemr-db", "mariadb", "-uroot", "-proot", "openemr", "-e", sql],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[1]))
    print("  enable client sql rc=", p.returncode,
          (p.stdout or p.stderr or "")[:300].replace("\n", " | "))
    return p.stdout


def openemr_register_and_token() -> tuple[dict, str | None]:
    st, smart = json_req(
        "GET", f"{OPENEMR}/oauth2/default/.well-known/smart-configuration",
        headers={"Accept": "application/json"}, context=TLS)
    scopes = smart.get("scopes_supported") if isinstance(smart, dict) else None
    print("smart-configuration:", st,
          "grant_types", (smart.get("grant_types_supported") if isinstance(smart, dict) else None),
          "scopes_n", len(scopes or []))
    if scopes:
        interesting = [s for s in scopes if any(x in s for x in
                      ("Patient", "Practitioner", "Organization", "Appointment",
                       "Task", "Provenance", "api:fhir", "api:oemr", "system/"))]
        print("  interesting scopes:", interesting[:40])

    client: dict = {}
    for label, scope in (("v2", OEMR_SCOPES), ("v1", OEMR_SCOPES_V1)):
        status, client = json_req(
            "POST", f"{OPENEMR}/oauth2/default/registration",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            payload={
                "application_type": "private",
                "redirect_uris": ["https://localhost:9300/swagger/oauth2-redirect.html"],
                "client_name": f"Rock Lab {label}",
                "token_endpoint_auth_method": "client_secret_post",
                "scope": scope,
                "grant_types": ["password", "refresh_token", "authorization_code"],
                "response_types": ["code"],
            },
            context=TLS)
        print(f"oauth registration {label}:", status,
              "client_id" if client.get("client_id") else str(client)[:240])
        if client.get("client_id"):
            break
    if not client.get("client_id"):
        return client, None

    enable_openemr_client(client["client_id"])
    token = None
    for extra in (
        {"user_role": "users"},
        {"user_role": "api"},
        {},
    ):
        fields = {
            "grant_type": "password",
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "username": "admin",
            "password": "pass",
            "scope": client.get("scope") or OEMR_SCOPES,
            **extra,
        }
        raw_status, tok = form_post(f"{OPENEMR}/oauth2/default/token", fields, context=TLS)
        print("password grant", extra, raw_status,
              "token" if tok.get("access_token") else str(tok)[:240])
        token = tok.get("access_token")
        if token:
            break
    return client, token


def probe_openemr() -> dict:
    print_section("OpenEMR")
    ready = wait(f"{OPENEMR}/interface/login/login.php", timeout=300, context=TLS,
                 ok=lambda s, b: s in (200, 302, 301))
    print(f"login page: {ready}")
    if not ready:
        return {"ok": False, "error": "unreachable"}
    client, token = openemr_register_and_token()
    if not token:
        # metadata is sometimes public
        status, meta = json_req("GET", f"{OPENEMR}/apis/default/fhir/metadata", context=TLS)
        print("anonymous metadata:", status)
        caps = cap_table(meta) if status < 400 else {}
        for name in NEEDED:
            print(f"  {name:18} {caps.get(name) or 'MISSING'}")
        return {"ok": False, "error": "no token", "caps": {k: caps.get(k) for k in NEEDED},
                "registration": bool(client.get("client_id"))}

    auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/fhir+json"}
    status, meta = json_req("GET", f"{OPENEMR}/apis/default/fhir/metadata",
                            headers=auth, context=TLS)
    caps = cap_table(meta)
    print(f"metadata: {status}")
    for name in NEEDED:
        print(f"  {name:18} {caps.get(name) or 'MISSING'}")
    base = f"{OPENEMR}/apis/default/fhir"
    cond = try_conditional_create(base, auth, "Organization", "org-oemr-1",
                                  extra={"name": "Rock Lab Org", "active": True}, context=TLS)
    print("conditional create Organization:", cond)
    writes = {}
    for rtype, extra in (
        ("Organization", {"name": "Rock Lab Org", "active": True,
                          "identifier": [{"system": "http://hl7.org/fhir/sid/us-npi", "value": "1234567893"},
                                         {"system": ROCK_SYS, "value": "org-oemr-1"}]}),
        ("Practitioner", {"active": True,
                          "identifier": [{"system": "http://hl7.org/fhir/sid/us-npi", "value": "9941339108"}],
                          "name": [{"use": "official", "family": "Nurse", "given": ["Lab"]}]}),
        ("Patient", {"active": True, "gender": "female", "birthDate": "1980-01-15",
                     "name": [{"use": "official", "family": "Patient", "given": ["Lab"]}]}),
        ("Appointment", {"status": "booked", "start": "2026-09-21T12:00:00Z",
                         "end": "2026-09-21T20:00:00Z",
                         "participant": [{"status": "accepted", "actor": {"display": "Lab Nurse"}}]}),
        ("Task", {"status": "requested", "intent": "order", "code": {"text": "backfill-shift"}}),
        ("Provenance", {"recorded": "2026-09-21T12:00:00Z",
                        "target": [{"display": "Appointment"}],
                        "agent": [{"who": {"display": "Rock Scheduler"}}]}),
    ):
        resource = {"resourceType": rtype, **extra}
        if "identifier" not in resource:
            resource["identifier"] = [{"system": ROCK_SYS, "value": f"{rtype.lower()}-oemr-1"}]
        writes[rtype] = try_write(base, auth, resource, context=TLS)
        print(f"  write {rtype:18} status={writes[rtype]['status']} "
              f"id={writes[rtype]['id']} issue={writes[rtype]['issue']!r}")

    # Standard REST appointment probe
    rest: dict[str, Any] = {}
    pid = None
    rest_status, rest_body = json_req(
        "GET", f"{OPENEMR}/apis/default/api/patient",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        context=TLS)
    rest["GET /api/patient"] = rest_status
    rows = (rest_body.get("data") or []) if isinstance(rest_body, dict) else []
    print("standard REST GET /api/patient:", rest_status, f"count={len(rows)}")
    if rows:
        pid = rows[0].get("id") or rows[0].get("pid")
    if not pid:
        st, created = json_req(
            "POST", f"{OPENEMR}/apis/default/api/patient",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "Accept": "application/json"},
            payload={"fname": "Rest", "lname": "Appt", "sex": "Female", "DOB": "1980-01-15"},
            context=TLS)
        inner = created.get("data") if isinstance(created.get("data"), dict) else created
        pid = inner.get("pid") if isinstance(inner, dict) else None
        rest["POST /api/patient"] = {"status": st, "pid": pid}
        print("  REST POST patient:", rest["POST /api/patient"])
    if pid:
        st, body = json_req(
            "POST", f"{OPENEMR}/apis/default/api/patient/{pid}/appointment",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "Accept": "application/json"},
            payload={
                "pc_catid": "5",
                "pc_title": "Office Visit",
                "pc_duration": "60",
                "pc_hometext": "lab probe",
                "pc_apptstatus": "-",
                "pc_eventDate": "2026-09-21",
                "pc_startTime": "12:00",
                "pc_endTime": "13:00",
                "pc_facility": "3",
                "pc_billing_location": "3",
            },
            context=TLS)
        rest["POST appointment"] = {
            "status": st,
            "ok": 200 <= st < 300 and bool(body.get("id")),
            "id": body.get("id"),
            "issue": str(body.get("message") or body.get("error") or "")[:160],
        }
        print("  REST POST appointment:", rest["POST appointment"])
        st, body = json_req(
            "GET", f"{OPENEMR}/apis/default/api/appointment",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            context=TLS)
        rest["GET /api/appointment"] = st
        print("  REST GET /api/appointment:", st)
    return {"ok": True, "caps": {k: caps.get(k) for k in NEEDED},
            "conditional": cond, "writes": writes, "rest": rest}


def main() -> int:
    results = {
        "hapi": probe_hapi(),
        "medplum": probe_medplum(),
        "openemr": probe_openemr(),
    }
    print_section("SUMMARY")
    print(json.dumps({k: {"ok": v.get("ok"), "error": v.get("error"),
                          "writes": {rk: rv.get("status") for rk, rv in (v.get("writes") or {}).items()},
                          "conditional": (v.get("conditional") or {}).get("first"),
                          "client_credentials": (v.get("client_credentials") or {}).get("ok")}
                      for k, v in results.items()}, indent=2))
    out = Path(__file__).resolve().parent / "probe-report.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Local EMR lab

HAPI is the CI target. Medplum is the M3 contract target when
`EMR_TEST_BACKENDS=mock,hapi,medplum`. OpenEMR stays in this compose
file for M5.

```
make lab-up
python lab/probe_emr.py
make lab-seed
python -m data.import_fhir --agency <id> --patients
make lab-down
```

`lab/sample_bundle.json` is a tiny Practitioner+Patient collection. A
full Synthea download POSTs the same way via `python lab/load_bundle.py`.

Host ports: HAPI `8080`, Medplum `8103`/`3000`, OpenEMR `8300`/`9300`.
Postgres and Redis stay unpublished.

## Medplum first run

The image already has `admin@example.com` / `medplum_admin`. Do not
`POST /fhir/R4/ClientApplication` — that 201 is inert (no membership).
Mint a working client:

```
# after admin login + token exchange
curl -s http://localhost:8103/admin/projects/$PROJECT_ID/client \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Rock Lab Drainer"}'
```

Put the returned `id` on `agencies.emr_client_id` and the `secret` in an
env var whose NAME is `agencies.emr_secret_ref`. Auth is
`client_credentials` at `http://localhost:8103/oauth2/token`.

Medplum's Provenance schema has no `identifier` field — the driver
strips it and replays via `emr_links`, same as HAPI.

Sync-in: set `agencies.emr_sync_mode` to `push` and point a Subscription
at `POST /emr/medplum/hook?agency=<id>` with `MEDPLUM_HOOK_SECRET` in
the subscription-secret extension. HAPI uses `pull` (`_lastUpdated` +
refresh of linked Practitioner/Patient rows).

## OpenEMR (M5)

Self-signed cert on `:9300`. Password grant is lab-only (`admin` / `pass`).
Registered OAuth clients start disabled — `UPDATE oauth_clients SET
is_enabled=1`. FHIR writes work for Organization / Practitioner /
Patient only (official name + NPI required). Appointments go through
`POST /apis/default/api/patient/{pid}/appointment`. Task and Provenance
are skipped with an `emr_unsupported` event.

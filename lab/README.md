# Local EMR lab

Untracked until M2. Bring up HAPI (CI target); Medplum and OpenEMR stay in
the same compose file for later milestones.

```
docker compose -f lab/docker-compose.emr.yml up -d
python lab/probe_emr.py
docker compose -f lab/docker-compose.emr.yml down -v
```

Host ports: HAPI `8080`, Medplum `8103`/`3000`, OpenEMR `8300`/`9300`.
Postgres and Redis stay unpublished.

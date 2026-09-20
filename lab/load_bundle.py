"""POST a FHIR Bundle's entries to a server (HAPI by default).

  python lab/load_bundle.py lab/sample_bundle.json
  python lab/load_bundle.py path.json --base http://localhost:8080/fhir

For a full Synthea download, point this at each transaction JSON the same way.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path


def post(base: str, resource: dict) -> tuple[int, str]:
    rtype = resource["resourceType"]
    rid = resource.get("id")
    url = f"{base.rstrip('/')}/{rtype}"
    req = urllib.request.Request(
        url, data=json.dumps(resource).encode(), method="POST",
        headers={"Content-Type": "application/fhir+json",
                 "Accept": "application/fhir+json"})
    if rid:
        req.add_header("If-None-Exist", f"_id={rid}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read() or b"{}")
            return resp.status, str(body.get("id") or rid or "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:120].decode(errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", help="FHIR Bundle JSON")
    parser.add_argument("--base", default="http://localhost:8080/fhir")
    args = parser.parse_args()
    bundle = json.loads(Path(args.bundle).read_text())
    entries = bundle.get("entry") or [{"resource": bundle}]
    for entry in entries:
        resource = entry.get("resource")
        if not resource:
            continue
        status, rid = post(args.base, resource)
        print(f"  {resource.get('resourceType'):18} {status} {rid}")


if __name__ == "__main__":
    main()

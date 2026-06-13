#!/usr/bin/env python3
"""
Verifiable-serial registry. Each protected master carries a serial (in the
invisible watermark and/or a visible code). The registry maps serial -> owner +
the sha256 of the authentic master. Validation logic:

  - serial present in registry  -> authentic / licensed copy
  - serial recovered but NOT in registry, or no serial at all -> the copy was
    regenerated/scrubbed (an AI 'repair' draws a NEW code that never validates)
    = provable counterfeit.

Stored as a flat JSON file so it survives restarts; in production point
REGISTRY_PATH at a persistent volume.
"""
import json
import os

PATH = os.environ.get("REGISTRY_PATH",
                      os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "static", "registry.json"))


def _load():
    try:
        with open(PATH) as f:
            return json.load(f)
    except Exception:
        return {"serials": {}}


def _save(d):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w") as f:
        json.dump(d, f, indent=2)


def register(serial, owner, sha256="", notes=""):
    d = _load()
    d["serials"][serial] = {"owner": owner, "sha256": sha256, "notes": notes}
    _save(d)
    return d["serials"][serial]


def validate(serial):
    if not serial:
        return {"status": "none", "message": "No serial found in the file."}
    rec = _load()["serials"].get(serial)
    if rec:
        return {"status": "valid", "serial": serial, "owner": rec["owner"],
                "message": f"Serial {serial} is registered to {rec['owner']} — authentic / licensed."}
    return {"status": "invalid", "serial": serial,
            "message": f"Serial {serial} is not in the registry — unrecognized or fabricated copy."}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "register":
        print(register(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "demo owner"))
    elif len(sys.argv) > 2 and sys.argv[1] == "validate":
        print(validate(sys.argv[2]))
    else:
        print(json.dumps(_load(), indent=2))

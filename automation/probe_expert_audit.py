#!/usr/bin/env python3
"""Probe expert audit/approval APIs for project 2078."""
import json
import re
from pathlib import Path

import requests

from zjgj_client import ZjgjClient, ZjgjApiError

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
PROJECT_ID = 2078
SECTION_ID = 1906

pm = ZjgjClient(BASE, token=PM, verify_ssl=False)


def fetch_js_apis() -> tuple[set[str], set[str]]:
    manage: set[str] = set()
    expert: set[str] = set()
    cache = Path(__file__).parent / "_js_cache"
    chunks = [
        "projectManager-de10c0b1.js",
        "index-0e91e2d9.js",
        "main-868a39d1.js",
        "form-5471d1fb.js",
    ]
    for chunk in chunks:
        path = cache / chunk
        if not path.exists():
            try:
                text = requests.get(f"{BASE}/static/js/{chunk}", verify=False, timeout=20).text
                path.write_text(text, encoding="utf-8")
            except Exception as exc:
                print(f"fetch {chunk} failed: {exc}")
                continue
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
        manage.update(re.findall(r"api/manage/[a-zA-Z0-9_]+", text))
        expert.update(re.findall(r"api/expert/[a-zA-Z0-9_]+", text))
    return manage, expert


def probe_endpoint(method: str, path: str, params: dict | None = None, data: dict | None = None) -> dict:
    try:
        resp = pm.request(method, path, params=params, data=data, require_auth=True)
        return {"ok": True, "code": resp.get("code"), "msg": resp.get("msg"), "data_keys": list((resp.get("data") or {}).keys()) if isinstance(resp.get("data"), dict) else type(resp.get("data")).__name__}
    except ZjgjApiError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}


def main() -> None:
    manage, expert = fetch_js_apis()
    print("=== JS manage APIs ===")
    for a in sorted(manage):
        print(" ", a)
    print("=== JS expert APIs ===")
    for a in sorted(expert):
        print(" ", a)

    invite = pm.get_manage_invite_info(PROJECT_ID, SECTION_ID)
    print("\n=== inviteInfo (before audit) ===")
    print(json.dumps(invite, ensure_ascii=False, indent=2))

    # Candidate audit endpoints from manage + expert APIs
    candidates = sorted(
        set(manage) | set(expert),
        key=lambda x: (0 if any(k in x.lower() for k in ("audit", "check", "approve", "confirm", "invite", "expert")) else 1, x),
    )
    audit_like = [c for c in candidates if any(k in c.lower() for k in ("audit", "check", "approve", "invite", "expert", "confirm"))]
    print("\n=== Probe GET audit-like endpoints ===")
    for path in audit_like:
        if path.endswith(("addExpert", "confirm", "sign")):
            continue
        r = probe_endpoint("GET", path, {"project_id": PROJECT_ID, "section_id": SECTION_ID})
        if r.get("ok"):
            print(f"GET {path}: {r}")

    # Known register audit pattern
    register_paths = [p for p in manage if "register" in p.lower() or "audit" in p.lower() or "check" in p.lower()]
    print("\n=== Register/audit manage paths ===", register_paths)

    post_candidates = [
        ("POST", "api/manage/checkExpert", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/manage/expertAudit", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/manage/auditExpert", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/manage/expertCheck", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/manage/checkInvite", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/manage/inviteAudit", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/manage/auditInvite", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/manage/passExpert", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
        ("POST", "api/manage/approveExpert", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/expert/audit", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
    ]
    print("\n=== Probe POST guessed audit endpoints (dry - only if 404 vs other) ===")
    for method, path, data in post_candidates:
        r = probe_endpoint(method, path, data=data)
        print(f"{method} {path}: {r}")


if __name__ == "__main__":
    main()

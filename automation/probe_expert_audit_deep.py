#!/usr/bin/env python3
"""Deep probe for expert audit API on project 2078."""
import json
import re
from pathlib import Path

import requests

from zjgj_client import ZjgjClient, ZjgjApiError

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
EXPERTS = [
    ("专家-测试peng", "2dc7d42b334a80f5a9f468804b4c804e"),
    ("专家-数据�?, "1961087d90c565e4620b9a98b69a8b91"),
]
PROJECT_ID = 2078
SECTION_ID = 1906
CACHE = Path(__file__).parent / "_js_cache"


def download_manage_chunks() -> set[str]:
    manage: set[str] = set()
    expert: set[str] = set()
    publicity: set[str] = set()
    html = requests.get(BASE, verify=False, timeout=30).text
    chunks = sorted(set(re.findall(r"static/js/[^\"']+\.js", html)))
    for chunk in chunks:
        name = chunk.split("/")[-1]
        path = CACHE / name
        if not path.exists():
            try:
                text = requests.get(f"{BASE}/{chunk}", verify=False, timeout=20).text
                path.write_text(text, encoding="utf-8")
            except Exception:
                continue
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
        manage.update(re.findall(r"bidding/manage/[a-zA-Z0-9_]+", text))
        expert.update(re.findall(r"bidding/expert/[a-zA-Z0-9_]+", text))
        publicity.update(re.findall(r"bidding/publicity/[a-zA-Z0-9_]+", text))
        manage.update(re.findall(r"api/manage/[a-zA-Z0-9_]+", text))
        expert.update(re.findall(r"api/expert/[a-zA-Z0-9_]+", text))
        publicity.update(re.findall(r"api/publicity/[a-zA-Z0-9_]+", text))
    print("bidding/manage:", *sorted(manage), sep="\n  ")
    print("bidding/expert:", *sorted(expert), sep="\n  ")
    audit_pub = [p for p in sorted(publicity) if any(k in p.lower() for k in ("audit", "expert", "invite", "register", "check"))]
    print("publicity audit-like:", *audit_pub, sep="\n  ")
    return manage | expert | publicity


def try_call(client: ZjgjClient, method: str, path: str, **kwargs) -> dict:
    try:
        resp = client.request(method, path, require_auth=True, **kwargs)
        return {"ok": True, "code": resp.get("code"), "msg": resp.get("msg"), "data": resp.get("data")}
    except ZjgjApiError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}


def main() -> None:
    download_manage_chunks()
    pm = ZjgjClient(BASE, token=PM, verify_ssl=False)

    invite = pm.get_manage_invite_info(PROJECT_ID, SECTION_ID)
    print("\n=== inviteInfo ===")
    print(json.dumps(invite, ensure_ascii=False, indent=2))

    # Expert-side views
    for name, token in EXPERTS:
        ec = ZjgjClient(BASE, token=token, verify_ssl=False)
        print(f"\n=== {name} expert list ===")
        for status in (0, 1, 2, 3, 4, 5, 6):
            r = try_call(ec, "GET", "api/expert/list", params={"page": 1, "limit": 20, "status": status})
            items = ((r.get("data") or {}).get("list") or []) if r.get("ok") else []
            hits = [i for i in items if int(i.get("project_id", -1)) == PROJECT_ID]
            if hits:
                print(f"status={status}:", json.dumps(hits, ensure_ascii=False, indent=2))

        print(f"\n=== {name} expert myList ===")
        r = try_call(ec, "GET", "api/expert/myList", params={"page": 1, "limit": 50})
        if r.get("ok"):
            hits = [i for i in ((r.get("data") or {}).get("list") or []) if int(i.get("project_id", -1)) == PROJECT_ID]
            if hits:
                print(json.dumps(hits, ensure_ascii=False, indent=2))

    # PM list endpoints
    for path, params in [
        ("api/manage/getList", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "page": 1, "limit": 50}),
        ("api/publicity/getRegisterListNew", {"project_id": PROJECT_ID, "page": 1, "limit": 50}),
    ]:
        print(f"\n=== GET {path} ===")
        print(json.dumps(try_call(pm, "GET", path, params=params), ensure_ascii=False)[:2000])

    # Brute-force audit-like publicity/manage POST endpoints
    user_ids = [153, 154]
    invite_id = 93
    guesses = [
        ("POST", "api/publicity/expertAudit", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/publicity/inviteAudit", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/publicity/expertInviteAudit", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/manage/expertAudit", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/manage/inviteAudit", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/manage/checkExpert", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1}),
        ("POST", "api/manage/audit", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "type": "expert", "status": 1}),
        ("POST", "api/manage/addExpert", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1, "id": invite_id}),
    ]
    for uid in user_ids:
        guesses.extend([
            ("POST", "api/manage/expertAudit", {"id": uid, "status": 1}),
            ("POST", "api/manage/checkExpert", {"id": uid, "status": 1}),
            ("POST", "api/manage/inviteAudit", {"id": uid, "status": 1, "invite_id": invite_id}),
            ("POST", "api/publicity/expertAudit", {"id": uid, "status": 1, "project_id": PROJECT_ID}),
            ("POST", "api/manage/passExpert", {"id": uid, "status": 1}),
            ("POST", "api/manage/confirmExpert", {"id": uid, "status": 1}),
        ])

    print("\n=== POST guesses (non-404 highlighted) ===")
    for method, path, data in guesses:
        r = try_call(pm, method, path, data=data)
        err = r.get("error", "")
        if "404" not in err:
            print(f"{method} {path} {data} -> {r}")


if __name__ == "__main__":
    main()

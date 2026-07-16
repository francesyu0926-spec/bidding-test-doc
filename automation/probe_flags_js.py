#!/usr/bin/env python3
import json
import re
from pathlib import Path

import requests

from zjgj_client import ZjgjClient

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
pm = ZjgjClient(BASE, token=PM, verify_ssl=False)

for pid in [2060, 1983, 2031]:
    info = pm.request("GET", "api/publicity/info", params={"project_id": pid}).get("data") or {}
    sec = (info.get("sections") or [{}])[0]
    slim = {k: info.get(k) for k in ["id", "start_time", "state", "status", "is_allow", "is_login", "is_regsiter", "is_min", "is_audit", "create_time"]}
    slim["section_state"] = sec.get("state")
    print(json.dumps(slim, ensure_ascii=False))

cache = Path(__file__).parent / "_js_cache"
for chunk in ["projectManager-de10c0b1.js", "index-0e91e2d9.js", "main-868a39d1.js"]:
    path = cache / chunk
    if not path.exists():
        try:
            text = requests.get(f"{BASE}/static/js/{chunk}", verify=False, timeout=20).text
            path.write_text(text, encoding="utf-8")
        except Exception as exc:
            print(chunk, "fetch failed", exc)
            continue
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
    apis = sorted(set(re.findall(r"api/manage/[a-zA-Z0-9_]+", text)))
    pub = sorted(set(re.findall(r"api/publicity/[a-zA-Z0-9_]+", text)))
    if apis:
        print(f"\n{chunk} manage APIs:")
        for a in apis:
            print(" ", a)
    interesting = [a for a in pub if any(x in a.lower() for x in ("review", "open", "change", "create", "save"))]
    if interesting:
        print(f"{chunk} publicity APIs:", interesting)

#!/usr/bin/env python3
import re
import requests

BASE = "https://www.bidding.shanxiguandian.com"
html = requests.get(BASE, verify=False, timeout=30).text
chunks = sorted(set(re.findall(r"static/js/[^\"']+\.js", html)))
manage: set[str] = set()
expert: set[str] = set()
publicity: set[str] = set()
for chunk in chunks:
    try:
        text = requests.get(f"{BASE}/{chunk}", verify=False, timeout=15).text
    except Exception:
        continue
    manage.update(re.findall(r"api/manage/[a-zA-Z0-9_]+", text))
    expert.update(re.findall(r"api/expert/[a-zA-Z0-9_]+", text))
    publicity.update(re.findall(r"api/publicity/[a-zA-Z0-9_]+", text))

print("manage:", *sorted(manage), sep="\n  ")
print("expert:", *sorted(expert), sep="\n  ")
print("publicity audit-like:", *[p for p in sorted(publicity) if any(k in p.lower() for k in ("audit", "expert", "invite", "register", "check"))], sep="\n  ")

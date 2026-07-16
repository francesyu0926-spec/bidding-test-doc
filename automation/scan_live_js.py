#!/usr/bin/env python3
import re
import requests
from pathlib import Path

BASE = "https://www.bidding.shanxiguandian.com"
CACHE = Path(__file__).parent / "_js_cache"

# Fetch index.html directly
html = requests.get(BASE + "/", verify=False, timeout=30).text
print("html len", len(html), "has static/js", "static/js" in html)
chunks = sorted(set(re.findall(r"static/js/[^\"']+\.js", html)))
print("chunks from index", len(chunks))

apis: set[str] = set()
bidding: set[str] = set()
for chunk in chunks:
    name = chunk.split("/")[-1]
    path = CACHE / name
    url = f"{BASE}/{chunk}"
    try:
        text = requests.get(url, verify=False, timeout=20).text
        if len(text) > 100:
            path.write_text(text, encoding="utf-8")
    except Exception as exc:
        print("fail", name, exc)
        continue
    apis.update(re.findall(r"api/[a-zA-Z0-9_/]+", text))
    bidding.update(re.findall(r"bidding/[a-zA-Z0-9_/]+", text))

expertish = sorted(a for a in apis if any(k in a.lower() for k in ("expert", "invite", "audit", "check", "confirm", "sign")))
manageish = sorted(a for a in apis if "manage" in a.lower())
print("\nexpert/invite/audit apis:")
for a in expertish:
    print(" ", a)
print("\nall manage apis:")
for a in manageish:
    print(" ", a)

# Search context around 审核 in downloaded chunks
for chunk in chunks:
    name = chunk.split("/")[-1]
    path = CACHE / name
    if not path.exists():
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "审核" in text or "inviteAudit" in text or "expertAudit" in text or "checkExpert" in text:
        print("\n=== context in", name, "===")
        for m in re.finditer(r".{0,60}(审核|inviteAudit|expertAudit|checkExpert|registerAudit|addExpert|inviteInfo).{0,80}", text):
            print(m.group(0)[:180])

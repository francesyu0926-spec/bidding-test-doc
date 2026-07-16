#!/usr/bin/env python3
import re
from pathlib import Path

cache = Path(__file__).parent / "_js_cache"
apis: set[str] = set()
routes: set[str] = set()
hits: list[tuple[str, str]] = []
for p in cache.glob("gdbid_*.js"):
    if "vendor" in p.name:
        continue
    t = p.read_text(encoding="utf-8", errors="ignore")
    apis.update(re.findall(r"api/[a-zA-Z0-9_/]+", t))
    apis.update(re.findall(r"bidding/[a-zA-Z0-9_/]+", t))
    routes.update(re.findall(r'path:"(/[^"]+)"', t))
    for kw in [
        "addExpert", "inviteInfo", "inviteExpert", "searchExpert", "expertAudit",
        "checkExpert", "registerAudit", "confirm", "sign", "审核", "通过", "extract",
    ]:
        if kw in t:
            hits.append((p.name, kw))

print("apis", len(apis))
for a in sorted(a for a in apis if any(x in a for x in ["manage", "expert", "invite", "audit", "extract", "register"])):
    print(a)
print("\nroutes:")
for r in sorted(routes):
    if any(x in r.lower() for x in ["expert", "manage", "invite", "audit", "extract", "register", "review"]):
        print(r)
print("\nhits:")
for h in hits:
    print(h)

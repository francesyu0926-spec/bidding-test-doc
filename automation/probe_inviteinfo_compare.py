#!/usr/bin/env python3
import json

from zjgj_client import ZjgjClient

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
pm = ZjgjClient(BASE, token=PM, verify_ssl=False)

listing = pm.list_manage_projects(page=1, limit=50, status=3)
items = (listing.get("data") or {}).get("list") or []
print("opened projects", len(items))
for item in items[:5]:
    pid = item.get("project_id")
    sid = item.get("section_id")
    invite = pm.get_manage_invite_info(pid, sid)
    info = (invite.get("data") or {}).get("info") or {}
    users = info.get("users") or []
    print(f"\nproject {pid} invite batch {info.get('id')} users={len(users)}")
    for u in users:
        slim = {k: u.get(k) for k in u if k not in {"user", "apply"}}
        print(" ", json.dumps(slim, ensure_ascii=False))

# Also inspect 2078 full user objects for hidden status keys
invite2078 = pm.get_manage_invite_info(2078, 1906)
users = ((invite2078.get("data") or {}).get("info") or {}).get("users") or []
print("\n2078 full user keys:", [sorted(u.keys()) for u in users])
print(json.dumps(users, ensure_ascii=False, indent=2)[:3000])

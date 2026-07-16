#!/usr/bin/env python3
import json

from zjgj_client import ZjgjClient, ZjgjApiError

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
PROJECT_ID = 2078
SECTION_ID = 1906

pm = ZjgjClient(BASE, token=PM, verify_ssl=False)
invite = pm.get_manage_invite_info(PROJECT_ID, SECTION_ID)
users = ((invite.get("data") or {}).get("info") or {}).get("users") or []
print("users", [(u["id"], u["uid"]) for u in users])

BASE = {
    "project_id": PROJECT_ID,
    "section_id": SECTION_ID,
    "province": "440000",
    "city": "440100",
    "major_ids": "916,917,221",
    "extract_way": 2,
    "take_time": 3,
    "type": 1,
    "address": "山西省太原市",
}


def post(data):
    try:
        r = pm.add_expert_to_project(data)
        return {"ok": True, "msg": r.get("msg")}
    except ZjgjApiError as e:
        return {"ok": False, "error": str(e)}


# Per-user audit variants using row id / uid
for u in users:
    row_id = u["id"]
    uid = u["uid"]
    variants = [
        {**BASE, "users": str(uid), "check": 1},
        {**BASE, "users": str(uid), "check": 1, "status": 2},
        {**BASE, "users": str(uid), "is_check": 1},
        {**BASE, "id": row_id, "users": str(uid), "check": 1},
        {**BASE, "user_id": row_id, "check": 1, "status": 2},
        {**BASE, "invite_user_id": row_id, "check": 1},
    ]
    print(f"\n=== uid={uid} row={row_id} ===")
    for data in variants:
        r = post(data)
        if r.get("ok") or "404" not in r.get("error", ""):
            print(data, "->", r)

# Try sign on project 2010 (known opened)
print("\n=== sign on opened project 2010 ===")
for name, token in [("peng", "2dc7d42b334a80f5a9f468804b4c804e"), ("liao", "1961087d90c565e4620b9a98b69a8b91")]:
    ex = ZjgjClient(BASE, token=token, verify_ssl=False)
    try:
        s = ex.expert_sign_in(2010, 1832, 79)
        print(name, "sign 2010 ->", s.get("msg"))
    except ZjgjApiError as e:
        print(name, "sign 2010 ->", e)

# Final 2078 sign after per-user audit
print("\n=== 2078 sign after per-user audit ===")
for name, token in [("peng", "2dc7d42b334a80f5a9f468804b4c804e"), ("liao", "1961087d90c565e4620b9a98b69a8b91")]:
    ex = ZjgjClient(BASE, token=token, verify_ssl=False)
    try:
        s = ex.expert_sign_in(PROJECT_ID, SECTION_ID, 93)
        print(name, "sign 2078 ->", s.get("msg"))
    except ZjgjApiError as e:
        print(name, "sign 2078 ->", e)

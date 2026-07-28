#!/usr/bin/env python3
import json

from zjgj_client import ZjgjClient, ZjgjApiError

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
EXPERTS = [
    ("专家-测试peng", "2dc7d42b334a80f5a9f468804b4c804e", 11286),
    ("专家-数据�?, "1961087d90c565e4620b9a98b69a8b91", 7882),
]
PROJECT_ID = 2078
SECTION_ID = 1906
INVITE_ID = 93

BASE_PAYLOAD = {
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


def call(client, method, path, **kw):
    try:
        r = client.request(method, path, require_auth=True, **kw)
        return {"ok": True, "msg": r.get("msg"), "data": r.get("data")}
    except ZjgjApiError as e:
        return {"ok": False, "error": str(e)}


pm = ZjgjClient(BASE, token=PM, verify_ssl=False)

print("=== inviteInfo before audit ===")
before = pm.get_manage_invite_info(PROJECT_ID, SECTION_ID)
print(json.dumps(before, ensure_ascii=False, indent=2))

audit_variants = [
    {**BASE_PAYLOAD, "users": "11286,7882", "check": 1},
    {**BASE_PAYLOAD, "users": "11286", "check": 1},
    {**BASE_PAYLOAD, "users": "7882", "check": 1},
    {**BASE_PAYLOAD, "users": "11286,7882", "is_check": 1},
    {**BASE_PAYLOAD, "users": "11286,7882", "status": 1, "check": 1},
    {**BASE_PAYLOAD, "id": 153, "check": 1},
    {**BASE_PAYLOAD, "id": 154, "check": 1},
]

for data in audit_variants:
    r = call(pm, "POST", "api/manage/addExpert", data=data)
    print(f"\naudit payload keys={list(data.keys())} -> {r}")

print("\n=== inviteInfo after audit ===")
after = pm.get_manage_invite_info(PROJECT_ID, SECTION_ID)
print(json.dumps(after, ensure_ascii=False, indent=2))

# Diff user fields
before_users = (before.get("data") or {}).get("info", {}).get("users") or []
after_users = (after.get("data") or {}).get("info", {}).get("users") or []
print("\n=== user field diff ===")
for bu, au in zip(before_users, after_users):
    keys = set(bu) | set(au)
    diff = {k: (bu.get(k), au.get(k)) for k in keys if bu.get(k) != au.get(k)}
    if diff:
        print(f"uid={bu.get('uid')} diff:", diff)
    else:
        print(f"uid={bu.get('uid')} no diff visible; keys={sorted(bu)}")

print("\n=== expert confirm + sign ===")
for name, token, uid in EXPERTS:
    ex = ZjgjClient(BASE, token=token, verify_ssl=False)
    r = call(ex, "POST", "api/expert/confirm", data={"invite_id": INVITE_ID, "status": 1})
    print(f"[{name}] confirm -> {r}")
    r = call(ex, "POST", "api/expert/sign", data={"project_id": PROJECT_ID, "section_id": SECTION_ID, "invite_id": INVITE_ID})
    print(f"[{name}] sign -> {r}")

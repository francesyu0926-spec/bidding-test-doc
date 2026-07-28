#!/usr/bin/env python3
import json

from zjgj_client import ZjgjClient, ZjgjApiError

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
EXPERTS = [
    ("专家-测试peng", "2dc7d42b334a80f5a9f468804b4c804e"),
    ("专家-数据�?, "1961087d90c565e4620b9a98b69a8b91"),
]
PROJECT_ID = 2078
SECTION_ID = 1906
INVITE_ID = 93


def call(client, method, path, **kw):
    try:
        r = client.request(method, path, require_auth=True, **kw)
        return {"ok": True, "msg": r.get("msg"), "data": r.get("data")}
    except ZjgjApiError as e:
        return {"ok": False, "error": str(e)}


pm = ZjgjClient(BASE, token=PM, verify_ssl=False)

print("=== inviteInfo before ===")
print(json.dumps(pm.get_manage_invite_info(PROJECT_ID, SECTION_ID), ensure_ascii=False, indent=2)[:2000])

for name, token in EXPERTS:
    ex = ZjgjClient(BASE, token=token, verify_ssl=False)
    for status in [0, 1, 2]:
        r = call(ex, "POST", "api/expert/confirm", data={"invite_id": INVITE_ID, "status": status})
        print(f"[{name}] confirm status={status} -> {r}")
    r = call(ex, "POST", "api/expert/sign", data={"project_id": PROJECT_ID, "section_id": SECTION_ID, "invite_id": INVITE_ID})
    print(f"[{name}] sign -> {r}")

print("\n=== expert myList after ===")
for name, token in EXPERTS:
    ex = ZjgjClient(BASE, token=token, verify_ssl=False)
    listing = ex.list_expert_projects(page=1, limit=50)
    hits = [i for i in ((listing.get("data") or {}).get("list") or []) if int(i.get("project_id", -1)) == PROJECT_ID]
    print(name, json.dumps(hits, ensure_ascii=False, indent=2))

# PM-side audit candidates with full addExpert payload
base = {
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
audit_payloads = [
    {**base, "id": 153, "status": 1},
    {**base, "id": 154, "status": 1},
    {**base, "ids": "153,154", "status": 1},
    {**base, "users": "11286,7882", "status": 1, "check": 1},
    {**base, "users": "11286,7882", "is_check": 1},
    {**base, "user_id": 153, "status": 2},
    {**base, "invite_id": 93, "user_id": 153, "status": 1},
]
print("\n=== PM audit POST attempts ===")
for path in ["api/manage/addExpert", "api/manage/check", "api/manage/audit", "api/manage/pass", "api/manage/confirm"]:
    for data in audit_payloads:
        r = call(pm, "POST", path, data=data)
        if "404" not in r.get("error", ""):
            print(f"POST {path} {data} -> {r}")

print("\n=== sign retry after PM attempts ===")
for name, token in EXPERTS:
    ex = ZjgjClient(BASE, token=token, verify_ssl=False)
    r = call(ex, "POST", "api/expert/sign", data={"project_id": PROJECT_ID, "section_id": SECTION_ID, "invite_id": INVITE_ID})
    print(f"[{name}] sign -> {r}")

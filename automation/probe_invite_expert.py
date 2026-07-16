#!/usr/bin/env python3
import json

from zjgj_client import ZjgjClient, ZjgjApiError

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
PROJECT_ID = 2078
SECTION_ID = 1906


def call(client, method, path, **kw):
    try:
        r = client.request(method, path, require_auth=True, **kw)
        return {"ok": True, "msg": r.get("msg"), "data": r.get("data")}
    except ZjgjApiError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": repr(e)}


pm = ZjgjClient(BASE, token=PM, verify_ssl=False)

get_paths = [
    "api/manage/inviteExpert",
    "api/manage/searchExpert",
    "api/manage/expertList",
    "api/manage/getExpertList",
    "api/manage/getInviteList",
    "api/manage/inviteList",
    "api/manage/expertInviteList",
    "api/manage/getExpertInviteList",
    "api/manage/checkExpertList",
    "api/manage/getCheckExpertList",
    "api/manage/expertCheckList",
    "api/manage/inviteInfo",
    "api/manage/getExpertCheckList",
    "api/manage/expertRecord",
    "api/manage/getExpertRecord",
]

params_variants = [
    {"project_id": PROJECT_ID, "section_id": SECTION_ID},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "page": 1, "limit": 20},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 0},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "invite_id": 93},
    {"id": 93},
    {"invite_id": 93},
]

print("=== GET probes ===")
for path in get_paths:
    for params in params_variants[:3]:
        r = call(pm, "GET", path, params=params)
        if r.get("ok"):
            print(f"GET {path} {params}")
            print(json.dumps(r, ensure_ascii=False, indent=2)[:3000])
            break

post_paths = [
    "api/manage/inviteExpert",
    "api/manage/checkExpert",
    "api/manage/expertCheck",
    "api/manage/expertAudit",
    "api/manage/auditExpert",
    "api/manage/passExpert",
    "api/manage/confirmExpert",
    "api/manage/agreeExpert",
    "api/manage/approveExpert",
    "api/manage/expertPass",
    "api/manage/expertApprove",
    "api/manage/checkInviteExpert",
    "api/manage/inviteExpertAudit",
    "api/manage/expertInviteAudit",
    "api/manage/auditInviteExpert",
    "api/manage/check",
    "api/manage/audit",
]

post_data = [
    {"id": 153, "status": 1},
    {"id": 154, "status": 1},
    {"ids": "153,154", "status": 1},
    {"user_id": 153, "status": 1, "project_id": PROJECT_ID, "section_id": SECTION_ID},
    {"invite_id": 93, "uid": 11286, "status": 1},
    {"invite_id": 93, "uid": 7882, "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "uid": 11286, "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "id": 153, "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "ids": [153, 154], "status": 1},
]

print("\n=== POST probes (non-404) ===")
for path in post_paths:
    for data in post_data:
        r = call(pm, "POST", path, data=data)
        err = r.get("error", "")
        if "404" not in err:
            print(f"POST {path} {data} -> {r}")

# Try searchExpert to understand expert selection UI
for params in [
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "province": "440000", "city": "440100", "major_ids": "916,917", "page": 1, "limit": 20, "keyword": "测试"},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "province": "440000", "city": "440100", "major_ids": "221", "page": 1, "limit": 20},
]:
    r = call(pm, "GET", "api/manage/searchExpert", params=params)
    if r.get("ok"):
        print("\nsearchExpert", params)
        print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])

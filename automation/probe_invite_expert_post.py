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

# Focus on inviteExpert POST since GET works
payloads = [
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "id": 153, "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "ids": "153,154", "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "uid": 11286, "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "uids": "11286,7882", "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "invite_id": 93, "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "invite_id": 93, "uid": 11286, "status": 1},
    {"id": 153, "status": 1},
    {"id": 153, "status": 2},
    {"id": 153, "check_status": 1},
    {"user_id": 153, "status": 1},
    {"apply_id": 30, "status": 1, "project_id": PROJECT_ID, "section_id": SECTION_ID},
    # addExpert audit variants
    {
        "project_id": PROJECT_ID,
        "section_id": SECTION_ID,
        "province": "440000",
        "city": "440100",
        "major_ids": "916,917,221",
        "extract_way": 2,
        "take_time": 3,
        "type": 1,
        "address": "山西省太原市",
        "users": "11286,7882",
        "status": 1,
        "id": 93,
    },
    {
        "project_id": PROJECT_ID,
        "section_id": SECTION_ID,
        "id": 93,
        "user_id": 153,
        "status": 1,
    },
]

print("=== POST api/manage/inviteExpert ===")
for data in payloads:
    r = call(pm, "POST", "api/manage/inviteExpert", data=data)
    if r.get("ok") or "404" not in r.get("error", ""):
        print(data, "->", r)

# Other promising endpoints from route names
for path in [
    "api/manage/skipReview",
    "api/manage/agreeInvite",
    "api/manage/inviteAgree",
    "api/manage/expertAgree",
    "api/manage/userCheck",
    "api/manage/checkUser",
    "api/manage/userAudit",
    "api/manage/auditUser",
    "api/manage/inviteUserAudit",
    "api/manage/inviteUserCheck",
    "api/manage/checkInviteUser",
    "api/manage/auditInviteUser",
    "api/publicity/inviteAudit",
    "api/publicity/expertInviteAudit",
    "api/publicity/expertAudit",
]:
    for data in [{"id": 153, "status": 1}, {"project_id": PROJECT_ID, "section_id": SECTION_ID, "id": 153, "status": 1}]:
        r = call(pm, "POST", path, data=data)
        if r.get("ok") or "404" not in r.get("error", ""):
            print(f"POST {path} {data} -> {r}")

# GET inviteExpert with status filters
for params in [
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 0},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "check_status": 0},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "invite_id": 93},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "type": 1},
]:
    r = call(pm, "GET", "api/manage/inviteExpert", params=params)
    if r.get("ok"):
        print("GET inviteExpert", params, json.dumps(r, ensure_ascii=False)[:1500])

#!/usr/bin/env python3
import json

from zjgj_client import ZjgjClient, ZjgjApiError

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
EXPERT = "2dc7d42b334a80f5a9f468804b4c804e"
PROJECT_ID = 2078
SECTION_ID = 1906


def call(client, method, path, **kw):
    try:
        r = client.request(method, path, require_auth=True, **kw)
        return {"ok": True, "msg": r.get("msg"), "data": r.get("data")}
    except ZjgjApiError as e:
        return {"ok": False, "error": str(e)}


pm = ZjgjClient(BASE, token=PM, verify_ssl=False)
ex = ZjgjClient(BASE, token=EXPERT, verify_ssl=False)

# Try confirm/sign with different ids
for invite_id in [93, 153, 154]:
    print(f"\n=== expert confirm invite_id={invite_id} ===")
    print(call(ex, "POST", "api/expert/confirm", data={"invite_id": invite_id, "status": 1}))

for invite_id in [93, 153, 154]:
    print(f"\n=== expert sign invite_id={invite_id} ===")
    print(call(ex, "POST", "api/expert/sign", data={"project_id": PROJECT_ID, "section_id": SECTION_ID, "invite_id": invite_id}))

# Brute GET manage endpoints
prefixes = ["get", "list", "check", "audit", "invite", "expert"]
names = [
    "ExpertList", "expertList", "getExpertList", "inviteList", "getInviteList",
    "inviteInfo", "getInviteInfo", "expertInfo", "getExpertInfo", "checkList",
    "auditList", "getCheckList", "getAuditList", "expertCheckList", "inviteCheckList",
]
print("\n=== GET manage probe ===")
for name in names:
    path = f"api/manage/{name}"
    r = call(pm, "GET", path, params={"project_id": PROJECT_ID, "section_id": SECTION_ID, "page": 1, "limit": 20})
    if r.get("ok") or ("404" not in r.get("error", "")):
        print(path, r)

# POST audit with user row ids
for path in [
    "api/manage/checkExpert",
    "api/manage/expertCheck",
    "api/manage/inviteCheck",
    "api/manage/expertPass",
    "api/manage/passInvite",
    "api/manage/auditInvite",
    "api/manage/expertAudit",
    "api/manage/checkInviteExpert",
    "api/manage/expertInviteCheck",
    "api/manage/expertInviteAudit",
    "api/manage/inviteExpertAudit",
    "api/manage/inviteExpertCheck",
    "api/manage/check",
]:
    for data in [
        {"id": 153, "status": 1},
        {"id": 154, "status": 1},
        {"user_id": 153, "status": 1, "project_id": PROJECT_ID, "section_id": SECTION_ID},
        {"invite_id": 93, "uid": 11286, "status": 1},
        {"project_id": PROJECT_ID, "section_id": SECTION_ID, "uid": 11286, "status": 1},
    ]:
        r = call(pm, "POST", path, data=data)
        if r.get("ok") or ("404" not in r.get("error", "")):
            print(f"POST {path} {data} -> {r}")

# publicity audit variants
for path in [
    "api/publicity/expertAudit",
    "api/publicity/inviteAudit",
    "api/publicity/expertInviteAudit",
    "api/publicity/expertCheck",
]:
    for data in [
        {"id": 153, "status": 1, "project_id": PROJECT_ID},
        {"register_id": 153, "status": 1},
        {"project_id": PROJECT_ID, "section_id": SECTION_ID, "uid": 11286, "status": 1},
    ]:
        r = call(pm, "POST", path, data=data)
        if r.get("ok") or ("404" not in r.get("error", "")):
            print(f"POST {path} {data} -> {r}")

print("\n=== inviteInfo after probes ===")
print(json.dumps(pm.get_manage_invite_info(PROJECT_ID, SECTION_ID), ensure_ascii=False, indent=2))

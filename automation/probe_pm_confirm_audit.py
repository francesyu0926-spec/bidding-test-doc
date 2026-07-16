#!/usr/bin/env python3
import json

from zjgj_client import ZjgjClient, ZjgjApiError

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
EXPERT = "2dc7d42b334a80f5a9f468804b4c804f"
EXPERT2 = "2dc7d42b334a80f5a9f468804b4c804e"
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
ex = ZjgjClient(BASE, token=EXPERT2, verify_ssl=False)

print("=== PM calling expert/confirm ===")
for status in [1, 2, 3]:
    for invite_id in [93, 153]:
        r = call(pm, "POST", "api/expert/confirm", data={"invite_id": invite_id, "status": status})
        print(f"PM confirm invite_id={invite_id} status={status} -> {r}")

print("\n=== Expert confirm status variants ===")
for status in [0, 1, 2, 3, 4]:
    r = call(ex, "POST", "api/expert/confirm", data={"invite_id": 93, "status": status})
    print(f"expert confirm status={status} -> {r}")

print("\n=== PM audit via manage/addExpert with check fields ===")
payloads = [
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "id": 153, "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "id": 153, "check_status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "id": 153, "is_check": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "id": 153, "audit_status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "ids": "153,154", "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "user_id": 153, "status": 1},
    {"project_id": PROJECT_ID, "section_id": SECTION_ID, "invite_id": 93, "user_id": 153, "status": 1},
]
for data in payloads:
    for path in ["api/manage/addExpert", "api/manage/checkExpert", "api/manage/expertCheck", "api/manage/inviteCheck"]:
        r = call(pm, "POST", path, data=data)
        if "404" not in r.get("error", ""):
            print(f"POST {path} {data} -> {r}")

# Brute short manage actions from prior research
actions = [
    "expertList", "getExpertList", "listExpert", "getListExpert", "expertRecord", "getExpertRecord",
    "inviteRecord", "getInviteRecord", "extractRecord", "getExtractRecord", "checkRecord", "getCheckRecord",
    "auditRecord", "getAuditRecord", "expertUserList", "getExpertUserList", "inviteUserList", "getInviteUserList",
    "userList", "getUserList", "checkList", "getCheckList", "auditList", "getAuditList",
    "expertConfirm", "expertPass", "expertApprove", "expertAgree", "expertAccept", "expertVerify",
    "inviteConfirm", "invitePass", "inviteApprove", "inviteAgree", "inviteAccept", "inviteVerify",
    "checkInvite", "auditInvite", "passInvite", "confirmInvite", "agreeInvite", "acceptInvite",
    "checkExtract", "auditExtract", "passExtract", "confirmExtract",
    "userCheck", "userAudit", "userPass", "userConfirm", "userApprove",
    "check", "audit", "pass", "approve", "confirm", "agree", "accept", "verify",
    "operate", "handle", "deal", "review", "save", "update", "edit", "set",
]
print("\n=== POST manage short actions (non-404) ===")
for action in actions:
    path = f"api/manage/{action}"
    for data in [{"id": 153, "status": 1}, {"project_id": PROJECT_ID, "section_id": SECTION_ID, "id": 153, "status": 1}]:
        r = call(pm, "POST", path, data=data)
        if r.get("ok") or "404" not in r.get("error", ""):
            print(f"POST {path} {data} -> {r}")

print("\n=== try sign after PM confirm ===")
r = call(ex, "POST", "api/expert/sign", data={"project_id": PROJECT_ID, "section_id": SECTION_ID, "invite_id": 93})
print("sign ->", r)

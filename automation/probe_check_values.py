#!/usr/bin/env python3
import json

from zjgj_client import ZjgjClient, ZjgjApiError

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
PROJECT_ID = 2078
SECTION_ID = 1906

pm = ZjgjClient(BASE, token=PM, verify_ssl=False)
info = pm.get_publicity_project_info(PROJECT_ID).get("data") or {}
sec = (info.get("sections") or [{}])[0]
print("project state", info.get("state"), "section state", sec.get("state"), "start_time", info.get("start_time"))

invite = pm.get_manage_invite_info(PROJECT_ID, SECTION_ID)
print("\ninviteInfo users count", len(((invite.get("data") or {}).get("info") or {}).get("users") or []))

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


def call(method, path, **kw):
    try:
        r = pm.request(method, path, require_auth=True, **kw)
        return {"ok": True, "msg": r.get("msg"), "data": r.get("data")}
    except ZjgjApiError as e:
        return {"ok": False, "error": str(e)}


for check_val in [1, 2, 3]:
    for status_val in [None, 1, 2]:
        data = {**BASE_PAYLOAD, "users": "11286,7882", "check": check_val}
        if status_val is not None:
            data["status"] = status_val
        r = call("POST", "api/manage/addExpert", data=data)
        print(f"check={check_val} status={status_val} -> {r}")

# inspect expert-side status after audit
for name, token in [("peng", "2dc7d42b334a80f5a9f468804b4c804e"), ("liao", "1961087d90c565e4620b9a98b69a8b91")]:
    ex = ZjgjClient(BASE, token=token, verify_ssl=False)
    print(f"\n=== {name} invites by status ===")
    for st in range(0, 7):
        r = ex.list_expert_invites(page=1, limit=20, status=st)
        hits = [i for i in ((r.get("data") or {}).get("list") or []) if int(i.get("project_id", -1)) == PROJECT_ID]
        if hits:
            print("status", st, json.dumps(hits, ensure_ascii=False)[:1000])
    listing = ex.list_expert_projects(page=1, limit=50)
    hits = [i for i in ((listing.get("data") or {}).get("list") or []) if int(i.get("project_id", -1)) == PROJECT_ID]
    print("myList", json.dumps(hits, ensure_ascii=False))

# try sign for both
for name, token in [("peng", "2dc7d42b334a80f5a9f468804b4c804e"), ("liao", "1961087d90c565e4620b9a98b69a8b91")]:
    ex = ZjgjClient(BASE, token=token, verify_ssl=False)
    for status in [0, 1]:
        c = call_ex = None
        try:
            c = ex.request("POST", "api/expert/confirm", data={"invite_id": 93, "status": status}, require_auth=True)
        except ZjgjApiError as e:
            c = str(e)
        print(f"{name} confirm status={status} -> {c}")
    try:
        s = ex.expert_sign_in(PROJECT_ID, SECTION_ID, 93)
        print(f"{name} sign ->", s.get("msg"))
    except ZjgjApiError as e:
        print(f"{name} sign fail ->", e)

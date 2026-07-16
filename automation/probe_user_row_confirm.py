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
batch_id = ((invite.get("data") or {}).get("info") or {}).get("id")
print("batch_id", batch_id)
print("users", json.dumps([{"id": u.get("id"), "uid": u.get("uid"), "name": u.get("name")} for u in users], ensure_ascii=False))

experts = [
    ("专家-测试peng", "2dc7d42b334a80f5a9f468804b4c804e", 11286),
    ("专家-数据廖", "1961087d90c565e4620b9a98b69a8b91", 7882),
]

# PM audit pass
audit_payload = {
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
    "check": 1,
}
r = pm.add_expert_to_project(audit_payload)
print("PM audit", r.get("msg"))

uid_to_row = {int(u["uid"]): int(u["id"]) for u in users}

for name, token, uid in experts:
    ex = ZjgjClient(BASE, token=token, verify_ssl=False)
    row_id = uid_to_row.get(uid)
    for invite_id in [batch_id, row_id]:
        if invite_id is None:
            continue
        for status in [0, 1]:
            try:
                c = ex.confirm_expert_invite(int(invite_id), status=status)
                print(f"[{name}] confirm invite_id={invite_id} status={status} -> {c.get('msg')}")
            except ZjgjApiError as e:
                print(f"[{name}] confirm invite_id={invite_id} status={status} -> {e}")
    for invite_id in [batch_id, row_id]:
        if invite_id is None:
            continue
        try:
            s = ex.expert_sign_in(PROJECT_ID, SECTION_ID, int(invite_id))
            print(f"[{name}] sign invite_id={invite_id} -> {s.get('msg')}")
        except ZjgjApiError as e:
            print(f"[{name}] sign invite_id={invite_id} -> {e}")

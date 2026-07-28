#!/usr/bin/env python3
import json
from datetime import datetime, timedelta

from zjgj_client import ZjgjClient, ZjgjApiError

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
PROJECT_ID = 2078
SECTION_ID = 1906
EXPERTS = [
    ("专家-测试peng", "2dc7d42b334a80f5a9f468804b4c804e"),
    ("专家-数据�?, "1961087d90c565e4620b9a98b69a8b91"),
]

pm = ZjgjClient(BASE, token=PM, verify_ssl=False)

# Force open time to past
info = pm.get_publicity_project_info(PROJECT_ID).get("data") or {}
past = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
change = dict(info)
change["id"] = PROJECT_ID
change["start_time"] = past
change["file_end_time"] = past
for k in ["create_time", "update_time", "sections", "cate", "pattern", "company"]:
    change.pop(k, None)
try:
    r = pm.publish_change_project(PROJECT_ID, change)
    print("publish change", r.get("msg"))
except ZjgjApiError as e:
    print("publish change failed", e)

info2 = pm.get_publicity_project_info(PROJECT_ID).get("data") or {}
sec = (info2.get("sections") or [{}])[0]
print("after change: project state", info2.get("state"), "section state", sec.get("state"))

# PM audit only (no expert confirm)
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
print("PM audit", pm.add_expert_to_project(audit_payload).get("msg"))

print("\n=== sign without expert confirm ===")
for name, token in EXPERTS:
    ex = ZjgjClient(BASE, token=token, verify_ssl=False)
    try:
        s = ex.expert_sign_in(PROJECT_ID, SECTION_ID, 93)
        print(f"[{name}] sign -> {s.get('msg')}")
    except ZjgjApiError as e:
        print(f"[{name}] sign -> {e}")

print("\n=== sign after expert confirm status=0 ===")
for name, token in EXPERTS:
    ex = ZjgjClient(BASE, token=token, verify_ssl=False)
    try:
        c = ex.confirm_expert_invite(93, status=0)
        print(f"[{name}] confirm -> {c.get('msg')}")
    except ZjgjApiError as e:
        print(f"[{name}] confirm -> {e}")
    try:
        s = ex.expert_sign_in(PROJECT_ID, SECTION_ID, 93)
        print(f"[{name}] sign -> {s.get('msg')}")
    except ZjgjApiError as e:
        print(f"[{name}] sign -> {e}")

progress = pm.get_manage_progress(PROJECT_ID, SECTION_ID)
print("\nprogress", json.dumps(progress, ensure_ascii=False)[:1500])

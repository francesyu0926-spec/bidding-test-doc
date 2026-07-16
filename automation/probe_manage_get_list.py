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


pm = ZjgjClient(BASE, token=PM, verify_ssl=False)

get_endpoints = [
    ("api/manage/searchExpert", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "province": "440000", "city": "440100", "major_ids": "916,917", "page": 1, "limit": 20}),
    ("api/manage/searchExpert", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "page": 1, "limit": 20, "keyword": "测试"}),
    ("api/manage/expertList", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "page": 1, "limit": 20}),
    ("api/manage/getExpertList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/getInviteList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/inviteList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/getExpertInviteList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/expertInviteList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/getCheckList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/checkList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/getExpertCheckList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/expertCheckList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/getInviteCheckList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/inviteCheckList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/getExtractList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/extractList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/getExtractInfo", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/extractInfo", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "invite_id": 93}),
    ("api/manage/getExpertInfo", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "id": 153}),
    ("api/manage/expertInfo", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "id": 153}),
    ("api/manage/getInviteUserList", {"project_id": PROJECT_ID, "section_id": SECTION_ID, "invite_id": 93}),
    ("api/manage/inviteUserList", {"project_id": PROJECT_ID, "section_id": SECTION_ID}),
    ("api/manage/getInviteUserInfo", {"id": 153}),
    ("api/manage/inviteUserInfo", {"id": 153}),
]

for path, params in get_endpoints:
    r = call(pm, "GET", path, params=params)
    if r.get("ok"):
        print(f"\n=== {path} ===")
        print(json.dumps(r, ensure_ascii=False, indent=2)[:4000])
    elif "404" not in r.get("error", ""):
        print(f"ERR {path}: {r}")

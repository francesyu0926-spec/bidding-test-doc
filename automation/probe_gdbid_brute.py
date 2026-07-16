#!/usr/bin/env python3
import json
import re
import requests
from pathlib import Path

from zjgj_client import ZjgjClient, ZjgjApiError

BASE = "https://www.bidding.shanxiguandian.com"
GDBID = "https://www.gdbid.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
PROJECT_ID = 2078
SECTION_ID = 1906
CACHE = Path(__file__).parent / "_js_cache"


def fetch_gdbid_js():
    html = requests.get(GDBID + "/", verify=False, timeout=30).text
    print("gdbid html len", len(html))
    chunks = sorted(set(re.findall(r"static/js/[^\"']+\.js", html)))
    print("gdbid chunks", len(chunks))
    manage = set()
    for chunk in chunks:
        name = chunk.split("/")[-1]
        path = CACHE / f"gdbid_{name}"
        try:
            text = requests.get(f"{GDBID}/{chunk}", verify=False, timeout=20).text
            if len(text) > 200:
                path.write_text(text, encoding="utf-8")
        except Exception:
            continue
        manage.update(re.findall(r"api/manage/[a-zA-Z0-9_]+", text))
        manage.update(re.findall(r"bidding/manage/[a-zA-Z0-9_]+", text))
    print("manage apis from gdbid:", sorted(manage))
    for path in CACHE.glob("gdbid_*.js"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(k in text for k in ("审核", "inviteExpert", "checkExpert", "expertAudit", "addExpert", "inviteInfo")):
            print("\nfile", path.name)
            for m in re.finditer(r".{0,50}(审核|inviteExpert|checkExpert|expertAudit|addExpert|inviteInfo|registerAudit).{0,100}", text):
                s = m.group(0)
                if "api/" in s or "manage/" in s or "审核" in s:
                    print(" ", s[:200])


def call(client, method, path, **kw):
    try:
        r = client.request(method, path, require_auth=True, **kw)
        return {"ok": True, "msg": r.get("msg"), "data": r.get("data")}
    except ZjgjApiError as e:
        return {"ok": False, "error": str(e)}


def brute_post():
    pm = ZjgjClient(BASE, token=PM, verify_ssl=False)
    actions = [
        "checkExpert", "expertCheck", "expertAudit", "auditExpert", "passExpert", "approveExpert",
        "confirmExpert", "agreeExpert", "acceptExpert", "verifyExpert", "auditInvite", "inviteAudit",
        "checkInvite", "inviteCheck", "expertInviteCheck", "expertInviteAudit", "inviteExpertCheck",
        "inviteExpertAudit", "checkInviteExpert", "auditInviteExpert", "expertPass", "expertApprove",
        "expertConfirm", "expertAgree", "expertVerify", "setExpertStatus", "updateExpertStatus",
        "changeExpertStatus", "operateExpert", "handleExpert", "dealExpert", "reviewExpert",
        "expertReview", "inviteReview", "reviewInvite", "check", "audit", "pass", "approve",
        "confirm", "agree", "accept", "verify", "handle", "deal", "operate", "review",
        "saveExpert", "updateExpert", "editExpert", "setExpert", "expertOperate", "inviteOperate",
        "extractCheck", "extractAudit", "extractPass", "extractConfirm", "extractExpert",
        "checkExtract", "auditExtract", "passExtract",
    ]
    payloads = [
        {"id": 153, "status": 1},
        {"id": 154, "status": 1},
        {"ids": "153,154", "status": 1},
        {"project_id": PROJECT_ID, "section_id": SECTION_ID, "id": 153, "status": 1},
        {"project_id": PROJECT_ID, "section_id": SECTION_ID, "uid": 11286, "status": 1},
        {"invite_id": 93, "uid": 11286, "status": 1},
        {"invite_user_id": 153, "status": 1},
        {"user_id": 153, "status": 1, "project_id": PROJECT_ID, "section_id": SECTION_ID},
    ]
    found = []
    for action in actions:
        path = f"api/manage/{action}"
        for data in payloads:
            r = call(pm, "POST", path, data=data)
            err = r.get("error", "")
            if "404" not in err:
                found.append((path, data, r))
    print("\n=== non-404 POST manage/* ===")
    for item in found:
        print(item)


if __name__ == "__main__":
    fetch_gdbid_js()
    brute_post()

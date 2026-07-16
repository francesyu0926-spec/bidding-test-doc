"""Probe sign field for project 2079."""
import json
import urllib3
import requests

urllib3.disable_warnings()

BASE = "https://www.bidding.shanxiguandian.com"
cfg = json.load(open("config.project7.generated.json", encoding="utf-8"))
report = json.load(open("project7_full_report.json", encoding="utf-8"))
PM = cfg["tokens"]["project_manager"]


def req(token, method, path, **kw):
    r = requests.request(
        method,
        BASE + "/" + path.lstrip("/"),
        headers={"Token": token, "Accept": "application/json"},
        verify=False,
        timeout=30,
        **kw,
    )
    return r.json()


prog = req(PM, "GET", "api/manage/getProgress", params={"project_id": 2079, "section_id": 1907})
print("=== getProgress case 2 ===")
for p in prog.get("data", {}).get("progress", []):
    if p.get("id") == 2:
        print(json.dumps(p, ensure_ascii=False, indent=2))

for b in cfg["tokens"]["bidders"]:
    tid = next((br["tender_id"] for br in report.get("bidders", []) if br["name"] == b["name"]), None)
    print(f"\n=== {b['name']} tender_id={tid} ===")
    f = req(b["token"], "GET", "api/tender/getTenderFile", params={"tender_id": tid, "section_id": 1907})
    data = f.get("data") or {}
    print("file_id:", data.get("id"), "sign:", data.get("sign"), "amount:", data.get("amount"))
    cp = req(b["token"], "GET", "api/tender/checkPassword", params={"project_id": 2079, "section_id": 1907})
    print("checkPassword (sign?1:0):", cp.get("data"))

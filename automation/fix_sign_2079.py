"""Test and apply tender signature for project 2079."""
import json
import urllib3
import requests

urllib3.disable_warnings()

BASE = "https://www.bidding.shanxiguandian.com"
# 1x1 transparent PNG
SIGNATURE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

cfg = json.load(open("config.project7.generated.json", encoding="utf-8"))
report = json.load(open("project7_full_report.json", encoding="utf-8"))
PASSWORD = cfg["submit"]["password"]


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


results = []
for b in cfg["tokens"]["bidders"]:
    tid = next((br["tender_id"] for br in report.get("bidders", []) if br["name"] == b["name"]), None)
    entry = {"bidder": b["name"], "tender_id": tid}
    try:
        file_data = req(
            b["token"], "GET", "api/tender/getTenderFile", params={"tender_id": tid, "section_id": 1907}
        ).get("data") or {}
        file_id = file_data.get("id")
        entry["file_id"] = file_id
        entry["sign_before"] = file_data.get("sign")

        pwd = req(
            b["token"],
            "POST",
            "api/tender/password",
            data={
                "project_id": 2079,
                "tender_id": tid,
                "section_id": 1907,
                "password": PASSWORD,
            },
        )
        entry["password"] = pwd.get("msg")

        sig = req(
            b["token"],
            "POST",
            "api/tender/signature",
            data={"id": file_id, "signature": SIGNATURE},
        )
        entry["signature"] = sig

        after = req(
            b["token"], "GET", "api/tender/getTenderFile", params={"tender_id": tid, "section_id": 1907}
        ).get("data") or {}
        entry["sign_after"] = after.get("sign")
        cp = req(
            b["token"], "GET", "api/tender/checkPassword", params={"project_id": 2079, "section_id": 1907}
        )
        entry["checkPassword"] = cp.get("data")
        entry["ok"] = bool(after.get("sign"))
    except Exception as exc:
        entry["error"] = str(exc)
        entry["ok"] = False
    results.append(entry)

print(json.dumps(results, ensure_ascii=False, indent=2))

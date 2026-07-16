#!/usr/bin/env python3
"""Probe bid-opening status for projects 2060-2063 vs opened reference projects."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from zjgj_client import ZjgjApiError, ZjgjClient

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
TARGETS = [(2060, 1890), (2061, 1891), (2062, 1892), (2063, 1893)]
REFERENCE_IDS = [2052, 2050, 2048, 2040]

OPEN_ENDPOINTS = [
    ("GET", "api/manage/open", {"project_id": 2060, "section_id": 1890}),
    ("POST", "api/manage/open", {"project_id": 2060, "section_id": 1890}),
    ("GET", "api/manage/startBid", {"project_id": 2060, "section_id": 1890}),
    ("POST", "api/manage/startBid", {"project_id": 2060, "section_id": 1890}),
    ("GET", "api/manage/openBid", {"project_id": 2060, "section_id": 1890}),
    ("POST", "api/manage/openBid", {"project_id": 2060, "section_id": 1890}),
    ("POST", "api/manage/begin", {"project_id": 2060, "section_id": 1890}),
    ("POST", "api/manage/start", {"project_id": 2060, "section_id": 1890}),
    ("POST", "api/section/open", {"project_id": 2060, "section_id": 1890}),
    ("POST", "api/publicity/open", {"project_id": 2060}),
    ("GET", "api/cron/openBid", {}),
    ("GET", "api/index/cron", {}),
]


def pick(obj: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {k: obj.get(k) for k in keys if k in obj}


def project_snapshot(pm: ZjgjClient, project_id: int, section_id: int, my_list_item: dict | None) -> dict[str, Any]:
    row: dict[str, Any] = {"project_id": project_id, "section_id": section_id}
    info = pm.get_publicity_project_info(project_id).get("data") or {}
    sections = info.get("sections") or []
    row.update(
        pick(
            info,
            [
                "title",
                "start_time",
                "file_start_time",
                "file_end_time",
                "is_audit",
                "is_min",
                "manage_status",
                "status",
                "pattern_id",
                "cate_id",
            ],
        )
    )
    row["section_state"] = sections[0].get("state") if sections else None
    row["section_detail"] = sections[0] if sections else None
    if my_list_item:
        row["myList"] = pick(
            my_list_item,
            [
                "status",
                "start_time",
                "file_end_time",
                "title",
                "section_id",
                "state",
                "is_min",
                "bidder_count",
                "tender_count",
            ],
        )

    try:
        row["progress"] = pm.get_manage_progress(project_id, section_id).get("data")
    except ZjgjApiError as exc:
        row["progress_error"] = str(exc)

    reg_list = (pm.list_project_registers(project_id, limit=50).get("data") or {}).get("list") or []
    row["registers"] = {
        "count": len(reg_list),
        "paid": sum(1 for r in reg_list if int(r.get("pay_status", 0)) == 1),
        "audited": sum(1 for r in reg_list if int(r.get("status", 0)) == 1),
        "items": [
            pick(r, ["id", "status", "pay_status", "company_name", "contact_phone"]) for r in reg_list[:8]
        ],
    }

    tlist = (pm.list_manage_tenders(project_id, section_id).get("data") or {}).get("list") or []
    row["tenders"] = {
        "count": len(tlist),
        "items": [pick(t, ["tender_id", "apply_id", "company_name", "status", "sign"]) for t in tlist[:8]],
    }

    try:
        row["invite"] = pm.get_manage_invite_info(project_id, section_id).get("data")
    except ZjgjApiError as exc:
        row["invite_error"] = str(exc)

    return row


def probe_open_endpoints(pm: ZjgjClient) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for method, path, params in OPEN_ENDPOINTS:
        entry: dict[str, Any] = {"method": method, "path": path}
        try:
            if method == "GET":
                resp = pm.request("GET", path, params=params, require_auth=True)
            else:
                resp = pm.request("POST", path, data=params, require_auth=True)
            entry["code"] = resp.get("code")
            entry["msg"] = resp.get("msg")
            entry["data_keys"] = list((resp.get("data") or {}).keys()) if isinstance(resp.get("data"), dict) else type(resp.get("data")).__name__
        except ZjgjApiError as exc:
            entry["error"] = str(exc)
            entry["error_code"] = exc.code
        except Exception as exc:
            entry["error"] = str(exc)
        results.append(entry)
    return results


def main() -> None:
    pm = ZjgjClient(BASE, token=PM, verify_ssl=False)
    now = datetime.now()
    print(f"NOW: {now.strftime('%Y-%m-%d %H:%M:%S')}")

    listing = pm.list_manage_projects(page=1, limit=200)
    all_items = (listing.get("data") or {}).get("list") or []
    by_pid = {int(x.get("project_id", -1)): x for x in all_items}

    opened = [x for x in all_items if int(x.get("status", 0)) == 1]
    bidding = [x for x in all_items if int(x.get("status", 0)) == 2]
    print(f"myList: total={len(all_items)} opened={len(opened)} bidding={len(bidding)}")

    out: dict[str, Any] = {
        "now": now.isoformat(),
        "myList_summary": {
            "total": len(all_items),
            "opened_count": len(opened),
            "bidding_count": len(bidding),
            "opened_sample": [
                pick(x, ["project_id", "section_id", "status", "start_time", "title"]) for x in opened[:5]
            ],
        },
        "targets": [],
        "references": [],
        "open_endpoint_probe": probe_open_endpoints(pm),
    }

    for pid, sid in TARGETS:
        out["targets"].append(project_snapshot(pm, pid, sid, by_pid.get(pid)))

    for ref_id in REFERENCE_IDS:
        item = by_pid.get(ref_id)
        if not item:
            continue
        sid = int(item.get("section_id", 0))
        out["references"].append(project_snapshot(pm, ref_id, sid, item))

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

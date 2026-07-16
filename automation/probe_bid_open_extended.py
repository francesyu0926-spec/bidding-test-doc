#!/usr/bin/env python3
"""Extended probe: review config, is_min, original times, manage API discovery."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import requests

from zjgj_client import ZjgjApiError, ZjgjClient

BASE = "https://www.bidding.shanxiguandian.com"
PM = "41ecfede938eb984fe6cfe94c185688f"
TARGETS = [2060, 2061, 2062, 2063]
REF = [2052, 1983, 1980]


def dump_info_fields(info: dict) -> dict:
    keep = {}
    for k, v in info.items():
        if k in ("intro", "images", "sections"):
            if k == "sections" and isinstance(v, list) and v:
                keep["sections"] = [{kk: vv for kk, vv in s.items() if kk != "zip_url"} for s in v]
            continue
        keep[k] = v
    return keep


def try_review_endpoints(pm: ZjgjClient, project_id: int, section_id: int) -> dict:
    endpoints = [
        ("GET", "api/publicity/saveReview", {"publicity_id": project_id, "section_id": section_id}),
        ("GET", "api/publicity/saveReview", {"project_id": project_id, "section_id": section_id}),
        ("GET", "api/publicity/review", {"project_id": project_id, "section_id": section_id}),
        ("GET", "api/manage/getReview", {"project_id": project_id, "section_id": section_id}),
    ]
    out = {}
    for method, path, params in endpoints:
        try:
            resp = pm.request(method, path, params=params, require_auth=True)
            out[path] = {"code": resp.get("code"), "msg": resp.get("msg"), "data": resp.get("data")}
        except ZjgjApiError as exc:
            out[path] = {"error": str(exc)}
        except Exception as exc:
            out[path] = {"error": str(exc)[:120]}
    return out


def discover_manage_routes() -> list[str]:
    cache = Path(__file__).parent / "_js_cache"
    hits: set[str] = set()
    for js in cache.glob("*.js"):
        text = js.read_text(encoding="utf-8", errors="ignore")
        for m in re.findall(r"api/manage/[a-zA-Z0-9_]+", text):
            hits.add(m)
        for m in re.findall(r"api/publicity/[a-zA-Z0-9_]+", text):
            if any(x in m.lower() for x in ("review", "open", "cron", "change", "create")):
                hits.add(m)
    return sorted(hits)


def main() -> None:
    pm = ZjgjClient(BASE, token=PM, verify_ssl=False)
    now = datetime.now()
    result: dict = {"now": now.isoformat(), "projects": {}, "manage_routes_in_js": discover_manage_routes()}

    for pid in TARGETS + REF:
        info = pm.get_publicity_project_info(pid).get("data") or {}
        sid = (info.get("sections") or [{}])[0].get("id")
        st = info.get("start_time")
        st_dt = datetime.strptime(st, "%Y-%m-%d %H:%M:%S") if st else None
        my_rows = [
            x
            for x in (pm.list_manage_projects(limit=200).get("data") or {}).get("list", [])
            if int(x.get("project_id", 0)) == pid
        ]
        statuses = sorted({int(x.get("status", 0)) for x in my_rows})
        result["projects"][pid] = {
            "info": dump_info_fields(info),
            "start_in_past_min": round((now - st_dt).total_seconds() / 60, 1) if st_dt else None,
            "myList_statuses": statuses,
            "myList_rows": len(my_rows),
            "registers": [
                {
                    "id": r.get("id"),
                    "status": r.get("status"),
                    "status_name": r.get("status_name"),
                    "pay_state": r.get("pay_state"),
                    "pay_state_name": r.get("pay_state_name"),
                }
                for r in (pm.list_project_registers(pid).get("data") or {}).get("list", [])
            ],
            "tender_count": len(
                (pm.list_manage_tenders(pid, sid).get("data") or {}).get("list", [])
                if sid
                else []
            ),
            "review_probe": try_review_endpoints(pm, pid, sid) if sid else {},
        }

    out = Path(__file__).parent / "probe_bid_open_extended.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {out}")
    print("manage routes:", result["manage_routes_in_js"])
    for pid in TARGETS:
        p = result["projects"][pid]
        sec = (p["info"].get("sections") or [{}])[0]
        print(
            pid,
            "section_state=",
            sec.get("state"),
            "is_min=",
            p["info"].get("is_min"),
            "start_past_min=",
            p["start_in_past_min"],
            "myList=",
            p["myList_statuses"],
            "tenders=",
            p["tender_count"],
        )


if __name__ == "__main__":
    main()

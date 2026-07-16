#!/usr/bin/env python3
import json
from datetime import datetime, timedelta
from pathlib import Path

from run_bid_opening import DEFAULT_EXPERTS, run_project as run_bid_open
from run_project_folder import build_project_config, scan_project_folder
from run_three_stage_flow import load_config, run_flow

base = load_config(Path("config.project4.base.json"))
project_dir = Path(r"d:\文件\客户项目文件\项目集\3")
scanned = scan_project_folder(project_dir)
config = build_project_config(base, scanned)
now = datetime.now()
config["publish"]["project_no"] = f"AUTO-SET3-{now.strftime('%Y%m%d%H%M%S')}"
config["publish"]["file_start_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
config["publish"]["file_end_time"] = (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
config["publish"]["start_time"] = (now + timedelta(minutes=4)).strftime("%Y-%m-%d %H:%M:%S")
Path("config.project3.generated.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
print("publish start", config["publish"]["start_time"], "project_no", config["publish"]["project_no"])
result = run_flow(config, dry_run=False)
print("flow done", result.get("project_id"), result.get("section_id"))
open_result = run_bid_open(
    {"project_id": result["project_id"], "section_id": result["section_id"], "set": 3},
    base_url=config["base_url"],
    pm_token=config["tokens"]["project_manager"],
    config={
        "verify_ssl": False,
        "expert_invite": {"enabled": True},
        "expert_actions": {"audit": True, "confirm": False, "sign": True, "wait_invite_timeout_sec": 15, "poll_sec": 2},
    },
    experts=DEFAULT_EXPERTS,
    bidders=[{"name": b.get("name"), "token": b["token"], "register": b.get("register")} for b in config["tokens"]["bidders"]],
    decrypt_password="123456",
    force_times=False,
    wait_open_sec=180,
)
report = {
    "project_id": result["project_id"],
    "section_id": result["section_id"],
    "bidders": result.get("bidders"),
    "bid_opening": open_result,
}
Path("set3_retry_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

#!/usr/bin/env python3
import json
from datetime import datetime, timedelta
from pathlib import Path

from run_three_stage_flow import load_config, run_flow

cfg = load_config(Path("config.project4.generated.json"))
now = datetime.now()
cfg["publish"]["project_no"] = f"ZCGF-CZFW-260504-R{now.strftime('%H%M%S')}"
cfg["publish"]["file_start_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
cfg["publish"]["file_end_time"] = (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
cfg["publish"]["start_time"] = (now + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
Path("config.project4.generated.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

result = run_flow(cfg, dry_run=False)
report = {
    "set_index": 4,
    "status": "success",
    "project_id": result.get("project_id"),
    "section_id": result.get("section_id"),
    "project_name": cfg["publish"].get("title"),
    "project_no": cfg["publish"]["project_no"],
    "bidder_count": len(result.get("bidders", [])),
    "bidders": [
        {
            "name": b.get("name"),
            "mobile": b.get("mobile"),
            "register_id": b.get("register_id"),
            "tender_id": b.get("tender_id"),
            "status": "failed" if b.get("error") else "submitted",
            "error": b.get("error"),
        }
        for b in result.get("bidders", [])
    ],
}
print(json.dumps(report, ensure_ascii=False, indent=2))

batch = json.loads(Path("batch_run_report.json").read_text(encoding="utf-8"))
for i, r in enumerate(batch):
    if r["set_index"] == 4:
        failed = [b for b in report["bidders"] if b["status"] == "failed"]
        status = "partial" if failed and len(failed) < len(report["bidders"]) else ("failed" if failed else "success")
        batch[i] = {
            **r,
            **report,
            "status": status,
            "flow_result": result,
            "error": None,
        }
        break
Path("batch_run_report.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

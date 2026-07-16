#!/usr/bin/env python3
"""Batch-run bidding flow for 项目集 folders 1-6."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from run_project_folder import build_project_config, scan_project_folder
from run_three_stage_flow import apply_publish_times, load_config, run_flow
from zjgj_client import ZjgjApiError

MAX_FILE_BYTES = 150 * 1024 * 1024
AUTOMATION_DIR = Path(__file__).resolve().parent
BASE_CONFIG = AUTOMATION_DIR / "config.project4.base.json"

PROJECT_DIRS = [
    Path(r"d:\文件\客户项目文件\项目集\1"),
    Path(r"d:\文件\客户项目文件\项目集\2"),
    Path(r"d:\文件\客户项目文件\项目集\3"),
    Path(r"d:\文件\客户项目文件\项目集\4"),
    Path(r"d:\文件\客户项目文件\项目集\5"),
    Path(r"d:\文件\客户项目文件\项目集\6"),
]


def filter_large_files(paths: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
    kept: list[str] = []
    skipped: list[dict[str, Any]] = []
    for path_str in paths:
        path = Path(path_str)
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            skipped.append({"path": path_str, "name": path.name, "mb": round(size / 1024 / 1024, 2)})
        else:
            kept.append(path_str)
    return kept, skipped


def bidder_summary(bidders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bidder in bidders:
        row: dict[str, Any] = {
            "name": bidder.get("name"),
            "mobile": bidder.get("mobile"),
            "register_id": bidder.get("register_id"),
            "tender_id": bidder.get("tender_id"),
            "pay_state": bidder.get("pay_state"),
            "pay_state_name": bidder.get("pay_state_name"),
            "register_skipped": bidder.get("register_skipped"),
            "payment_skipped": bidder.get("payment_skipped"),
            "submit_skipped": bidder.get("submit_skipped"),
            "error": bidder.get("error"),
        }
        if bidder.get("error"):
            row["status"] = "failed"
        elif bidder.get("submit_skipped") or bidder.get("submit"):
            row["status"] = "submitted"
        elif bidder.get("register_id"):
            row["status"] = "registered"
        else:
            row["status"] = "unknown"
        rows.append(row)
    return rows


def run_one(index: int, project_dir: Path, base_config: dict[str, Any], *, extract_only: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "set_index": index,
        "folder": str(project_dir),
        "status": "pending",
    }
    try:
        scanned = scan_project_folder(project_dir)
        tender_kept, tender_skipped = filter_large_files(scanned.get("tender_files") or [])
        bidding_kept, bidding_skipped = filter_large_files(scanned.get("bidding_files") or [])

        scanned["tender_files"] = tender_kept
        scanned["bidding_files"] = bidding_kept
        extracted = scanned.get("extracted_by_file") or {}
        scanned["extracted_by_file"] = {k: v for k, v in extracted.items() if k in tender_kept}

        report["skipped_files"] = tender_skipped + bidding_skipped
        report["project_name"] = scanned.get("title")
        report["tenderer_name"] = scanned.get("tenderer_name")
        report["tender_file_count"] = len(tender_kept)
        report["token_pool_size"] = len(base_config.get("tokens", {}).get("bidders") or [])

        if not tender_kept:
            report["status"] = "skipped"
            report["error"] = "no tender files after 150MB filter"
            return report

        if len(tender_kept) > report["token_pool_size"]:
            report["token_reuse_warning"] = (
                f"{len(tender_kept)} tender files > {report['token_pool_size']} tokens; round-robin reuse"
            )

        config = build_project_config(base_config, scanned)
        apply_publish_times(config)

        config_path = AUTOMATION_DIR / f"config.project{index}.generated.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        report["config_path"] = str(config_path)

        if extract_only:
            report["status"] = "extract_only"
            report["bidder_count"] = len(config.get("tokens", {}).get("bidders", []))
            report["publish_upload_files"] = config.get("publish", {}).get("upload_files")
            report["bidders_preview"] = [
                {
                    "name": b.get("name"),
                    "token_note": b.get("token_note"),
                    "register": b.get("register"),
                    "submit_file": (b.get("submit") or {}).get("upload_files"),
                }
                for b in config.get("tokens", {}).get("bidders", [])
            ]
            return report

        result = run_flow(config, dry_run=False)
        report["project_id"] = result.get("project_id")
        report["section_id"] = result.get("section_id")
        report["bidder_count"] = len(result.get("bidders") or [])
        report["bidders"] = bidder_summary(result.get("bidders") or [])

        failed = [b for b in report["bidders"] if b.get("status") == "failed"]
        if failed and len(failed) < report["bidder_count"]:
            report["status"] = "partial"
        elif failed:
            report["status"] = "failed"
        else:
            report["status"] = "success"
        report["flow_result"] = result
    except ZjgjApiError as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        report["api_payload"] = exc.payload
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
    return report


def main() -> None:
    extract_only = "--extract-only" in sys.argv
    base_config = load_config(BASE_CONFIG)
    reports: list[dict[str, Any]] = []

    for index, project_dir in enumerate(PROJECT_DIRS, start=1):
        print(f"\n{'=' * 60}\n项目集 {index}: {project_dir}\n{'=' * 60}", flush=True)
        report = run_one(index, project_dir, base_config, extract_only=extract_only)
        reports.append(report)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str), flush=True)

    out_path = AUTOMATION_DIR / ("batch_extract_report.json" if extract_only else "batch_run_report.json")
    out_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nreport saved: {out_path}", flush=True)

    print("\n=== SUMMARY ===")
    for r in reports:
        pid = r.get("project_id", "-")
        name = (r.get("project_name") or "")[:40]
        bidders = r.get("bidder_count", r.get("tender_file_count", "-"))
        status = r.get("status")
        warn = " [TOKEN REUSE]" if r.get("token_reuse_warning") else ""
        skip = f" [skipped {len(r.get('skipped_files') or [])} files]" if r.get("skipped_files") else ""
        print(f"  项目集{r['set_index']}: {status:12} project_id={pid} bidders={bidders} {name}{warn}{skip}")


if __name__ == "__main__":
    main()

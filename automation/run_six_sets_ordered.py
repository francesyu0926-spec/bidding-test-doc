#!/usr/bin/env python3
"""Run full bidding flow (publish→decrypt) for 项目集 4,5,6,1,2,3 in order."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from run_bid_opening import DEFAULT_EXPERTS, run_project as run_bid_open
from run_project_folder import build_project_config, scan_project_folder
from run_three_stage_flow import apply_publish_times, load_config, normalize_experts, run_flow
from zjgj_client import ZjgjApiError

MAX_FILE_BYTES = 150 * 1024 * 1024
AUTOMATION_DIR = Path(__file__).resolve().parent
BASE_CONFIG = AUTOMATION_DIR / "config.project4.base.json"

# User order: 4,5,6,1,2,3
SET_ORDER = [4, 5, 6, 1, 2, 3]
PROJECT_DIRS = {i: Path(rf"d:\文件\客户项目文件\项目集\{i}") for i in range(1, 7)}


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


def run_one(
    set_index: int,
    project_dir: Path,
    base_config: dict[str, Any],
    *,
    extract_only: bool,
    skip_flow: bool,
    skip_open: bool,
    wait_open_sec: int,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "set_index": set_index,
        "folder": str(project_dir),
        "status": "pending",
        "stages": {},
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
        report["publish_times"] = {
            "start_time": config["publish"].get("start_time"),
            "file_start_time": config["publish"].get("file_start_time"),
            "file_end_time": config["publish"].get("file_end_time"),
        }

        config_path = AUTOMATION_DIR / f"config.project{set_index}.generated.json"
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

        if not skip_flow:
            result = run_flow(config, dry_run=False)
            report["project_id"] = result.get("project_id")
            report["section_id"] = result.get("section_id")
            report["bidder_count"] = len(result.get("bidders") or [])
            report["bidders"] = bidder_summary(result.get("bidders") or [])
            report["stages"]["publish_register_pay_submit"] = {
                "ok": not any(b.get("status") == "failed" for b in report["bidders"]),
                "project_id": report["project_id"],
                "section_id": report["section_id"],
            }

            failed = [b for b in report["bidders"] if b.get("status") == "failed"]
            if failed and len(failed) < report["bidder_count"]:
                report["status"] = "partial_flow"
            elif failed:
                report["status"] = "failed_flow"
            else:
                report["status"] = "flow_ok"

        if skip_open or not report.get("project_id"):
            return report

        open_config: dict[str, Any] = {
            "verify_ssl": False,
            "flow": {"expert_agree_invite": True},
            "expert_invite": {"enabled": True},
            "expert_actions": {
                "confirm": True,
                "sign": True,
                "wait_invite_timeout_sec": 15,
                "poll_sec": 2,
            },
        }
        bidders_for_open = [
            {"name": b.get("name"), "token": b["token"], "register": b.get("register")}
            for b in config.get("tokens", {}).get("bidders", [])
        ]
        open_result = run_bid_open(
            {"project_id": report["project_id"], "section_id": report["section_id"], "set": set_index},
            base_url=config["base_url"],
            pm_token=config["tokens"]["project_manager"],
            config=open_config,
            experts=DEFAULT_EXPERTS,
            bidders=bidders_for_open,
            decrypt_password=config.get("submit", {}).get("password", "123456"),
            force_times=False,
            wait_open_sec=wait_open_sec,
        )
        report["bid_opening"] = open_result
        decrypt_ops = next(
            (op for op in open_result.get("operations", []) if op.get("action") == "bidder_decrypt"),
            {},
        )
        decrypt_results = decrypt_ops.get("results") or []
        report["decrypt"] = {
            "total": len(decrypt_results),
            "ok": sum(1 for d in decrypt_results if d.get("ok")),
            "results": decrypt_results,
        }
        report["section_state"] = (open_result.get("final") or {}).get("section_state")
        report["section_state_label"] = (open_result.get("final") or {}).get("section_state_label")

        for op in open_result.get("operations", []):
            action = op.get("action")
            if action in (
                "review_config",
                "expert_invite",
                "expert_agree_invite",
                "expert_sign",
                "expert_confirm_sign",
                "wait_section_open",
                "wait_start_time",
                "publish_change_times",
            ):
                report["stages"][action] = op

        decrypt_ok = report["decrypt"]["ok"] == report["decrypt"]["total"] and report["decrypt"]["total"] > 0
        if open_result.get("success") and decrypt_ok:
            report["status"] = "success"
        elif report.get("status") == "flow_ok" or report.get("status") == "partial_flow":
            report["status"] = "decrypt_partial" if decrypt_ok else "decrypt_failed"
        report["stages"]["decrypt"] = {"ok": decrypt_ok, **report["decrypt"]}

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
    skip_flow = "--skip-flow" in sys.argv
    skip_open = "--skip-open" in sys.argv
    wait_open_sec = 180
    for arg in sys.argv:
        if arg.startswith("--wait-open-sec="):
            wait_open_sec = int(arg.split("=", 1)[1])

    base_config = load_config(BASE_CONFIG)
    reports: list[dict[str, Any]] = []

    for set_index in SET_ORDER:
        project_dir = PROJECT_DIRS[set_index]
        print(f"\n{'=' * 60}\n项目集 {set_index}: {project_dir}\n{'=' * 60}", flush=True)
        report = run_one(
            set_index,
            project_dir,
            base_config,
            extract_only=extract_only,
            skip_flow=skip_flow,
            skip_open=skip_open or extract_only,
            wait_open_sec=wait_open_sec,
        )
        reports.append(report)
        slim = {k: v for k, v in report.items() if k not in ("flow_result", "bid_opening")}
        print(json.dumps(slim, ensure_ascii=False, indent=2, default=str), flush=True)

    suffix = "extract" if extract_only else "full"
    out_path = AUTOMATION_DIR / f"six_sets_{suffix}_report.json"
    out_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nreport saved: {out_path}", flush=True)

    print("\n=== SUMMARY ===")
    for r in reports:
        pid = r.get("project_id", "-")
        sid = r.get("section_id", "-")
        dec = r.get("decrypt") or {}
        dec_str = f"{dec.get('ok', '-')}/{dec.get('total', '-')}" if dec else "-"
        sec = r.get("section_state_label") or r.get("section_state") or "-"
        name = (r.get("project_name") or "")[:35]
        warn = " [TOKEN REUSE]" if r.get("token_reuse_warning") else ""
        print(
            f"  项目集{r['set_index']}: {r.get('status', '?'):14} "
            f"pid={pid} sid={sid} decrypt={dec_str} open={sec} {name}{warn}"
        )


if __name__ == "__main__":
    main()

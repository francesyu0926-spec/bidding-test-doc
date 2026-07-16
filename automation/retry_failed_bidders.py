#!/usr/bin/env python3
"""Retry failed bidder flows (expired token D) on existing projects."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from run_bid_opening import build_publish_change_payload
from run_three_stage_flow import load_config, make_client, run_flow
from zjgj_client import ZjgjApiError

NEW_TOKEN = "f23debcfcc877c030c0a84f5bf18a472"
OLD_TOKEN = "080af50de7f32dacc24e02bb90be41b9"
DECRYPT_PASSWORD = "123456"
AUTOMATION_DIR = Path(__file__).resolve().parent

# (label, project_id, section_id, config_path, bidder_indices_to_retry)
RETRY_JOBS = [
    ("six_sets set4", 2066, 1896, "config.project4.generated.json", [3]),
    ("six_sets set5-4th", 2072, 1901, "config.project5.generated.json", [3]),
    ("six_sets set5-5th", 2072, 1901, "config.project5.generated.json", [4]),
    ("six_sets set2", 2076, 1905, "config.project2.generated.json", [3]),
    ("batch set4", 2073, 1902, "config.project4.generated.json", [3]),
    ("batch set5-4th", 2070, 1899, "config.project5.generated.json", [3]),
    ("batch set5-5th", 2070, 1899, "config.project5.generated.json", [4]),
    ("batch set2", 2067, 1897, "config.project2.generated.json", [3]),
]


def extend_registration_window(source_config: dict, project_id: int) -> dict | None:
    """Extend file_end_time into the future so registration can proceed."""
    pm = make_client(
        source_config["base_url"],
        source_config["tokens"]["project_manager"],
        source_config,
    )
    data = pm.get_publicity_project_info(project_id).get("data") or {}
    now = datetime.now()
    new_file_end = (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    new_start = data.get("start_time")
    start_dt = None
    if new_start:
        try:
            start_dt = datetime.strptime(str(new_start)[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    if start_dt and start_dt > now:
        new_start = (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    payload = build_publish_change_payload(pm, project_id, start_time=new_start or now.strftime("%Y-%m-%d %H:%M:%S"), file_end_time=new_file_end)
    resp = pm.publish_change_project(project_id, payload)
    return {"file_end_time": new_file_end, "start_time": new_start, "msg": resp.get("msg")}


def verify_new_token(base_config: dict, project_checks: list[tuple[int, int]]) -> dict:
    base_url = base_config["base_url"]
    client = make_client(base_url, NEW_TOKEN, base_config)
    profile = client.get_user_profile()
    data = profile.get("data") or {}
    result: dict = {
        "token": NEW_TOKEN,
        "profile_ok": profile.get("code") == 1,
        "mobile": data.get("mobile"),
        "nickname": data.get("nickname"),
        "status_name": data.get("status_name"),
        "user_type": data.get("user_type"),
        "check_register": {},
    }
    for project_id, section_id in project_checks:
        key = f"{project_id}/{section_id}"
        try:
            check = client.check_register(project_id, section_id)
            result["check_register"][key] = {"ok": True, "response": check}
        except ZjgjApiError as exc:
            result["check_register"][key] = {"ok": False, "error": str(exc), "payload": exc.payload}
    return result


def build_retry_config(
    source_config: dict,
    *,
    project_id: int,
    section_id: int,
    bidder_indices: list[int],
) -> dict:
    bidders = source_config["tokens"]["bidders"]
    retry_bidders = []
    for idx in bidder_indices:
        bidder = dict(bidders[idx])
        # 4th slot (index 3): always use new token replacing expired D
        if idx == 3:
            bidder["token"] = NEW_TOKEN
            bidder["name"] = bidder.get("name", "").replace(OLD_TOKEN[:8], NEW_TOKEN[:8])
            if "13729483065" in bidder.get("name", ""):
                mobile = None  # resolved at runtime
        # 5th slot (index 4): token reuse failed; try new token (may fail if 4th used same token)
        elif idx == 4:
            bidder["token"] = NEW_TOKEN
            bidder["name"] = f"投标人-新token-5th-{bidder.get('register', {}).get('company_name', '')[:8]}"
        retry_bidders.append(bidder)

    return {
        "base_url": source_config["base_url"],
        "verify_ssl": source_config.get("verify_ssl", False),
        "existing_project": {"project_id": project_id, "section_id": section_id},
        "tokens": {
            "project_manager": source_config["tokens"]["project_manager"],
            "bidders": retry_bidders,
        },
        "publish": {"is_audit": source_config.get("publish", {}).get("is_audit", 0)},
        "register": source_config.get("register", {}),
        "payment": source_config.get("payment", {}),
        "submit": source_config.get("submit", {}),
        "flow": {"experts": False, "stages": ["register", "payment", "submit"]},
        "experts": {"enabled": False},
    }


def decrypt_tender_ids(
    source_config: dict,
    project_id: int,
    section_id: int,
    tender_ids: list[int],
    token: str = NEW_TOKEN,
) -> list[dict]:
    pm = make_client(
        source_config["base_url"],
        source_config["tokens"]["project_manager"],
        source_config,
    )
    client = make_client(source_config["base_url"], token, source_config)
    results = []
    for tender_id in tender_ids:
        entry = {"tender_id": tender_id, "token": token[:8]}
        try:
            decrypt_resp = client.decrypt_and_sign_tender(
                project_id,
                tender_id,
                section_id,
                DECRYPT_PASSWORD,
            )
            entry["ok"] = bool(decrypt_resp.get("sign"))
            entry["msg"] = (decrypt_resp.get("password") or {}).get("msg")
            entry["file_id"] = decrypt_resp.get("file_id")
            entry["sign"] = decrypt_resp.get("sign")
            if not entry["ok"]:
                entry["error"] = "signature step did not populate sign"
        except ZjgjApiError as exc:
            entry["ok"] = False
            entry["error"] = str(exc)
        results.append(entry)
    return results


def main() -> None:
    base_config = load_config(AUTOMATION_DIR / "config.project4.base.json")
    project_checks = list({(j[1], j[2]) for j in RETRY_JOBS})
    token_validation = verify_new_token(base_config, project_checks)
    print("=== Token validation ===")
    print(json.dumps(token_validation, ensure_ascii=False, indent=2))

    if not token_validation.get("profile_ok"):
        print("New token validation failed; aborting.", file=sys.stderr)
        sys.exit(1)

    report: list[dict] = []
    for label, project_id, section_id, config_name, indices in RETRY_JOBS:
        print(f"\n=== Retry: {label} project={project_id} section={section_id} indices={indices} ===")
        source = load_config(AUTOMATION_DIR / config_name)
        retry_cfg = build_retry_config(source, project_id=project_id, section_id=section_id, bidder_indices=indices)
        entry: dict = {
            "label": label,
            "project_id": project_id,
            "section_id": section_id,
            "bidder_indices": indices,
            "companies": [source["tokens"]["bidders"][i].get("register", {}).get("company_name") for i in indices],
        }
        if label == "six_sets set2":
            entry["skipped"] = "already completed in prior run"
            report.append(entry)
            print(json.dumps(entry, ensure_ascii=False, indent=2, default=str))
            continue
        try:
            time_ext = extend_registration_window(source, project_id)
            if time_ext:
                entry["time_extension"] = time_ext
                print(f"Extended registration window: file_end={time_ext['file_end_time']}")
            result = run_flow(retry_cfg, dry_run=False)
            bidders_out = []
            for i, b in enumerate(result.get("bidders", [])):
                src_idx = indices[i] if i < len(indices) else None
                company = source["tokens"]["bidders"][src_idx].get("register", {}).get("company_name") if src_idx is not None else None
                bidders_out.append({
                    "company": company,
                    "name": b.get("name"),
                    "mobile": b.get("mobile"),
                    "register_id": b.get("register_id"),
                    "tender_id": b.get("tender_id"),
                    "pay_state": b.get("pay_state"),
                    "pay_state_name": b.get("pay_state_name"),
                    "status": "failed" if b.get("error") else "submitted",
                    "error": b.get("error"),
                    "register_company": company,
                })
            entry["bidders"] = bidders_out
            entry["flow_ok"] = all(x["status"] == "submitted" for x in bidders_out)

            # Decrypt only newly submitted bidders
            new_ok = [x for x in bidders_out if x["status"] == "submitted" and x.get("tender_id")]
            if new_ok:
                tender_ids = [int(x["tender_id"]) for x in new_ok]
                decrypt_results = decrypt_tender_ids(source, project_id, section_id, tender_ids)
                for dr, bo in zip(decrypt_results, new_ok):
                    dr["company"] = bo.get("company")
                entry["decrypt"] = decrypt_results
                entry["decrypt_ok"] = all(r.get("ok") for r in decrypt_results)
        except Exception as exc:
            entry["flow_ok"] = False
            entry["error"] = str(exc)
        report.append(entry)
        print(json.dumps(entry, ensure_ascii=False, indent=2, default=str))

    out_path = AUTOMATION_DIR / "retry_failed_bidders_report.json"
    full_report = {"token_validation": token_validation, "config_updated": "config.project4.base.json", "retries": report}
    out_path.write_text(json.dumps(full_report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nReport written: {out_path}")


if __name__ == "__main__":
    main()

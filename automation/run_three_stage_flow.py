#!/usr/bin/env python3
"""Run ZJGJ three-stage bidding flow against a live environment.

Stages:
1. Publish publicity project (project manager token)
2. Register and pay (bidder token)
3. Submit tender files (bidder token)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from zjgj_client import ZjgjApiError, ZjgjClient

REGISTER_STATUS_COMPLETED = 3


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_publish_payload(config: dict) -> dict:
    publish = config["publish"]
    now = datetime.now()
    return {
        "project_no": publish.get("project_no") or f"AUTO-{now.strftime('%Y%m%d%H%M%S')}",
        "title": publish["title"],
        "cate_id": publish["cate_id"],
        "company_id": publish["company_id"],
        "pattern_id": publish["pattern_id"],
        "industry_id": publish.get("industry_id", 1),
        "username": publish["username"],
        "address": publish["address"],
        "region": publish.get("region", "140000,140100"),
        "is_audit": publish.get("is_audit", 0),
        "is_min": publish.get("is_min", 2),
        "is_bid_section": publish.get("is_bid_section", 0),
        "start_time": publish.get("start_time") or (now + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"),
        "file_start_time": publish.get("file_start_time") or now.strftime("%Y-%m-%d %H:%M:%S"),
        "file_end_time": publish.get("file_end_time") or (now + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
        "file_price": publish.get("file_price", "1.00"),
        "platform_price": publish.get("platform_price", "1.00"),
        "deposit": publish.get("deposit", "0.00"),
        "price": publish.get("price", "0.00"),
        "intro": publish.get("intro", "<p>自动化测试项目</p>"),
    }


def extract_id(payload: dict, *keys: str) -> int | None:
    data = payload.get("data") or payload.get("result") or {}
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] is not None:
                return int(data[key])
    return None


def wait_register_completed(client: ZjgjClient, register_id: int, timeout_sec: int, poll_sec: int) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        info = client.get_register_info(register_id)
        data = info.get("data") or {}
        status = data.get("status")
        print(f"register {register_id} status={status}")
        if status == REGISTER_STATUS_COMPLETED:
            return info
        time.sleep(poll_sec)
    raise TimeoutError(f"register {register_id} did not reach completed status within {timeout_sec}s")


def run_health_check(base_url: str) -> None:
    client = ZjgjClient(base_url=base_url)
    index = client.health_check()
    projects = client.list_public_projects(page=1, limit=3)
    print("health_check: ok")
    print(f"carousel_count={len((index.get('data') or {}).get('carousel', []))}")
    print(f"public_project_count={(projects.get('data') or {}).get('count')}")


def run_flow(config: dict, *, dry_run: bool) -> dict:
    base_url = config["base_url"]
    pm_token = config.get("tokens", {}).get("project_manager")
    bidder_token = config.get("tokens", {}).get("bidder")

    result: dict = {"base_url": base_url, "dry_run": dry_run}

    if dry_run:
        print("[dry-run] validating tokens and dictionaries only")
        if not pm_token or not bidder_token:
            raise SystemExit("dry-run still requires tokens.project_manager and tokens.bidder")
        pm = ZjgjClient(base_url=base_url, token=pm_token)
        bidder = ZjgjClient(base_url=base_url, token=bidder_token)
        result["pm_cate"] = pm.get_publicity_cate()
        result["pm_pattern"] = pm.get_publicity_pattern()
        result["bidder_my_tenders"] = bidder.list_my_tenders(page=1, limit=1)
        return result

    if not pm_token or not bidder_token:
        raise SystemExit(
            "Missing tokens. This environment does not expose /api/login/check; "
            "copy Token from the mini program and set tokens.project_manager / tokens.bidder."
        )

    pm = ZjgjClient(base_url=base_url, token=pm_token)
    bidder = ZjgjClient(base_url=base_url, token=bidder_token)

    # Stage 1
    publish_payload = build_publish_payload(config)
    create_resp = pm.create_publicity_project(publish_payload)
    project_id = extract_id(create_resp, "project_id", "id")
    if project_id is None:
        raise ZjgjApiError(-1, "create publicity succeeded but project_id missing", create_resp)
    result["project_id"] = project_id
    print(f"stage1 publish ok: project_id={project_id}")

    project_info = pm.request(
        "GET",
        "api/publicity/projectInfo",
        params={"project_id": project_id},
        require_auth=True,
    )
    sections = (project_info.get("data") or {}).get("sections") or []
    if not sections:
        raise ZjgjApiError(-1, "project has no sections", project_info)
    section_id = int(sections[0]["id"])
    result["section_id"] = section_id

    review_cfg = config.get("review")
    if review_cfg:
        review_payload = {"project_id": project_id, **review_cfg}
        pm.save_publicity_review(review_payload)
        print("stage1 review config saved")

    # Stage 2
    register_payload = {
        "project_id": project_id,
        "section_id": section_id,
        **config.get("register", {}),
    }
    bidder.check_register(project_id, section_id)
    register_resp = bidder.register_project(register_payload)
    register_id = extract_id(register_resp, "id", "register_id")
    if register_id is None:
        raise ZjgjApiError(-1, "register succeeded but register_id missing", register_resp)
    result["register_id"] = register_id
    print(f"stage2 register ok: register_id={register_id}")

    publish_cfg = config.get("publish", {})
    if publish_cfg.get("is_audit", 0) == 1:
        pm.audit_register(register_id, status=1)
        print("stage2 register audit approved")

    pay_cfg = config.get("payment", {})
    if pay_cfg.get("enabled", True):
        pay_payload = {
            "id": register_id,
            "pay_way": pay_cfg.get("pay_way", "bank"),
            **{k: v for k, v in pay_cfg.items() if k not in {"enabled", "pay_way", "wait_timeout_sec", "poll_sec"}},
        }
        pay_resp = bidder.pay_register(pay_payload, use_v3=pay_cfg.get("use_v3", True))
        result["payment"] = pay_resp
        print("stage2 payment request sent")

        wait_timeout = int(pay_cfg.get("wait_timeout_sec", 0))
        if wait_timeout > 0:
            wait_register_completed(
                bidder,
                register_id,
                timeout_sec=wait_timeout,
                poll_sec=int(pay_cfg.get("poll_sec", 5)),
            )
            print("stage2 payment completed")
    else:
        print("stage2 payment skipped by config")

    # Stage 3
    tender_list = bidder.list_my_tenders(page=1, limit=50)
    tender_id = None
    for item in (tender_list.get("data") or {}).get("list", []):
        if int(item.get("project_id", -1)) == project_id:
            tender_id = int(item["id"])
            break
    if tender_id is None:
        tender_detail = bidder.get_tender_project(project_id, section_id)
        tender_id = extract_id(tender_detail, "tender_id", "id")
    if tender_id is None:
        raise ZjgjApiError(-1, "unable to resolve tender_id after registration", tender_list)
    result["tender_id"] = tender_id

    submit_cfg = config.get("submit", {})
    files = submit_cfg.get("files")
    if not files:
        upload_path = submit_cfg.get("upload_file")
        if not upload_path:
            raise SystemExit("submit.files or submit.upload_file is required for stage 3")
        upload_resp = bidder.upload_image(upload_path)
        uploaded = (upload_resp.get("data") or upload_resp.get("result") or {}).get("url")
        if not uploaded:
            raise ZjgjApiError(-1, "upload succeeded but file url missing", upload_resp)
        files = json.dumps([{"name": Path(upload_path).name, "url": uploaded}])

    submit_payload = {
        "tender_id": tender_id,
        "section_id": section_id,
        "apply_id": register_id,
        "files": files,
        **{k: v for k, v in submit_cfg.items() if k not in {"files", "upload_file"}},
    }
    submit_resp = bidder.submit_tender_file(submit_payload)
    result["submit"] = submit_resp
    print("stage3 submit ok")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="ZJGJ three-stage bidding automation")
    default_config = Path(__file__).resolve().parent / "config.example.json"
    parser.add_argument("--config", default=str(default_config), help="Path to JSON config")
    parser.add_argument("--health-check", action="store_true", help="Only verify public API connectivity")
    parser.add_argument("--dry-run", action="store_true", help="Validate tokens without mutating data")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")

    config = load_config(config_path)
    base_url = config.get("base_url", "https://www.bidding.shanxiguandian.com")

    if args.health_check:
        run_health_check(base_url)
        return

    try:
        result = run_flow(config, dry_run=args.dry_run)
    except ZjgjApiError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        if exc.payload is not None:
            print(json.dumps(exc.payload, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

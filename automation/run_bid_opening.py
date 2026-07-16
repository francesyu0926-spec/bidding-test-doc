#!/usr/bin/env python3
"""Execute bid-opening stage operations for existing ZJGJ projects.

Workflow (aligned with ZJGJ backend source):
1. Wait until publish start_time (开标时间) is reached
2. PM: save review/scoring table (saveReview) before expert invite
3. PM: invite experts (addExpert) if none assigned
4. PM: pass expert audit — POST api/manage/addExpert with check=1 (通过审核)
5. Optional: experts agree invite (api/expert/confirm) if expert_actions.confirm=true
6. Poll section.state until bid opened
7. Experts: sign in (api/expert/sign; invite_id from inviteInfo.users[].id)
8. Bidders: 签字解密 via api/tender/password then api/tender/signature (sets sign)
9. Report status from manage/myList, section.state, getProgress

Use --force-times to backdate start/file_end into the past (legacy; near-future publish is preferred).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from run_three_stage_flow import (
    audit_all_expert_invites,
    build_expert_invite_payload,
    confirm_all_expert_invites,
    expert_agree_invite_enabled,
    invite_project_experts,
    make_client,
    normalize_experts,
    normalize_publish_images,
    parse_time,
    resolve_expert_uid,
    run_expert_sign_all,
    save_project_review_config,
    section_state,
    wait_for_section_open,
    wait_until_start_time,
)
from zjgj_client import ZjgjApiError, ZjgjClient

DEFAULT_EXPERTS = [
    {
        "name": "专家-测试peng",
        "token": "2dc7d42b334a80f5a9f468804b4c804e",
        "expert_id": 30,
        "uid": 11286,
        "invite": {"major_ids": "916,917"},
    },
    {
        "name": "专家-数据廖",
        "token": "1961087d90c565e4620b9a98b69a8b91",
        "expert_id": 23,
        "uid": 7882,
        "invite": {"major_ids": "221"},
    },
]

DEFAULT_PROJECTS = [
    {"project_id": 2060, "section_id": 1890, "set": 3},
    {"project_id": 2061, "section_id": 1891, "set": 4},
    {"project_id": 2062, "section_id": 1892, "set": 5},
    {"project_id": 2063, "section_id": 1893, "set": 6},
]

DEFAULT_BIDDERS = [
    {"name": "bidder-A", "token": "e016124f0ee365edbe1440d91f9857e3"},
    {"name": "bidder-B", "token": "7e8a8eb2eb79d2e50dc62765c4bef368"},
    {"name": "bidder-C", "token": "6a717729bb9d4e75677db82ba7aae838"},
    {"name": "bidder-D", "token": "080af50de7f32dacc24e02bb90be41b9"},
]

# Known apply_id -> bidder token order per project set (round-robin token reuse).
PROJECT_BIDDER_TOKENS: dict[int, list[str]] = {
    2060: [DEFAULT_BIDDERS[0]["token"], DEFAULT_BIDDERS[1]["token"], DEFAULT_BIDDERS[2]["token"]],
    2061: [b["token"] for b in DEFAULT_BIDDERS],
    2062: [b["token"] for b in DEFAULT_BIDDERS],
    2063: [DEFAULT_BIDDERS[0]["token"], DEFAULT_BIDDERS[1]["token"], DEFAULT_BIDDERS[2]["token"]],
}

STATUS_LABELS = {1: "已开标/评审中", 2: "投标中", 3: "评审后续", 4: "已定标/废标"}
SECTION_STATE_LABELS = {1: "已开标", 2: "投标中"}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def manage_status(pm: ZjgjClient, project_id: int, section_id: int) -> int | None:
    listing = pm.request("GET", "api/manage/myList", params={"page": 1, "limit": 200}, require_auth=True)
    for item in (listing.get("data") or {}).get("list", []):
        if int(item.get("project_id", -1)) == project_id and int(item.get("section_id", section_id)) == section_id:
            status = item.get("status")
            return int(status) if status is not None else None
    return None


def has_expert_invite(pm: ZjgjClient, project_id: int, section_id: int) -> bool:
    invite = pm.get_manage_invite_info(project_id, section_id).get("data") or {}
    info = invite.get("info")
    if isinstance(info, list):
        return bool(info)
    if isinstance(info, dict):
        return bool(info.get("id") or info.get("users"))
    return False


def build_publish_change_payload(pm: ZjgjClient, project_id: int, *, start_time: str, file_end_time: str) -> dict[str, Any]:
    data = pm.get_publicity_project_info(project_id).get("data") or {}
    if not data:
        raise ZjgjApiError(-1, f"project {project_id} not found", None)
    payload = {
        "id": project_id,
        "company_id": data.get("company_id"),
        "project_no": data.get("project_no"),
        "title": data.get("title"),
        "cate_id": data.get("cate_id"),
        "username": data.get("username"),
        "address": data.get("address"),
        "pattern_id": data.get("pattern_id"),
        "start_time": start_time,
        "file_start_time": data.get("file_start_time"),
        "file_end_time": file_end_time,
        "platform_price": data.get("platform_price", "1.00"),
        "file_price": data.get("file_price", "1.00"),
        "is_bid_section": data.get("is_bid_section", 0),
        "deposit": data.get("deposit", "0.00"),
        "intro": data.get("intro") or f"<p>{data.get('title', '')}</p>",
        "images": normalize_publish_images(data.get("images")) or "[]",
        "is_min": data.get("is_min", 2),
        "is_audit": data.get("is_audit", 0),
        "region": data.get("region"),
        "industry_id": data.get("industry_id", 1),
    }
    if data.get("is_bid_section") == 1 and data.get("sections"):
        payload["sections"] = data.get("sections")
    return payload


def advance_times_if_needed(pm: ZjgjClient, project_id: int, *, force: bool) -> dict[str, Any] | None:
    data = pm.get_publicity_project_info(project_id).get("data") or {}
    now = datetime.now()
    start_dt = parse_time(data.get("start_time"))
    file_end_dt = parse_time(data.get("file_end_time"))
    needs_start = force or (start_dt is not None and start_dt > now)
    needs_file_end = force or (file_end_dt is not None and file_end_dt > now)
    if not needs_start and not needs_file_end:
        return None

    new_start = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    new_file_end = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    if not needs_start:
        new_start = data.get("start_time")
    if not needs_file_end:
        new_file_end = data.get("file_end_time")

    payload = build_publish_change_payload(pm, project_id, start_time=new_start, file_end_time=new_file_end)
    resp = pm.publish_change_project(project_id, payload)
    return {
        "start_time": new_start,
        "file_end_time": new_file_end,
        "response": resp.get("msg"),
    }


def list_project_tenders(pm: ZjgjClient, project_id: int, section_id: int) -> list[dict[str, Any]]:
    resp = pm.request(
        "GET",
        "api/manage/getList",
        params={"project_id": project_id, "section_id": section_id, "page": 1, "limit": 50},
        require_auth=True,
    )
    return (resp.get("data") or {}).get("list") or []


def bidder_token_for_tender(
    bidders: list[dict[str, Any]],
    tender_id: int,
    pm: ZjgjClient,
    project_id: int,
    section_id: int,
) -> str | None:
    if project_id in PROJECT_BIDDER_TOKENS:
        tenders = sorted(list_project_tenders(pm, project_id, section_id), key=lambda x: int(x.get("apply_id", 0)))
        tokens = PROJECT_BIDDER_TOKENS[project_id]
        for index, item in enumerate(tenders):
            if int(item.get("tender_id", -1)) == tender_id and index < len(tokens):
                return tokens[index]

    listing = pm.list_project_registers(project_id)
    register_by_id = {
        int(item["id"]): item for item in (listing.get("data") or {}).get("list", []) if item.get("id") is not None
    }
    apply_id = None
    for item in list_project_tenders(pm, project_id, section_id):
        if int(item.get("tender_id", -1)) == tender_id:
            apply_id = item.get("apply_id")
            break
    if apply_id is None:
        return None
    reg = register_by_id.get(int(apply_id)) or {}
    phone = reg.get("contact_phone") or reg.get("mobile")
    if phone:
        for bidder in bidders:
            reg_cfg = bidder.get("register") or {}
            if str(reg_cfg.get("contact_phone") or reg_cfg.get("mobile") or "") == str(phone):
                return bidder["token"]
    return None


def decrypt_tenders(
    pm: ZjgjClient,
    *,
    project_id: int,
    section_id: int,
    bidders: list[dict[str, Any]],
    password: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in list_project_tenders(pm, project_id, section_id):
        tender_id = int(item["tender_id"])
        token = bidder_token_for_tender(bidders, tender_id, pm, project_id, section_id)
        label = next((b["name"] for b in bidders if b["token"] == token), f"tender-{tender_id}")
        entry: dict[str, Any] = {"tender_id": tender_id, "bidder": label, "company": item.get("company_name")}
        if token is None:
            entry["error"] = "bidder token not resolved"
            results.append(entry)
            continue
        client = make_client(pm.base_url.rstrip("/"), token, {"verify_ssl": pm.verify_ssl})
        try:
            decrypt_resp = client.decrypt_and_sign_tender(
                project_id,
                tender_id,
                section_id,
                password,
            )
            entry["ok"] = bool(decrypt_resp.get("sign"))
            entry["msg"] = (decrypt_resp.get("password") or {}).get("msg")
            entry["file_id"] = decrypt_resp.get("file_id")
            entry["sign"] = decrypt_resp.get("sign")
            sig_resp = decrypt_resp.get("signature")
            if sig_resp:
                entry["signature_msg"] = sig_resp.get("msg")
            if not entry["ok"]:
                entry["error"] = "signature step did not populate sign"
        except ZjgjApiError as exc:
            entry["ok"] = False
            entry["error"] = str(exc)
        results.append(entry)
    return results


def run_project(
    spec: dict[str, Any],
    *,
    base_url: str,
    pm_token: str,
    config: dict[str, Any],
    experts: list[dict[str, Any]],
    bidders: list[dict[str, Any]],
    decrypt_password: str,
    force_times: bool,
    wait_open_sec: int,
) -> dict[str, Any]:
    project_id = int(spec["project_id"])
    section_id = int(spec["section_id"])
    pm = make_client(base_url, pm_token, config)
    result: dict[str, Any] = {
        "project_id": project_id,
        "section_id": section_id,
        "set": spec.get("set"),
        "operations": [],
        "errors": [],
    }

    info = pm.get_publicity_project_info(project_id).get("data") or {}
    result["title"] = info.get("title")
    result["initial"] = {
        "start_time": info.get("start_time"),
        "file_end_time": info.get("file_end_time"),
        "section_state": section_state(pm, project_id),
        "manage_status": manage_status(pm, project_id, section_id),
    }

    start_time_str = info.get("start_time")

    if force_times:
        try:
            time_change = advance_times_if_needed(pm, project_id, force=force_times)
            if time_change:
                result["operations"].append({"action": "publish_change_times", **time_change})
                print(f"[{project_id}] times advanced: start={time_change['start_time']}")
        except ZjgjApiError as exc:
            result["errors"].append(f"publish_change_times: {exc}")
            print(f"[{project_id}] time advance failed: {exc}")
    else:
        wait_until_start_time(start_time_str, poll_sec=5, label=str(project_id))
        result["operations"].append({"action": "wait_start_time", "start_time": start_time_str})

    if experts:
        try:
            review_resp = save_project_review_config(pm, project_id, section_id, config)
            result["operations"].append(
                {"action": "review_config", "ok": True, "msg": (review_resp or {}).get("msg")}
                if review_resp is not None
                else {"action": "review_config", "skipped": True, "reason": "disabled"}
            )
        except ZjgjApiError as exc:
            result["errors"].append(f"review_config: {exc}")
            print(f"[{project_id}] review config failed: {exc}")

        if not has_expert_invite(pm, project_id, section_id):
            try:
                invite_resp = invite_project_experts(
                    experts,
                    base_url=base_url,
                    pm=pm,
                    project_id=project_id,
                    section_id=section_id,
                    config=config,
                )
                result["operations"].append({"action": "expert_invite", "ok": True, "msg": (invite_resp or {}).get("msg")})
                print(f"[{project_id}] experts invited")
            except ZjgjApiError as exc:
                result["errors"].append(f"expert_invite: {exc}")
                print(f"[{project_id}] expert invite failed: {exc}")
        else:
            result["operations"].append({"action": "expert_invite", "skipped": True, "reason": "already invited"})
            print(f"[{project_id}] expert invite skipped (exists)")

        try:
            audit_result = audit_all_expert_invites(
                project_id,
                section_id,
                experts,
                base_url=base_url,
                config=config,
                pm=pm,
            )
            result["operations"].append({"action": "expert_audit", **audit_result})
            if audit_result.get("ok"):
                print(f"[{project_id}] stage: expert audit passed")
        except ZjgjApiError as exc:
            result["errors"].append(f"expert_audit: {exc}")
            print(f"[{project_id}] expert audit failed: {exc}")

        if expert_agree_invite_enabled(config):
            try:
                confirm_results = confirm_all_expert_invites(
                    project_id,
                    section_id,
                    experts,
                    base_url=base_url,
                    config=config,
                    pm=pm,
                    project_title=info.get("title"),
                )
                result["operations"].append({"action": "expert_agree_invite", "experts": confirm_results})
            except ZjgjApiError as exc:
                result["errors"].append(f"expert_agree_invite: {exc}")
                print(f"[{project_id}] expert agree invite failed: {exc}")

    if section_state(pm, project_id) != 1 and wait_open_sec > 0:
        print(f"[{project_id}] polling section open...")
        opened = wait_for_section_open(pm, project_id, timeout_sec=wait_open_sec, poll_sec=5)
        result["operations"].append({"action": "wait_section_open", "opened": opened, "wait_sec": wait_open_sec})
        if not opened:
            result["errors"].append("section still not opened after wait (state!=1); decrypt/sign may fail")

    if experts:
        try:
            sign_results = run_expert_sign_all(
                project_id,
                section_id,
                experts,
                base_url=base_url,
                config=config,
                pm=pm,
                project_title=info.get("title"),
            )
            result["operations"].append({"action": "expert_sign", "experts": sign_results})
        except ZjgjApiError as exc:
            result["errors"].append(f"expert_sign: {exc}")
            print(f"[{project_id}] expert sign failed: {exc}")

    try:
        decrypt_results = decrypt_tenders(
            pm,
            project_id=project_id,
            section_id=section_id,
            bidders=bidders,
            password=decrypt_password,
        )
        result["operations"].append({"action": "bidder_decrypt", "results": decrypt_results})
        ok_count = sum(1 for item in decrypt_results if item.get("ok"))
        print(f"[{project_id}] decrypt: {ok_count}/{len(decrypt_results)} ok")
    except ZjgjApiError as exc:
        result["errors"].append(f"bidder_decrypt: {exc}")

    try:
        progress = pm.request(
            "GET",
            "api/manage/getProgress",
            params={"project_id": project_id, "section_id": section_id},
            require_auth=True,
        ).get("data")
        result["progress"] = progress
    except ZjgjApiError as exc:
        result["errors"].append(f"getProgress: {exc}")

    sec_state = section_state(pm, project_id)
    mg_status = manage_status(pm, project_id, section_id)
    result["final"] = {
        "start_time": (pm.get_publicity_project_info(project_id).get("data") or {}).get("start_time"),
        "section_state": sec_state,
        "section_state_label": SECTION_STATE_LABELS.get(sec_state, str(sec_state)),
        "manage_status": mg_status,
        "manage_status_label": STATUS_LABELS.get(mg_status, str(mg_status)),
    }
    result["success"] = not result["errors"] and sec_state == 1
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bid-opening operations for existing projects")
    parser.add_argument("--config", help="Optional JSON config (tokens/experts/bidders)")
    parser.add_argument("--base-url", default="https://www.bidding.shanxiguandian.com")
    parser.add_argument("--pm-token", default="41ecfede938eb984fe6cfe94c185688f")
    parser.add_argument("--project-id", type=int, action="append", dest="project_ids")
    parser.add_argument("--force-times", action="store_true", help="Force start/file_end times into the past")
    parser.add_argument("--wait-open-sec", type=int, default=30, help="Wait for section.state=1 after time change")
    parser.add_argument("--decrypt-password", default="123456")
    parser.add_argument("--dry-run", action="store_true", help="Only report current status")
    args = parser.parse_args()

    config: dict[str, Any] = {
        "verify_ssl": False,
        "flow": {"expert_agree_invite": False},
        "expert_invite": {"enabled": True},
        "expert_actions": {"audit": True, "confirm": False, "sign": True, "wait_invite_timeout_sec": 15, "poll_sec": 2},
    }
    if args.config:
        config.update(load_json(Path(args.config)))

    base_url = config.get("base_url", args.base_url)
    pm_token = config.get("tokens", {}).get("project_manager", args.pm_token)
    experts = normalize_experts({"experts": config.get("tokens", {}).get("experts")}) if config.get("tokens", {}).get("experts") else DEFAULT_EXPERTS
    bidders = config.get("tokens", {}).get("bidders") or DEFAULT_BIDDERS

    projects = DEFAULT_PROJECTS
    if args.project_ids:
        wanted = set(args.project_ids)
        projects = [p for p in DEFAULT_PROJECTS if p["project_id"] in wanted]

    if args.dry_run:
        pm = make_client(base_url, pm_token, config)
        rows = []
        for spec in projects:
            pid = spec["project_id"]
            sid = spec["section_id"]
            info = pm.get_publicity_project_info(pid).get("data") or {}
            sec_state = section_state(pm, pid)
            mg = manage_status(pm, pid, sid)
            rows.append(
                {
                    **spec,
                    "title": info.get("title"),
                    "start_time": info.get("start_time"),
                    "section_state": sec_state,
                    "manage_status": mg,
                    "experts_invited": has_expert_invite(pm, pid, sid),
                }
            )
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    results = []
    for spec in projects:
        print(f"\n========== project {spec['project_id']} (set {spec.get('set')}) ==========")
        results.append(
            run_project(
                spec,
                base_url=base_url,
                pm_token=pm_token,
                config=config,
                experts=experts,
                bidders=bidders,
                decrypt_password=args.decrypt_password,
                force_times=args.force_times,
                wait_open_sec=args.wait_open_sec,
            )
        )

    print("\n" + json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    try:
        main()
    except ZjgjApiError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

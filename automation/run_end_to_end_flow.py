#!/usr/bin/env python3
"""End-to-end ZJGJ automation: 发布项目公告 ->发布中标公示.

Orchestrates four phases (configurable via ``phases`` flags and ``--stop-after``):

  Phase A (Pre-bid):   scan folder / extract PDF ->publish ->register/pay/submit
  Phase B (Opening):   expert invite/confirm/sign ->leader election ->decrypt
  Phase C (Evaluation): preliminary review + scoring ->saveReport ->reportSign ->pushTenderReport
  Phase D (Post-eval):  addNotice (中标公示, first candidate from getCandidate)

Imports helpers from the read-only core library under ``automation/others``; does not modify them.

Usage::

  python run_end_to_end_flow.py --config config.end_to_end.example.json --folder "d:\\文件\\...\\I\\4"
  python run_end_to_end_flow.py --config config.end_to_end.example.json --project-id 2104 --stop-after decrypt
  python run_end_to_end_flow.py --config config.end_to_end.example.json --folder ... --dry-run

See ``END_TO_END_FLOW.md`` for full documentation.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

WORKSPACE_AUTOMATION = Path(__file__).resolve().parent
AUTOMATION_OTHERS = Path(r"d:\Document\others\LAB\AI\bidding-test-doc\bidding-test-doc\automation")
sys.path.insert(0, str(AUTOMATION_OTHERS))

from run_bid_opening import run_project as run_bid_opening_project  # noqa: E402
from run_full_automation import (  # noqa: E402
    apply_refreshed_tokens,
    build_run_config,
    dry_run_summary,
    enrich_expert_profiles,
    refresh_tokens_if_needed,
    setup_logging,
    token_valid,
)
from run_project_folder import scan_project_folder  # noqa: E402
from run_three_stage_flow import (  # noqa: E402
    load_config,
    make_client,
    normalize_experts,
    run_flow,
)
from zjgj_client import (  # noqa: E402
    PRELIMINARY_REVIEW_STEPS,
    SCORING_REVIEW_STEPS,
    ZjgjAdminClient,
    ZjgjApiError,
    ZjgjClient,
)

DEFAULT_BASE_URL = "https://www.bidding.shanxiguandian.com"
ALL_REVIEW_STEPS = PRELIMINARY_REVIEW_STEPS + SCORING_REVIEW_STEPS
STOP_AFTER_ORDER = ("decrypt", "review", "report", "notice")


def ensure_admin_env() -> None:
    os.environ.setdefault("ZJGJ_ADMIN_NAME", "adminz")
    os.environ.setdefault("ZJGJ_ADMIN_PASSWORD", "")


def safe_request(client: ZjgjClient, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        resp = client.request(method, path, require_auth=True, **kwargs)
        return {"ok": True, "code": resp.get("code"), "msg": resp.get("msg"), "data": resp.get("data")}
    except ZjgjApiError as exc:
        return {"ok": False, "code": exc.code, "msg": str(exc), "payload": exc.payload}
    except Exception as exc:
        err = str(exc)
        return {"ok": False, "code": None, "msg": err[:500], "is_404": "404" in err}


def resolve_section_id(pm: ZjgjClient, project_id: int, section_id: int | None) -> int:
    if section_id is not None:
        return int(section_id)
    project_info = pm.request(
        "GET",
        "api/publicity/projectInfo",
        params={"project_id": project_id},
        require_auth=True,
    )
    sections = (project_info.get("data") or {}).get("sections") or []
    if not sections:
        raise ZjgjApiError(-1, f"project {project_id} has no sections", project_info)
    return int(sections[0]["id"])


def normalize_end_to_end_config(raw: dict[str, Any], *, folder: Path | None) -> dict[str, Any]:
    """Merge simplified top-level keys (materials_folder, pm_uid, phases) into run config."""
    config = dict(raw)
    config.setdefault("base_url", DEFAULT_BASE_URL)
    config.setdefault("verify_ssl", False)

    materials = folder or config.get("materials_folder")
    if materials:
        config["materials_folder"] = str(materials)

    phases = config.setdefault(
        "phases",
        {
            "publish": True,
            "bidders": True,
            "experts": True,
            "decrypt": True,
            "review": True,
            "report": True,
            "notice": True,
        },
    )
    for key in ("publish", "bidders", "experts", "decrypt", "review", "report", "notice"):
        phases.setdefault(key, True)

    tokens = config.setdefault("tokens", {})
    if config.get("pm_uid") and not tokens.get("project_manager"):
        pm_uid = int(config["pm_uid"])
        refresh_pm = (config.get("token_refresh") or {}).get("pm") or {}
        tokens["project_manager"] = refresh_pm.get("token") or tokens.get("pm", {}).get("token", "")
        tokens.setdefault("pm", {})["uid"] = pm_uid

    return config


def trim_scanned_to_bidder_count(scanned: dict[str, Any], config: dict[str, Any]) -> None:
    """When folder has more tender PDFs than configured bidder tokens, keep the first N only."""
    max_b = config.get("max_bidders")
    token_pool = (config.get("tokens") or {}).get("bidders") or []
    limit = int(max_b) if max_b is not None else len(token_pool)
    if limit <= 0:
        return
    tender_files = scanned.get("tender_files") or []
    if len(tender_files) <= limit:
        return
    scanned["tender_files"] = tender_files[:limit]
    tender_scan = scanned.get("tender_scan") or {}
    bid_files = tender_scan.get("bid_files") or []
    if bid_files:
        tender_scan["bid_files"] = bid_files[:limit]
    extracted = scanned.get("extracted_by_file") or {}
    kept = set(scanned["tender_files"])
    scanned["extracted_by_file"] = {k: v for k, v in extracted.items() if k in kept}


def validate_no_bidder_expert_overlap(config: dict[str, Any]) -> None:
    """Fail fast if the same uid is listed as both bidder and expert."""
    tokens = config.get("tokens") or {}
    bidder_uids = {int(b["uid"]) for b in (tokens.get("bidders") or []) if b.get("uid") is not None}
    expert_uids = {int(e["uid"]) for e in (tokens.get("experts") or []) if e.get("uid") is not None}
    overlap = sorted(bidder_uids & expert_uids)
    if overlap:
        raise SystemExit(
            f"Config error: uid(s) {overlap} appear in both tokens.bidders and tokens.experts; "
            "one user cannot be bidder and expert in the same run"
        )


def phase_enabled(phases: dict[str, bool], name: str) -> bool:
    return bool(phases.get(name, True))


def should_stop_after(stop_after: str | None, checkpoint: str) -> bool:
    """Return True when ``checkpoint`` is at or past the requested stop phase.

    Example: ``--stop-after report`` continues past decrypt/review and stops
    after the report phase completes (does not run notice).
    """
    if not stop_after:
        return False
    if stop_after not in STOP_AFTER_ORDER:
        raise SystemExit(f"Invalid --stop-after: {stop_after!r}; choose from {STOP_AFTER_ORDER}")
    return STOP_AFTER_ORDER.index(checkpoint) >= STOP_AFTER_ORDER.index(stop_after)


def admin_client_from_config(config: dict[str, Any]) -> ZjgjAdminClient:
    admin_cfg = config.get("admin") or {}
    password_env = admin_cfg.get("password_env", "ZJGJ_ADMIN_PASSWORD")
    admin_password = os.environ.get(password_env)
    if not admin_password:
        raise SystemExit(f"Set {password_env} for admin token refresh / mock payment")

    admin = ZjgjAdminClient(
        config["base_url"],
        verify_ssl=config.get("verify_ssl", False),
        admin_prefix=admin_cfg.get("prefix", "/zjgj230214"),
    )
    admin.admin_name = os.environ.get(admin_cfg.get("name_env", "ZJGJ_ADMIN_NAME"), "adminz")
    admin.admin_password = admin_password
    last_err: Exception | None = None
    for _ in range(30):
        try:
            admin.admin_login()
            return admin
        except ZjgjApiError as exc:
            if "captcha OCR failed" in str(exc):
                last_err = exc
                continue
            raise
    raise SystemExit(f"admin login failed after captcha retries: {last_err}")


def refresh_uid_via_admin(config: dict[str, Any], uid: int) -> str:
    admin = admin_client_from_config(config)
    return admin.impersonate_user(uid)


def ensure_expert_ids(config: dict[str, Any], logger: logging.Logger) -> None:
    """Warn when expert_id is missing after profile enrichment (api/expert/info may be empty)."""
    missing: list[str] = []
    for expert in config.get("tokens", {}).get("experts") or []:
        uid = expert.get("uid")
        label = expert.get("name") or f"uid-{uid}"
        if expert.get("expert_id") is None:
            missing.append(label)
    if missing:
        logger.warning(
            "experts missing expert_id (add to config.tokens.experts[]): %s",
            ", ".join(missing),
        )


def resolve_expert_tokens(config: dict[str, Any], logger: logging.Logger) -> list[dict[str, Any]]:
    base = config["base_url"]
    verify = config.get("verify_ssl", False)
    experts = normalize_experts(config.get("tokens", {}))
    resolved: list[dict[str, Any]] = []
    for ex in experts:
        uid = int(ex.get("uid") or -1)
        token = ex["token"]
        if not token_valid(base, token, verify_ssl=verify):
            logger.warning("expert token invalid, refreshing uid=%s", uid)
            token = refresh_uid_via_admin(config, uid)
            ex["token"] = token
        resolved.append({"uid": uid, "name": ex.get("name") or f"uid-{uid}", "token": token, **ex})
    return resolved


def progress_snapshot(pm: ZjgjClient, project_id: int, section_id: int, step_ids: tuple[int, ...]) -> dict[str, Any]:
    resp = safe_request(pm, "GET", "api/manage/getProgress", params={"project_id": project_id, "section_id": section_id})
    data = resp.get("data") or {}
    steps: dict[str, Any] = {}
    for step in data.get("progress") or []:
        sid = step.get("id")
        if sid in step_ids:
            steps[f"step_{sid}"] = {
                "id": sid,
                "title": step.get("title"),
                "done": bool(step.get("data")),
                "data": step.get("data"),
            }
    return {"ok": resp.get("ok"), "steps": steps}


def review_list_summary(client: ZjgjClient, project_id: int, section_id: int, review_type: int) -> dict[str, Any]:
    rl = safe_request(
        client,
        "GET",
        "api/expert/reviewList",
        params={"project_id": project_id, "section_id": section_id, "type": review_type},
    )
    data = rl.get("data") or {}
    return {
        "code": rl.get("code"),
        "msg": rl.get("msg"),
        "companies": len(data.get("company") or []),
        "apply_ids": [c.get("apply_id") for c in (data.get("company") or [])],
        "data": data,
    }


def scoring_kwargs(flow_type: int) -> dict[str, Any]:
    if flow_type == 9:
        return {"score_strategy": "varied", "use_price_builder": True}
    return {"score_strategy": "varied"}


def run_phase_pre_bid(
    config: dict[str, Any],
    *,
    scanned: dict[str, Any] | None,
    project_id: int | None,
    section_id: int | None,
    logger: logging.Logger,
) -> dict[str, Any]:
    phases = config.get("phases") or {}
    report: dict[str, Any] = {"phase": "pre_bid"}

    if project_id is not None:
        config.setdefault("existing_project", {})["project_id"] = project_id
        if section_id is not None:
            config["existing_project"]["section_id"] = section_id
        if not phase_enabled(phases, "publish"):
            config["existing_project"]["project_id"] = project_id
    elif not phase_enabled(phases, "publish"):
        raise SystemExit("New project requires phases.publish=true or --project-id for resume")

    flow_flags = config.setdefault("flow", {})
    if not phase_enabled(phases, "experts"):
        flow_flags["experts"] = False
    else:
        flow_flags.setdefault("experts", True)

    if not phase_enabled(phases, "bidders") and project_id is not None:
        report["bidders"] = {"skipped": True, "reason": "phases.bidders=false"}
        if not phase_enabled(phases, "publish"):
            pm = make_client(config["base_url"], config["tokens"]["project_manager"], config)
            sid = resolve_section_id(pm, project_id, section_id)
            report["project_id"] = project_id
            report["section_id"] = sid
            report["status"] = "skipped"
            return report

    if not phase_enabled(phases, "publish") and not phase_enabled(phases, "bidders"):
        pm = make_client(config["base_url"], config["tokens"]["project_manager"], config)
        pid = int(config["existing_project"]["project_id"])
        sid = resolve_section_id(pm, pid, config["existing_project"].get("section_id"))
        report.update({"project_id": pid, "section_id": sid, "status": "skipped"})
        return report

    flow_result = run_flow(config, dry_run=False)
    report["flow"] = flow_result
    report["project_id"] = flow_result["project_id"]
    report["section_id"] = flow_result["section_id"]
    report["status"] = "success"
    return report


def opening_leader_incomplete(open_result: dict[str, Any]) -> bool:
    """True only when no leader elected and votes still incomplete."""
    leader_op = next(
        (op for op in open_result.get("operations", []) if op.get("action") == "expert_leader_election"),
        None,
    )
    if not leader_op or leader_op.get("skipped"):
        return False
    leader_elected = leader_op.get("leader_elected")
    all_voted = leader_op.get("all_voted")
    if leader_elected is None or all_voted is None:
        return not leader_op.get("ok", True)
    return not leader_elected and not all_voted


def run_phase_opening(
    config: dict[str, Any],
    *,
    project_id: int,
    section_id: int,
    logger: logging.Logger,
    decrypt_password: str | None,
) -> dict[str, Any]:
    phases = config.get("phases") or {}
    if not phase_enabled(phases, "decrypt"):
        return {"phase": "opening", "status": "skipped", "reason": "phases.decrypt=false"}

    expert_actions = config.setdefault("expert_actions", {})
    expert_actions["sign"] = True
    expert_actions["elect_leader"] = True
    expert_actions.setdefault("confirm", True)

    open_config = {
        "verify_ssl": config.get("verify_ssl", False),
        "review": config.get("review"),
        "flow": config.get("flow") or {},
        "expert_invite": config.get("expert_invite"),
        "expert_actions": expert_actions,
    }
    pm_token = config["tokens"]["project_manager"]
    bidders_for_open = [
        {"name": b.get("name"), "token": b["token"], "register": b.get("register")}
        for b in config.get("tokens", {}).get("bidders") or []
    ]
    password = decrypt_password or config.get("submit", {}).get("password", "123456")
    wait_open_sec = int(config.get("publish", {}).get("wait_open_sec", 240))

    open_result = run_bid_opening_project(
        {"project_id": project_id, "section_id": section_id},
        base_url=config["base_url"],
        pm_token=pm_token,
        config=open_config,
        experts=config.get("tokens", {}).get("experts") or [],
        bidders=bidders_for_open,
        decrypt_password=password,
        force_times=False,
        wait_open_sec=wait_open_sec,
    )

    decrypt_ops = next((op for op in open_result.get("operations", []) if op.get("action") == "bidder_decrypt"), {})
    decrypt_results = decrypt_ops.get("results") or []
    decrypt_ok = bool(decrypt_results) and all(d.get("ok") for d in decrypt_results)
    leader_incomplete = opening_leader_incomplete(open_result)
    leader_op = next(
        (op for op in open_result.get("operations", []) if op.get("action") == "expert_leader_election"),
        None,
    )

    all_ok = open_result.get("success") and decrypt_ok and not leader_incomplete

    return {
        "phase": "opening",
        "bid_opening": open_result,
        "decrypt": {
            "total": len(decrypt_results),
            "ok": sum(1 for d in decrypt_results if d.get("ok")),
            "results": decrypt_results,
        },
        "leader_election": {
            "leader_elected": (leader_op or {}).get("leader_elected"),
            "all_voted": (leader_op or {}).get("all_voted"),
            "incomplete": leader_incomplete,
        },
        "section_state": (open_result.get("final") or {}).get("section_state"),
        "status": "success" if all_ok else "partial",
    }


def run_phase_review(
    config: dict[str, Any],
    *,
    project_id: int,
    section_id: int,
    logger: logging.Logger,
) -> dict[str, Any]:
    phases = config.get("phases") or {}
    if not phase_enabled(phases, "review"):
        return {"phase": "review", "status": "skipped", "reason": "phases.review=false"}

    base_url = config["base_url"]
    verify = config.get("verify_ssl", False)
    pm_token = config["tokens"]["project_manager"]
    experts = resolve_expert_tokens(config, logger)
    expert_tokens = [ex["token"] for ex in experts]

    pm = ZjgjClient(base_url, token=pm_token, verify_ssl=verify)
    runner = ZjgjClient(base_url, token=experts[0]["token"], verify_ssl=verify)
    probe = ZjgjClient(base_url, token=experts[0]["token"], verify_ssl=verify)

    report: dict[str, Any] = {
        "phase": "review",
        "project_id": project_id,
        "section_id": section_id,
        "steps_order": [{"label": label, "flow_type": ft, "reviewList_type": rt} for ft, rt, label in ALL_REVIEW_STEPS],
        "progress_before": progress_snapshot(pm, project_id, section_id, (3, 4, 5, 7, 8, 9, 11)),
        "steps": [],
        "blockers": [],
    }

    first_review = review_list_summary(probe, project_id, section_id, ALL_REVIEW_STEPS[0][1])
    apply_ids = first_review.get("apply_ids") or []
    report["apply_ids"] = apply_ids
    report["bidder_count"] = len(apply_ids)

    if not apply_ids:
        report["blockers"].append("no bidders in reviewList")
        report["status"] = "failed"
        return report

    step_results: list[dict[str, Any]] = []
    for flow_type, review_type, label in ALL_REVIEW_STEPS:
        step_report: dict[str, Any] = {
            "label": label,
            "flow_type": flow_type,
            "reviewList_type": review_type,
            "experts": [],
        }
        review_data = review_list_summary(probe, project_id, section_id, review_type)
        review_payload = review_data.pop("data")
        step_report["reviewList"] = {k: v for k, v in review_data.items() if k != "data"}

        try:
            if flow_type in (3, 4, 5):
                results = runner.run_preliminary_review_step(
                    project_id,
                    section_id,
                    flow_type=flow_type,
                    review_type=review_type,
                    expert_tokens=expert_tokens,
                    review_list_data=review_payload,
                    pass_status=2,
                )
            else:
                results = runner.run_scoring_review_step(
                    project_id,
                    section_id,
                    flow_type=flow_type,
                    review_type=review_type,
                    expert_tokens=expert_tokens,
                    review_list_data=review_payload,
                    apply_ids=apply_ids,
                    **scoring_kwargs(flow_type),
                )
        except ZjgjApiError as exc:
            step_report["blocker"] = str(exc)
            report["blockers"].append(f"{label}: {exc}")
            step_results.append(step_report)
            continue

        all_ok = True
        for idx, result in enumerate(results):
            ex = experts[idx]
            msg = str(result.get("msg") or "")
            ok = result.get("code") == 1 and "评审成功" in msg
            if not ok:
                all_ok = False
            step_report["experts"].append(
                {
                    "uid": ex["uid"],
                    "name": ex["name"],
                    "action": result.get("phase"),
                    "code": result.get("code"),
                    "msg": msg,
                    "ok": ok,
                }
            )
        step_report["step_ok"] = all_ok
        step_report["progress_after_step"] = progress_snapshot(pm, project_id, section_id, (3, 4, 5, 7, 8, 9, 11))
        if not all_ok:
            report["blockers"].append(f"{label}: not all experts returned 评审成功")
        step_results.append(step_report)

    report["steps"] = step_results
    report["progress_after"] = progress_snapshot(pm, project_id, section_id, (3, 4, 5, 7, 8, 9, 11))
    report["status"] = (
        "success"
        if not report["blockers"] and all(s.get("step_ok") for s in step_results)
        else "partial"
        if any(s.get("step_ok") for s in step_results)
        else "failed"
    )
    return report


def run_phase_report(
    config: dict[str, Any],
    *,
    project_id: int,
    section_id: int,
    logger: logging.Logger,
) -> dict[str, Any]:
    phases = config.get("phases") or {}
    if not phase_enabled(phases, "report"):
        return {"phase": "report", "status": "skipped", "reason": "phases.report=false"}

    base_url = config["base_url"]
    verify = config.get("verify_ssl", False)
    pm_uid = int(config.get("pm_uid") or (config.get("token_refresh") or {}).get("pm", {}).get("uid") or 0)
    experts = resolve_expert_tokens(config, logger)
    leader_uid = int((config.get("leader") or {}).get("uid") or experts[0]["uid"])

    report: dict[str, Any] = {"phase": "report", "errors": []}
    admin = admin_client_from_config(config)
    pm_token = admin.impersonate_user(pm_uid) if pm_uid else config["tokens"]["project_manager"]
    pm = ZjgjClient(base_url, token=pm_token, verify_ssl=verify)

    progress_before = pm.get_manage_progress(project_id, section_id)
    get_report_before = pm.get_manage_report(project_id, section_id)
    report["progress_before"] = {"step12": _step_by_id(progress_before, 12)}
    report["getReport_before"] = _report_info(get_report_before)

    project_title = (
        (get_report_before.get("data") or {}).get("project", {}).get("title")
        or config.get("publish", {}).get("title")
        or "本项目"
    )
    content1 = f"本项目采购内容为{project_title}，按招标文件要求完成供货及相关服务。"

    try:
        save_resp = pm.save_evaluation_report(
            project_id,
            section_id,
            content1=content1,
            content2="无",
            content3="无",
        )
        report["saveReport"] = {"code": save_resp.get("code"), "msg": save_resp.get("msg"), "ok": True}
    except ZjgjApiError as exc:
        report["saveReport"] = {"code": exc.code, "msg": str(exc), "ok": False}
        report["errors"].append(f"saveReport: {exc}")

    get_report_after = pm.get_manage_report(project_id, section_id)
    report_info = (get_report_after.get("data") or {}).get("info") or {}
    report["getReport_after_save"] = _report_info(get_report_after)

    report["expert_reportSign"] = []
    for ex in experts:
        uid = int(ex["uid"])
        try:
            expert_token = admin.impersonate_user(uid)
            expert_client = ZjgjClient(base_url, token=expert_token, verify_ssl=verify)
            payload = {"project_id": project_id, "section_id": section_id}
            invite_id = (config.get("existing_project") or {}).get("invite_id")
            if invite_id:
                payload["invite_id"] = invite_id
            sign_resp = safe_request(expert_client, "POST", "api/expert/reportSign", data=payload)
            check_resp = safe_request(expert_client, "GET", "api/expert/checkReport", params=payload)
            report["expert_reportSign"].append(
                {
                    "uid": uid,
                    "name": ex.get("name"),
                    "reportSign": sign_resp,
                    "checkReport": check_resp,
                }
            )
        except Exception as exc:
            report["expert_reportSign"].append({"uid": uid, "error": str(exc)[:300]})
            report["errors"].append(f"expert {uid} reportSign: {exc}")

    leader_token = admin.impersonate_user(leader_uid)
    leader = ZjgjClient(base_url, token=leader_token, verify_ssl=verify)
    push_payload = {"project_id": project_id, "section_id": section_id}
    push_result = safe_request(leader, "GET", "api/manage/pushTenderReport", params=push_payload)
    report["pushTenderReport"] = push_result
    if not (push_result.get("ok") and push_result.get("code") == 1):
        pm_push = safe_request(pm, "GET", "api/manage/pushTenderReport", params=push_payload)
        report["pushTenderReport_pm_fallback"] = pm_push
        push_result = pm_push if pm_push.get("ok") else push_result

    progress_after = pm.get_manage_progress(project_id, section_id)
    get_report_final = pm.get_manage_report(project_id, section_id)
    report["progress_after"] = {"step12": _step_by_id(progress_after, 12), "step13": _step_by_id(progress_after, 13)}
    report["getReport_final"] = _report_info(get_report_final)

    is_push = (report["getReport_final"].get("info") or {}).get("is_push")
    is_report = (( _step_by_id(progress_after, 12) or {}).get("data") or {}).get("is_report")
    report["status"] = "success" if is_push == 1 or is_report == 1 else "partial"
    if report["status"] != "success":
        report["errors"].append(f"is_push={is_push!r}, is_report={is_report!r}")
    return report


def _step_by_id(progress: dict, step_id: int) -> dict | None:
    for item in (progress.get("data") or {}).get("progress") or []:
        if item.get("id") == step_id:
            return item
    return None


def _report_info(resp: dict) -> dict[str, Any]:
    data = resp.get("data") or {}
    info = data.get("info")
    return {"code": resp.get("code"), "msg": resp.get("msg"), "info": info, "is_push": (info or {}).get("is_push")}


def build_notice_content(project_title: str, project_no: str, winner: str, amount: str) -> str:
    start = datetime.now()
    end = start + timedelta(days=3)
    return (
        f"<p><strong>{project_title}（{project_no}）中标公示</strong></p>"
        f"<p>经评标委员会评审，拟确定<strong>{winner}</strong>为本项目中标单位，"
        f"中标金额：{amount}元（含税）。</p>"
        f"<p>公示期：{start.strftime('%Y年%m月%d日')}至{end.strftime('%Y年%m月%d日')}（3个工作日）。</p>"
        f"<p>各有关当事人对中标结果有异议的，可以在公示期内以书面形式向招标人提出异议。</p>"
        f"<p>特此公示。</p>"
    )


def run_phase_notice(
    config: dict[str, Any],
    *,
    project_id: int,
    section_id: int,
    logger: logging.Logger,
) -> dict[str, Any]:
    phases = config.get("phases") or {}
    if not phase_enabled(phases, "notice"):
        return {"phase": "notice", "status": "skipped", "reason": "phases.notice=false"}

    base_url = config["base_url"]
    verify = config.get("verify_ssl", False)
    pm_uid = int(config.get("pm_uid") or (config.get("token_refresh") or {}).get("pm", {}).get("uid") or 0)
    admin = admin_client_from_config(config)
    pm_token = admin.impersonate_user(pm_uid) if pm_uid else config["tokens"]["project_manager"]
    pm = ZjgjClient(base_url, token=pm_token, verify_ssl=verify)

    report: dict[str, Any] = {"phase": "notice", "errors": []}

    listing = pm.request("GET", "api/manage/myList", params={"page": 1, "limit": 300}, require_auth=True)
    mylist_row = None
    for item in (listing.get("data") or {}).get("list") or []:
        if int(item.get("project_id", -1)) == project_id and int(item.get("section_id", -1)) == section_id:
            mylist_row = item
            break
    report["before"] = {"myList_is_notice": (mylist_row or {}).get("is_notice")}

    if mylist_row and int(mylist_row.get("is_notice") or 0) == 1:
        report["addNotice"] = {"skipped": True, "reason": "is_notice already 1"}
        report["status"] = "already_published"
        return report

    get_candidate = pm.get_manage_candidates(project_id, section_id)
    candidates = (get_candidate.get("data") or {}).get("list") or []
    project_info = (get_candidate.get("data") or {}).get("project") or {}
    report["getCandidate"] = {
        "code": get_candidate.get("code"),
        "msg": get_candidate.get("msg"),
        "list": [
            {"id": c.get("id"), "apply_id": c.get("apply_id"), "company_name": c.get("company_name"), "amount": c.get("amount")}
            for c in candidates
        ],
    }

    if not candidates:
        report["status"] = "failed"
        report["errors"].append("getCandidate returned no rows")
        return report

    winner_stat = candidates[0]
    stat_id = int(winner_stat["id"])
    title = project_info.get("title") or config.get("publish", {}).get("title") or "本项目"
    project_no = project_info.get("project_no") or config.get("publish", {}).get("project_no") or ""
    winner_name = winner_stat.get("company_name") or "中标单位"
    amount = str(winner_stat.get("amount") or "10000.00")
    content = build_notice_content(title, project_no, winner_name, amount)
    payload = {"stat_id": stat_id, "content": content}
    report["selected_stat"] = {"stat_id": stat_id, "company_name": winner_name, "amount": amount}

    add_resp = safe_request(pm, "POST", "api/manage/addNotice", data=payload)
    report["addNotice"] = add_resp
    if not add_resp.get("ok"):
        report["status"] = "failed"
        report["errors"].append(f"addNotice: {add_resp.get('msg')}")
        return report

    listing_after = pm.request("GET", "api/manage/myList", params={"page": 1, "limit": 300}, require_auth=True)
    mylist_after = None
    for item in (listing_after.get("data") or {}).get("list") or []:
        if int(item.get("project_id", -1)) == project_id and int(item.get("section_id", -1)) == section_id:
            mylist_after = item
            break
    report["after"] = {"myList_is_notice": (mylist_after or {}).get("is_notice")}
    report["status"] = "success" if mylist_after and int(mylist_after.get("is_notice") or 0) == 1 else "partial"
    return report


def run_end_to_end(
    config: dict[str, Any],
    *,
    scanned: dict[str, Any] | None,
    project_id: int | None,
    section_id: int | None,
    stop_after: str | None,
    decrypt_password: str | None,
    logger: logging.Logger,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "base_url": config.get("base_url"),
        "phases_config": config.get("phases"),
        "stop_after": stop_after,
        "phase_results": {},
        "errors": [],
    }
    if scanned:
        report["project_dir"] = scanned.get("project_dir")
        report["materials"] = {
            "bidding_files": scanned.get("bidding_files") or [],
            "tender_files": scanned.get("tender_files") or [],
        }

    phases = config.get("phases") or {}
    pid = project_id
    sid = section_id

    run_pre = (
        phase_enabled(phases, "publish")
        or phase_enabled(phases, "bidders")
        or (pid is None and scanned is not None)
    )
    if run_pre and pid is None:
        pre = run_phase_pre_bid(config, scanned=scanned, project_id=pid, section_id=sid, logger=logger)
        report["phase_results"]["pre_bid"] = pre
        if pre.get("project_id"):
            pid = int(pre["project_id"])
            sid = int(pre["section_id"])
    elif pid is not None:
        pm = make_client(config["base_url"], config["tokens"]["project_manager"], config)
        sid = resolve_section_id(pm, pid, sid)
        report["phase_results"]["pre_bid"] = {"skipped": True, "project_id": pid, "section_id": sid}
        if phase_enabled(phases, "bidders"):
            pre = run_phase_pre_bid(config, scanned=scanned, project_id=pid, section_id=sid, logger=logger)
            report["phase_results"]["pre_bid"] = pre
    else:
        raise SystemExit("Provide --folder for new project or --project-id to resume")

    if pid is None or sid is None:
        raise SystemExit("Could not resolve project_id / section_id")

    report["project_id"] = pid
    report["section_id"] = sid

    if phase_enabled(phases, "decrypt"):
        opening = run_phase_opening(
            config, project_id=pid, section_id=sid, logger=logger, decrypt_password=decrypt_password
        )
        report["phase_results"]["opening"] = opening
    else:
        report["phase_results"]["opening"] = {"skipped": True, "reason": "phases.decrypt=false"}

    if should_stop_after(stop_after, "decrypt"):
        report["status"] = _aggregate_status(report)
        report["stopped_at"] = "decrypt"
        return report

    if phase_enabled(phases, "review"):
        review = run_phase_review(config, project_id=pid, section_id=sid, logger=logger)
        report["phase_results"]["review"] = review
    else:
        report["phase_results"]["review"] = {"skipped": True}

    if should_stop_after(stop_after, "review"):
        report["status"] = _aggregate_status(report)
        report["stopped_at"] = "review"
        return report

    if phase_enabled(phases, "report"):
        report_phase = run_phase_report(config, project_id=pid, section_id=sid, logger=logger)
        report["phase_results"]["report"] = report_phase
    else:
        report["phase_results"]["report"] = {"skipped": True}

    if should_stop_after(stop_after, "report"):
        report["status"] = _aggregate_status(report)
        report["stopped_at"] = "report"
        return report

    if phase_enabled(phases, "notice"):
        notice = run_phase_notice(config, project_id=pid, section_id=sid, logger=logger)
        report["phase_results"]["notice"] = notice
    else:
        report["phase_results"]["notice"] = {"skipped": True}

    report["status"] = _aggregate_status(report)
    report["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return report


def _aggregate_status(report: dict[str, Any]) -> str:
    phases = report.get("phase_results") or {}
    statuses = [p.get("status") for p in phases.values() if isinstance(p, dict) and p.get("status")]
    if not statuses:
        return "unknown"
    if all(s in ("success", "skipped", "already_published") for s in statuses):
        return "success"
    if any(s == "success" for s in statuses):
        return "partial"
    return "failed"


def default_report_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return WORKSPACE_AUTOMATION / f"end_to_end_flow_report_{stamp}.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ZJGJ 端到端自动化：发布项目公告 -> 发布中标公示",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "阶段 (--stop-after):\n"
            "  decrypt  开标解密完成后停止\n"
            "  review   评审打分完成后停止\n"
            "  report   评标报告推送完成后停止\n"
            "  notice   完整流程（含中标公示）"
        ),
    )
    parser.add_argument("--config", default=str(WORKSPACE_AUTOMATION / "config.end_to_end.example.json"))
    parser.add_argument("--folder", help="项目材料目录（覆盖 config.materials_folder）")
    parser.add_argument("--project-id", type=int, help="续跑已有项目 ID（跳过发布公告）")
    parser.add_argument("--section-id", type=int, help="标段 ID（默认取项目第一个标段）")
    parser.add_argument(
        "--stop-after",
        choices=STOP_AFTER_ORDER,
        help="在指定阶段完成后停止：decrypt|review|report|notice",
    )
    parser.add_argument("--dry-run", action="store_true", help="仅扫描文件夹并预览配置，不调用变更 API")
    parser.add_argument("--report", help="报告 JSON 输出路径")
    parser.add_argument("--log", help="日志文件路径")
    parser.add_argument("--decrypt-password", help="投标文件解密密码（默认 config.submit.password 或 123456）")
    parser.add_argument("--no-token-refresh", action="store_true", help="跳过 admin token 刷新")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.is_file():
        raise SystemExit(f"Config not found: {config_path}")

    report_path = Path(args.report) if args.report else default_report_path()
    log_path = Path(args.log) if args.log else report_path.with_suffix(".log")
    logger = setup_logging(log_path)

    folder: Path | None = Path(args.folder) if args.folder else None
    raw_config = load_config(config_path)
    config = normalize_end_to_end_config(raw_config, folder=folder)
    validate_no_bidder_expert_overlap(config)

    if not folder and config.get("materials_folder") and not args.project_id:
        folder = Path(config["materials_folder"])

    if args.no_token_refresh:
        config.setdefault("token_refresh", {})["enabled"] = False

    ensure_admin_env()
    if not args.dry_run and not os.environ.get("ZJGJ_ADMIN_PASSWORD"):
        logger.warning("ZJGJ_ADMIN_PASSWORD not set — token refresh / admin mock payment may fail")

    if not args.dry_run:
        token_map = refresh_tokens_if_needed(config, logger)
        apply_refreshed_tokens(config, token_map)
        enrich_expert_profiles(config)
        ensure_expert_ids(config, logger)

    scanned: dict[str, Any] | None = None
    if folder:
        if not folder.is_dir():
            if args.dry_run:
                logger.warning("folder not found (dry-run): %s", folder)
            else:
                raise SystemExit(f"Project folder not found: {folder}")
        else:
            scanned = scan_project_folder(folder, config=config)
            trim_scanned_to_bidder_count(scanned, config)
            if not args.dry_run:
                config = build_run_config(config, scanned, logger)
            elif scanned:
                config = build_run_config(config, scanned, logger)
            logger.info("scanned folder: %s tender_files=%s", folder, len(scanned.get("tender_files") or []))

    if args.dry_run:
        summary = dry_run_summary(scanned or {}, config) if scanned else {"mode": "dry-run", "config_only": True}
        summary["stop_after"] = args.stop_after
        summary["project_id_resume"] = args.project_id
        summary["phases"] = config.get("phases")
        summary["report_path"] = str(report_path)
        report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        logger.info("dry-run complete report=%s", report_path)
        return 0

    if args.project_id:
        config.setdefault("existing_project", {})["project_id"] = args.project_id
        if args.section_id:
            config["existing_project"]["section_id"] = args.section_id
        if not phase_enabled(config.get("phases") or {}, "publish"):
            pass
        else:
            config.setdefault("phases", {})["publish"] = False

    report: dict[str, Any] = {
        "config_path": str(config_path),
        "report_path": str(report_path),
        "log_path": str(log_path),
    }

    try:
        flow_report = run_end_to_end(
            config,
            scanned=scanned,
            project_id=args.project_id,
            section_id=args.section_id,
            stop_after=args.stop_after,
            decrypt_password=args.decrypt_password,
            logger=logger,
        )
        report.update(flow_report)
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        logger.exception("end-to-end flow failed")
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 1

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    logger.info("end-to-end complete status=%s report=%s", report.get("status"), report_path)
    return 0 if report.get("status") in ("success", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())

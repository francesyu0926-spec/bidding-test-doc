#!/usr/bin/env python3
"""Run ZJGJ three-stage bidding flow against a live environment.

Stages:
1. Publish publicity project (project manager token)
2. Register and pay (one or more bidder tokens)
3. Submit tender files (one or more bidder tokens)
4. Invite, confirm and sign in experts (optional, one or more expert tokens)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from zjgj_client import ZjgjApiError, ZjgjClient, leader_vote_already_done, review_categories_total

REGISTER_STATUS_COMPLETED = 3
BIDDING_DIR_NAMES = ("????", "bidding", "bid-documents")
BIDDING_FILE_SUFFIXES = {".pdf", ".doc", ".docx", ".zip", ".rar"}


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value))
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def compute_publish_times(
    publish: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """Compute near-future publish times from publish.open_in_minutes (default 3)."""
    publish = publish or {}
    now = now or datetime.now()
    open_in_minutes = max(2, int(publish.get("open_in_minutes", 3)))
    start_dt = now + timedelta(minutes=open_in_minutes)
    file_end_dt = now + timedelta(minutes=open_in_minutes - 1)
    return {
        "start_time": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "file_end_time": file_end_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "file_start_time": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


def apply_publish_times(config: dict[str, Any], *, now: datetime | None = None) -> dict[str, str]:
    """Set publish start/file times on config from open_in_minutes."""
    publish = config.setdefault("publish", {})
    times = compute_publish_times(publish, now=now)
    publish.update(times)
    return times


def wait_until_start_time(
    start_time: str | datetime | None,
    *,
    poll_sec: int = 5,
    label: str = "",
) -> bool:
    """Block until now >= start_time."""
    prefix = f"[{label}] " if label else ""
    start_dt = start_time if isinstance(start_time, datetime) else parse_time(start_time)
    if start_dt is None:
        print(f"{prefix}no start_time configured, skipping wait")
        return True
    if datetime.now() >= start_dt:
        print(f"{prefix}start_time already reached ({start_dt.strftime('%Y-%m-%d %H:%M:%S')})")
        return True
    remaining = int((start_dt - datetime.now()).total_seconds())
    print(f"{prefix}waiting for start_time {start_dt.strftime('%Y-%m-%d %H:%M:%S')} (~{remaining}s remaining)...")
    while datetime.now() < start_dt:
        time.sleep(min(poll_sec, max(1, (start_dt - datetime.now()).total_seconds())))
    print(f"{prefix}start_time reached ({start_dt.strftime('%Y-%m-%d %H:%M:%S')})")
    return True


def section_state(client: ZjgjClient, project_id: int) -> int | None:
    info = client.get_publicity_project_info(project_id).get("data") or {}
    sections = info.get("sections") or []
    if not sections:
        return None
    state = sections[0].get("state")
    return int(state) if state is not None else None


def wait_for_section_open(
    client: ZjgjClient,
    project_id: int,
    *,
    timeout_sec: int,
    poll_sec: int = 5,
    target_state: int = 3,
) -> bool:
    """Wait until publicity section reaches bid-open state (default 3).

    PublicityProject::autoStart() sets section/project state to 3 when
    start_time is reached and experts have been invited.
    """
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        client.request("GET", "api/manage/myList", params={"page": 1, "limit": 20}, require_auth=True)
        if section_state(client, project_id) == target_state:
            return True
        time.sleep(poll_sec)
    return section_state(client, project_id) == target_state


def client_verify_ssl(config: dict) -> bool:
    return bool(config.get("verify_ssl", True))


def make_client(base_url: str, token: str | None, config: dict) -> ZjgjClient:
    return ZjgjClient(base_url=base_url, token=token, verify_ssl=client_verify_ssl(config))


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_publish_images(images: Any) -> str | None:
    """Normalize ???? entries to [{name, tempFilePath}] for api/publicity/create."""
    if images is None:
        return None
    if isinstance(images, str):
        text = images.strip()
        if not text or text == "[]":
            return None
        parsed = json.loads(text)
    else:
        parsed = images
    if not parsed:
        return None

    normalized: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("fileName")
        temp_file_path = item.get("tempFilePath") or item.get("fileUrl") or item.get("url")
        if name and temp_file_path:
            normalized.append({"name": str(name), "tempFilePath": str(temp_file_path)})
    if not normalized:
        return None
    return json.dumps(normalized, ensure_ascii=False)


def build_images_payload(
    client: ZjgjClient,
    cfg: dict[str, Any],
) -> str | None:
    """Build images JSON for API payloads.

    Uses [{name, tempFilePath}] for both publish (api/publicity/create) and
    register (api/project_register/register).
    """
    images = cfg.get("images")
    if images:
        return normalize_publish_images(images)

    upload_paths: list[str] = []
    if cfg.get("upload_files"):
        upload_paths.extend(str(path) for path in cfg["upload_files"])
    if cfg.get("upload_file"):
        upload_paths.append(str(cfg["upload_file"]))
    if not upload_paths:
        return None

    uploaded_files: list[dict[str, str]] = []
    for upload_path in upload_paths:
        upload_resp = client.upload_image(upload_path)
        uploaded = (upload_resp.get("data") or upload_resp.get("result") or {}).get("url")
        if not uploaded:
            raise ZjgjApiError(-1, "upload succeeded but file url missing", upload_resp)
        uploaded_files.append({"name": Path(upload_path).name, "tempFilePath": uploaded})
    return json.dumps(uploaded_files, ensure_ascii=False)


def build_publish_payload(config: dict) -> dict:
    publish = config["publish"]
    now = datetime.now()
    times = compute_publish_times(publish, now=now)
    publish.update(times)
    payload = {
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
        "start_time": times["start_time"],
        "file_start_time": times["file_start_time"],
        "file_end_time": times["file_end_time"],
        "file_price": publish.get("file_price", "1.00"),
        "platform_price": publish.get("platform_price", "1.00"),
        "deposit": publish.get("deposit", "0.00"),
        "price": publish.get("price", "0.00"),
        "intro": publish.get("intro", "<p>????????/p>"),
    }
    if publish.get("project_id") is not None:
        payload["id"] = int(publish["project_id"])
    if publish.get("images"):
        payload["images"] = publish["images"]
    return payload


def extract_id(payload: dict, *keys: str) -> int | None:
    data = payload.get("data") or payload.get("result") or {}
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] is not None:
                return int(data[key])
    return None


def resolve_created_project_id(client: ZjgjClient, publish_payload: dict) -> int:
    project_id = None
    for page in range(1, 4):
        listing = client.list_public_projects(page=page, limit=20)
        for item in (listing.get("data") or {}).get("list", []):
            if publish_payload.get("project_no") and item.get("project_no") == publish_payload["project_no"]:
                return int(item["id"])
            if publish_payload.get("title") and item.get("title") == publish_payload["title"]:
                return int(item["id"])
    raise ZjgjApiError(-1, "create publicity succeeded but project_id missing", {"publish": publish_payload})


def normalize_bidders(tokens: dict[str, Any]) -> list[dict[str, Any]]:
    bidders = tokens.get("bidders")
    if bidders:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(bidders):
            if isinstance(item, str):
                normalized.append({"name": f"bidder-{index + 1}", "token": item})
            elif isinstance(item, dict) and item.get("token"):
                normalized.append(item)
            else:
                raise SystemExit(f"Invalid bidder entry at index {index}: {item!r}")
        return normalized

    single = tokens.get("bidder")
    if single:
        return [{"name": "bidder-1", "token": single}]
    return []


def normalize_experts(tokens: dict[str, Any]) -> list[dict[str, Any]]:
    experts = tokens.get("experts")
    if experts:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(experts):
            if isinstance(item, str):
                normalized.append({"name": f"expert-{index + 1}", "token": item})
            elif isinstance(item, dict) and item.get("token"):
                normalized.append(item)
            else:
                raise SystemExit(f"Invalid expert entry at index {index}: {item!r}")
        return normalized

    single = tokens.get("expert")
    if single:
        return [{"name": "expert-1", "token": single}]
    return []


def bidder_label(bidder_cfg: dict[str, Any], profile: dict[str, Any] | None = None) -> str:
    if bidder_cfg.get("name"):
        return str(bidder_cfg["name"])
    if profile:
        data = profile.get("data") or {}
        nickname = data.get("nickname") or data.get("mobile") or data.get("code")
        if nickname:
            return str(nickname)
    token = bidder_cfg.get("token", "")
    return f"token-{token[:8]}"


def expert_label(expert_cfg: dict[str, Any], profile: dict[str, Any] | None = None) -> str:
    if expert_cfg.get("name"):
        return str(expert_cfg["name"])
    if profile:
        data = profile.get("data") or {}
        name = data.get("name") or data.get("nickname")
        if name:
            return str(name)
        user = data.get("user") or {}
        if user.get("nickname"):
            return str(user["nickname"])
    token = expert_cfg.get("token", "")
    return f"token-{token[:8]}"


def resolve_expert_id(expert_cfg: dict[str, Any], client: ZjgjClient) -> int:
    if expert_cfg.get("expert_id") is not None:
        return int(expert_cfg["expert_id"])
    profile = client.get_expert_profile()
    expert_id = extract_id(profile, "id")
    if expert_id is None:
        data = profile.get("data") or {}
        if data.get("id") is not None:
            expert_id = int(data["id"])
    if expert_id is None:
        raise ZjgjApiError(-1, "unable to resolve expert_id", profile)
    return expert_id


def resolve_expert_uid(expert_cfg: dict[str, Any], client: ZjgjClient) -> int:
    if expert_cfg.get("uid") is not None:
        return int(expert_cfg["uid"])
    data = client.get_expert_profile().get("data") or {}
    user = data.get("user") or {}
    if user.get("id") is not None:
        return int(user["id"])
    if data.get("uid") is not None:
        return int(data["uid"])
    raise ZjgjApiError(-1, "unable to resolve expert uid", data)


def extract_invite_id_from_item(item: dict[str, Any]) -> int | None:
    extract = item.get("extract") or {}
    invite_id = extract.get("invite_id") or item.get("invite_id") or item.get("id")
    if invite_id is not None:
        return int(invite_id)
    return None


def find_expert_invite_id_from_pm(
    pm: ZjgjClient,
    project_id: int,
    section_id: int,
    expert_uid: int,
) -> int | None:
    """Resolve per-expert invite row id from api/manage/inviteInfo (info.users[].id)."""
    invite = pm.get_manage_invite_info(project_id, section_id).get("data") or {}
    info = invite.get("info") or {}
    if int(info.get("project_id", project_id)) != project_id:
        return None
    batch_id = info.get("id")
    users = info.get("users") or []
    for user in users:
        if int(user.get("uid", -1)) == expert_uid:
            row_id = user.get("id")
            if row_id is not None:
                return int(row_id)
    return int(batch_id) if batch_id is not None else None


def find_expert_invite_id(
    client: ZjgjClient,
    project_id: int,
    *,
    project_title: str | None = None,
    timeout_sec: int,
    poll_sec: int,
    pm: ZjgjClient | None = None,
    section_id: int | None = None,
    expert_uid: int | None = None,
) -> int | None:
    def lookup() -> int | None:
        listing = client.list_expert_projects(page=1, limit=50)
        for item in (listing.get("data") or {}).get("list", []):
            if int(item.get("project_id", -1)) == project_id:
                invite_id = extract_invite_id_from_item(item)
                if invite_id is not None:
                    return invite_id

        for status in (0, 1, 2, 3, 4, 6):
            invites = client.list_expert_invites(page=1, limit=50, status=status)
            for item in (invites.get("data") or {}).get("list", []):
                if int(item.get("project_id", -1)) == project_id:
                    invite_id = extract_invite_id_from_item(item)
                    if invite_id is not None:
                        return invite_id

        notifications = client.get_user_notifications(notify_type=2, page=1, limit=20)
        for item in notifications.get("data") or []:
            if item.get("type") != 7:
                continue
            content = item.get("content") or ""
            if project_title and project_title not in content:
                continue
            source = item.get("source")
            if source is not None:
                return int(source)

        if pm is not None and section_id is not None and expert_uid is not None:
            return find_expert_invite_id_from_pm(pm, project_id, section_id, expert_uid)
        return None

    if timeout_sec <= 0:
        return lookup()

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        invite_id = lookup()
        if invite_id is not None:
            return invite_id
        time.sleep(poll_sec)
    return None


def resolve_expert_invite_id(
    expert_cfg: dict[str, Any],
    client: ZjgjClient,
    *,
    project_id: int,
    section_id: int,
    pm: ZjgjClient | None,
    project_title: str | None,
    expert_actions: dict[str, Any],
) -> int | None:
    if expert_cfg.get("invite_id") is not None:
        return int(expert_cfg["invite_id"])

    expert_uid = resolve_expert_uid(expert_cfg, client)
    return find_expert_invite_id(
        client,
        project_id,
        project_title=project_title,
        timeout_sec=int(expert_actions.get("wait_invite_timeout_sec", 10)),
        poll_sec=int(expert_actions.get("poll_sec", 2)),
        pm=pm,
        section_id=section_id,
        expert_uid=expert_uid,
    )


CONFIRM_ALREADY_DONE_MARKERS = ("???", "????", "????")


def expert_confirm_already_done(message: str) -> bool:
    return any(marker in message for marker in CONFIRM_ALREADY_DONE_MARKERS)


def expert_audit_enabled(config: dict[str, Any]) -> bool:
    flow = config.get("flow") or {}
    if "expert_audit" in flow:
        return bool(flow["expert_audit"])
    expert_actions = config.get("expert_actions", {})
    if "audit" in expert_actions:
        return bool(expert_actions["audit"])
    # Backend has no PM ???? endpoint; addExpert ignores check/is_check.
    return False


def expert_agree_invite_enabled(config: dict[str, Any]) -> bool:
    flow = config.get("flow") or {}
    if "expert_agree_invite" in flow:
        return bool(flow["expert_agree_invite"])
    return bool(config.get("expert_actions", {}).get("confirm", False))


def confirm_expert_invite_for_cfg(
    expert_cfg: dict[str, Any],
    *,
    base_url: str,
    project_id: int,
    section_id: int,
    config: dict,
    pm: ZjgjClient | None = None,
    project_title: str | None = None,
) -> dict[str, Any]:
    token = expert_cfg["token"]
    client = make_client(base_url, token, config)
    profile = client.get_expert_profile()
    label = expert_label(expert_cfg, profile)
    expert_actions = config.get("expert_actions", {})
    expert_data = profile.get("data") or {}
    expert_id = resolve_expert_id(expert_cfg, client)
    expert_uid = resolve_expert_uid(expert_cfg, client)
    user = expert_data.get("user") or {}

    result: dict[str, Any] = {
        "name": label,
        "expert_id": expert_id,
        "uid": expert_uid,
        "mobile": user.get("mobile") or expert_data.get("mobile"),
        "major_name": expert_data.get("major_name"),
    }

    if not expert_agree_invite_enabled(config):
        result["skipped"] = True
        result["reason"] = "expert agree invite disabled"
        print(f"[{label}] stage: expert agree invite skipped (disabled)")
        return result

    invite_id = resolve_expert_invite_id(
        expert_cfg,
        client,
        project_id=project_id,
        section_id=section_id,
        pm=pm,
        project_title=project_title,
        expert_actions=expert_actions,
    )
    result["invite_id"] = invite_id

    if invite_id is None:
        result["ok"] = False
        result["error"] = "invite_id not found"
        print(f"[{label}] stage: expert agree invite failed: invite_id not found")
        return result

    confirm_status = int(expert_actions.get("confirm_status", 2))
    try:
        confirm_resp = client.confirm_expert_invite(int(invite_id), status=confirm_status)
        result["ok"] = True
        result["confirm"] = confirm_resp
        result["msg"] = confirm_resp.get("msg")
        print(f"[{label}] stage: expert agree invite ok (???????: invite_id={invite_id} msg={confirm_resp.get('msg')}")
    except ZjgjApiError as exc:
        if expert_confirm_already_done(str(exc)):
            result["ok"] = True
            result["already_confirmed"] = True
            result["msg"] = str(exc)
            print(f"[{label}] stage: expert agree invite ok (already confirmed): invite_id={invite_id}")
        else:
            result["ok"] = False
            result["error"] = str(exc)
            print(f"[{label}] stage: expert agree invite failed: {exc}")

    return result


def confirm_all_expert_invites(
    project_id: int,
    section_id: int,
    expert_cfgs: list[dict[str, Any]],
    *,
    base_url: str,
    config: dict,
    pm: ZjgjClient | None = None,
    project_title: str | None = None,
) -> list[dict[str, Any]]:
    """Agree to each expert invitation via api/expert/confirm (status=2)."""
    if not expert_agree_invite_enabled(config):
        print("stage: expert agree invite skipped (disabled)")
        return []

    results: list[dict[str, Any]] = []
    for expert_cfg in expert_cfgs:
        results.append(
            confirm_expert_invite_for_cfg(
                expert_cfg,
                base_url=base_url,
                project_id=project_id,
                section_id=section_id,
                config=config,
                pm=pm,
                project_title=project_title,
            )
        )
    ok_count = sum(1 for item in results if item.get("ok"))
    print(f"stage: expert agree invite {ok_count}/{len(results)} ok")
    return results


def pass_expert_audit_for_project(
    project_id: int,
    section_id: int,
    expert_cfgs: list[dict[str, Any]],
    *,
    base_url: str,
    pm: ZjgjClient,
    config: dict,
) -> dict[str, Any]:
    """PM ???? ??not supported; addExpert ignores check/is_check."""
    if not expert_audit_enabled(config):
        print("stage: expert audit skipped (disabled)")
        return {"skipped": True, "reason": "audit disabled"}

    expert_uids = [
        resolve_expert_uid(expert_cfg, make_client(base_url, expert_cfg["token"], config))
        for expert_cfg in expert_cfgs
    ]
    payload = build_expert_invite_payload(
        project_id=project_id,
        section_id=section_id,
        expert_uids=expert_uids,
        config=config,
        expert_cfgs=expert_cfgs,
        base_url=base_url,
    )
    audit_resp = pm.audit_expert_invites(payload)
    result: dict[str, Any] = {
        "ok": True,
        "msg": audit_resp.get("msg"),
        "users": payload.get("users"),
        "audit": audit_resp,
    }
    print(f"stage: expert audit passed (????): users={payload['users']} msg={audit_resp.get('msg')}")
    return result


def audit_all_expert_invites(
    project_id: int,
    section_id: int,
    expert_cfgs: list[dict[str, Any]],
    *,
    base_url: str,
    config: dict,
    pm: ZjgjClient,
) -> dict[str, Any]:
    """PM-side ???? for all invited experts (not api/expert/confirm)."""
    return pass_expert_audit_for_project(
        project_id,
        section_id,
        expert_cfgs,
        base_url=base_url,
        pm=pm,
        config=config,
    )


approve_expert_invites = audit_all_expert_invites


def build_expert_invite_payload(
    *,
    project_id: int,
    section_id: int,
    expert_uids: list[int],
    config: dict,
    expert_cfgs: list[dict[str, Any]],
    base_url: str,
) -> dict[str, Any]:
    invite_cfg = config.get("expert_invite", {})
    major_ids = invite_cfg.get("major_ids")
    if not major_ids:
        majors: list[str] = []
        for expert_cfg in expert_cfgs:
            invite_overrides = expert_cfg.get("invite", {})
            if invite_overrides.get("major_ids"):
                majors.extend(str(invite_overrides["major_ids"]).split(","))
            else:
                client = make_client(base_url, expert_cfg["token"], config)
                expert_data = client.get_expert_profile().get("data") or {}
                if expert_data.get("major_ids"):
                    majors.extend(str(expert_data["major_ids"]).split(","))
        major_ids = ",".join(dict.fromkeys(m for m in majors if m))

    return {
        "project_id": project_id,
        "section_id": section_id,
        "province": invite_cfg.get("province", "440000"),
        "city": invite_cfg.get("city", "440100"),
        "major_ids": major_ids,
        "extract_way": invite_cfg.get("extract_way", 2),
        "take_time": invite_cfg.get("take_time", 3),
        "type": invite_cfg.get("type", 1),
        "address": invite_cfg.get("address", "??????"),
        "users": ",".join(str(uid) for uid in expert_uids),
        **{
            k: v
            for k, v in invite_cfg.items()
            if k
            not in {
                "enabled",
                "province",
                "city",
                "major_ids",
                "extract_way",
                "take_time",
                "type",
                "address",
                "use_time",
                "check",
                "approve",
            }
        },
    }


def save_project_review_config(
    pm: ZjgjClient,
    project_id: int,
    section_id: int,
    config: dict,
) -> dict[str, Any] | None:
    """Save review/scoring table (????) before expert invite."""
    review_cfg = config.get("review") or {}
    if review_cfg.get("enabled") is False:
        print("stage: review config skipped (disabled)")
        return None

    categories = review_cfg.get("categories")
    if categories is not None:
        total = review_categories_total(categories)
        if total != 100:
            raise ZjgjApiError(-1, f"review categories must sum to 100, got {total}")

    publish = config.get("publish", {})
    project_info = pm.get_publicity_project_info(project_id).get("data") or {}
    cate_id = int(review_cfg.get("cate_id") or project_info.get("cate_id") or publish.get("cate_id") or 1)
    pattern_id = int(review_cfg.get("pattern_id") or project_info.get("pattern_id") or publish.get("pattern_id") or 1)

    resp = pm.save_review_config(
        project_id,
        section_id,
        categories,
        cate_id=cate_id,
        pattern_id=pattern_id,
    )
    print("stage: review config saved")
    return resp


def invite_project_experts(
    expert_cfgs: list[dict[str, Any]],
    *,
    base_url: str,
    pm: ZjgjClient,
    project_id: int,
    section_id: int,
    config: dict,
) -> dict[str, Any] | None:
    invite_cfg = config.get("expert_invite", {})
    if not invite_cfg.get("enabled", True):
        return None

    expert_uids = [resolve_expert_uid(expert_cfg, make_client(base_url, expert_cfg["token"], config)) for expert_cfg in expert_cfgs]
    payload = build_expert_invite_payload(
        project_id=project_id,
        section_id=section_id,
        expert_uids=expert_uids,
        config=config,
        expert_cfgs=expert_cfgs,
        base_url=base_url,
    )
    invite_resp = pm.add_expert_to_project(payload)
    print(f"stage: expert invite ok: users={payload['users']}")
    return invite_resp


def run_expert_sign_flow(
    expert_cfg: dict[str, Any],
    *,
    base_url: str,
    project_id: int,
    section_id: int,
    config: dict,
    pm: ZjgjClient | None = None,
    project_title: str | None = None,
) -> dict[str, Any]:
    token = expert_cfg["token"]
    client = make_client(base_url, token, config)
    profile = client.get_expert_profile()
    label = expert_label(expert_cfg, profile)
    print(f"=== expert sign: {label} ===")

    expert_data = profile.get("data") or {}
    expert_id = resolve_expert_id(expert_cfg, client)
    expert_uid = resolve_expert_uid(expert_cfg, client)
    expert_actions = config.get("expert_actions", {})
    user = expert_data.get("user") or {}

    result: dict[str, Any] = {
        "name": label,
        "expert_id": expert_id,
        "uid": expert_uid,
        "mobile": user.get("mobile") or expert_data.get("mobile"),
        "major_name": expert_data.get("major_name"),
    }

    if not expert_actions.get("sign", True):
        result["skipped"] = True
        result["reason"] = "sign disabled"
        print(f"[{label}] expert sign skipped (disabled)")
        return result

    invite_id = resolve_expert_invite_id(
        expert_cfg,
        client,
        project_id=project_id,
        section_id=section_id,
        pm=pm,
        project_title=project_title,
        expert_actions=expert_actions,
    )
    result["invite_id"] = invite_id

    if invite_id is None:
        result["ok"] = False
        result["error"] = "invite_id not found"
        print(f"[{label}] expert sign failed: invite_id not found")
        return result

    try:
        sign_resp = client.expert_sign_in(project_id, section_id, int(invite_id))
        result["ok"] = True
        result["sign"] = sign_resp
        result["msg"] = sign_resp.get("msg")
        print(f"[{label}] expert sign ok: invite_id={invite_id}")
    except ZjgjApiError as exc:
        result["ok"] = False
        result["sign_error"] = str(exc)
        result["error"] = str(exc)
        print(f"[{label}] expert sign failed: {exc}")

    return result


def run_expert_sign_all(
    project_id: int,
    section_id: int,
    expert_cfgs: list[dict[str, Any]],
    *,
    base_url: str,
    config: dict,
    pm: ZjgjClient | None = None,
    project_title: str | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for expert_cfg in expert_cfgs:
        results.append(
            run_expert_sign_flow(
                expert_cfg,
                base_url=base_url,
                project_id=project_id,
                section_id=section_id,
                config=config,
                pm=pm,
                project_title=project_title,
            )
        )
    ok_count = sum(1 for item in results if item.get("ok"))
    print(f"stage: expert sign {ok_count}/{len(results)} ok")
    return results


def fetch_expert_vote_status(
    pm: ZjgjClient | None,
    client: ZjgjClient,
    project_id: int,
    section_id: int,
    expert_uid: int,
) -> dict[str, Any]:
    """Read is_vote / is_leader / sign_id from inviteInfo and api/expert/list."""
    invite_row: dict[str, Any] = {}
    if pm is not None:
        invite = pm.get_manage_invite_info(project_id, section_id).get("data") or {}
        info = invite.get("info") or {}
        for user in info.get("users") or []:
            if int(user.get("uid", -1)) == expert_uid:
                invite_row = user
                break

    list_row: dict[str, Any] = {}
    for status in (0, 1, 2, 3, 4, 6):
        listing = client.list_expert_invites(page=1, limit=50, status=status)
        for item in (listing.get("data") or {}).get("list", []):
            if int(item.get("project_id", -1)) == project_id:
                list_row = item
                break
        if list_row:
            break

    is_vote = list_row.get("is_vote") if list_row.get("is_vote") is not None else invite_row.get("is_vote")
    is_leader = list_row.get("is_leader") if list_row.get("is_leader") is not None else invite_row.get("is_leader")
    return {
        "is_vote": is_vote,
        "is_leader": is_leader,
        "sign_id": list_row.get("sign_id"),
    }


def summarize_leader_election_status(
    expert_cfgs: list[dict[str, Any]],
    clients: list[ZjgjClient],
    pm: ZjgjClient | None,
    project_id: int,
    section_id: int,
) -> tuple[bool, bool, list[dict[str, Any]]]:
    statuses: list[dict[str, Any]] = []
    for expert_cfg, client in zip(expert_cfgs, clients):
        uid = int(expert_cfg.get("uid") or resolve_expert_uid(expert_cfg, client))
        row = fetch_expert_vote_status(pm, client, project_id, section_id, uid)
        statuses.append({"uid": uid, **row})
    leader_elected = any(row.get("is_leader") == 1 for row in statuses)
    all_voted = bool(statuses) and all(row.get("is_vote") == 1 for row in statuses)
    return leader_elected, all_voted, statuses


def resolve_leader_sign_id(
    project_id: int,
    section_id: int,
    expert_cfgs: list[dict[str, Any]],
    clients: list[ZjgjClient],
    pm: ZjgjClient | None,
    *,
    leader_sign_id: int | None = None,
    vote_statuses: list[dict[str, Any]] | None = None,
) -> int | None:
    if leader_sign_id is not None:
        return int(leader_sign_id)

    statuses = vote_statuses
    if statuses is None:
        _, _, statuses = summarize_leader_election_status(expert_cfgs, clients, pm, project_id, section_id)

    for row in statuses:
        if row.get("is_leader") == 1 and row.get("sign_id"):
            return int(row["sign_id"])
    for row in statuses:
        if row.get("sign_id"):
            return int(row["sign_id"])

    discovered = clients[0].discover_leader_candidate_sign_ids(project_id, section_id)
    return int(discovered[0]) if discovered else None


def run_expert_leader_election(
    project_id: int,
    section_id: int,
    expert_cfgs: list[dict[str, Any]],
    *,
    base_url: str,
    config: dict,
    leader_sign_id: int | None = None,
    pm: ZjgjClient | None = None,
) -> dict[str, Any]:
    """Opt-in: each signed expert votes once via GET api/expert/leaderVote."""
    expert_actions = config.get("expert_actions", {})
    if not expert_actions.get("elect_leader", False):
        return {"skipped": True, "reason": "elect_leader disabled"}

    if not expert_cfgs:
        return {"ok": False, "error": "no experts configured"}

    clients = [make_client(base_url, expert_cfg["token"], config) for expert_cfg in expert_cfgs]
    leader_elected, all_voted, vote_statuses = summarize_leader_election_status(
        expert_cfgs, clients, pm, project_id, section_id
    )

    if leader_elected and all_voted:
        target_sign_id = resolve_leader_sign_id(
            project_id,
            section_id,
            expert_cfgs,
            clients,
            pm,
            leader_sign_id=leader_sign_id,
            vote_statuses=vote_statuses,
        )
        print(f"stage: leader election skipped (already complete, sign_id={target_sign_id})")
        return {
            "leader_sign_id": target_sign_id,
            "experts": [
                {
                    "uid": row.get("uid"),
                    "ok": True,
                    "skipped": True,
                    "reason": "already voted (is_vote=1)",
                    "is_vote": row.get("is_vote"),
                    "is_leader": row.get("is_leader"),
                }
                for row in vote_statuses
            ],
            "ok": True,
            "leader_elected": True,
            "all_voted": True,
            "skipped": True,
            "reason": "leader already elected and all experts voted",
        }

    target_sign_id = resolve_leader_sign_id(
        project_id,
        section_id,
        expert_cfgs,
        clients,
        pm,
        leader_sign_id=leader_sign_id,
        vote_statuses=vote_statuses,
    )
    if target_sign_id is None:
        return {"ok": False, "error": "no leader candidate sign_id found", "leader_elected": leader_elected, "all_voted": all_voted}
    if leader_sign_id is None:
        print(f"stage: leader election using sign_id={target_sign_id}")

    results: list[dict[str, Any]] = []
    for expert_cfg, client in zip(expert_cfgs, clients):
        uid = int(expert_cfg.get("uid") or resolve_expert_uid(expert_cfg, client))
        label = expert_cfg.get("name") or expert_cfg.get("mobile") or "expert"
        vote_row = next((row for row in vote_statuses if row.get("uid") == uid), {})
        item: dict[str, Any] = {
            "name": label,
            "uid": uid,
            "sign_id": target_sign_id,
            "is_vote_before": vote_row.get("is_vote"),
        }

        if vote_row.get("is_vote") == 1:
            item["ok"] = True
            item["skipped"] = True
            item["reason"] = "already voted (is_vote=1)"
            item["msg"] = "idempotent skip"
            results.append(item)
            print(f"[{label}] leader vote skipped: already voted (is_vote=1)")
            continue

        try:
            resp = client.vote_expert_leader(project_id, section_id, int(target_sign_id))
            msg = str(resp.get("msg") or "")
            item["ok"] = True
            item["msg"] = msg
            if leader_vote_already_done(msg):
                item["already_voted"] = True
        except ZjgjApiError as exc:
            msg = str(exc)
            item["ok"] = leader_vote_already_done(msg)
            item["error"] = msg
            item["msg"] = msg
            if item["ok"]:
                item["already_voted"] = True
        results.append(item)
        status = "ok" if item.get("ok") else "fail"
        detail = item.get("msg") or item.get("error")
        print(f"[{label}] leader vote {status}: sign_id={target_sign_id} {detail}")

    leader_elected, all_voted, _ = summarize_leader_election_status(expert_cfgs, clients, pm, project_id, section_id)
    ok_count = sum(1 for item in results if item.get("ok"))
    print(f"stage: leader election {ok_count}/{len(results)} ok (sign_id={target_sign_id})")
    return {
        "leader_sign_id": target_sign_id,
        "experts": results,
        "ok": ok_count == len(results),
        "leader_elected": leader_elected,
        "all_voted": all_voted,
    }


def run_expert_flow(
    expert_cfg: dict[str, Any],
    *,
    base_url: str,
    project_id: int,
    section_id: int,
    config: dict,
    pm: ZjgjClient | None = None,
    project_title: str | None = None,
    do_confirm: bool | None = None,
    do_sign: bool | None = None,
) -> dict[str, Any]:
    expert_actions = config.get("expert_actions", {})
    confirm = expert_agree_invite_enabled(config) if do_confirm is None else do_confirm
    sign = expert_actions.get("sign", True) if do_sign is None else do_sign

    result: dict[str, Any] = {"name": expert_cfg.get("name")}
    if confirm:
        confirm_result = confirm_expert_invite_for_cfg(
            expert_cfg,
            base_url=base_url,
            project_id=project_id,
            section_id=section_id,
            config=config,
            pm=pm,
            project_title=project_title,
        )
        result.update(confirm_result)
    if sign:
        sign_result = run_expert_sign_flow(
            expert_cfg,
            base_url=base_url,
            project_id=project_id,
            section_id=section_id,
            config=config,
            pm=pm,
            project_title=project_title,
        )
        if confirm:
            sign_result.pop("name", None)
            sign_result.pop("expert_id", None)
            sign_result.pop("uid", None)
            sign_result.pop("mobile", None)
            sign_result.pop("major_name", None)
            if sign_result.get("invite_id") is None and result.get("invite_id") is not None:
                sign_result["invite_id"] = result["invite_id"]
            result.update(sign_result)
        else:
            result = sign_result
    return result


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


def find_existing_register_id(client: ZjgjClient, project_id: int, section_id: int) -> int | None:
    listing = client.request(
        "GET",
        "api/project_register/myList",
        params={"page": 1, "limit": 50},
        require_auth=True,
    )
    for item in (listing.get("data") or {}).get("list", []):
        if int(item.get("project_id", -1)) == project_id and int(item.get("section_id", section_id)) == section_id:
            return int(item["id"])
    return None


def has_submitted_tender(client: ZjgjClient, tender_id: int, section_id: int) -> bool:
    try:
        resp = client.get_tender_file(tender_id, section_id)
        data = resp.get("data") or {}
        return bool(data.get("id") or data.get("files"))
    except ZjgjApiError:
        return False


def resolve_tender_id(bidder: ZjgjClient, project_id: int, section_id: int) -> int:
    tender_list = bidder.list_my_tenders(page=1, limit=50)
    for item in (tender_list.get("data") or {}).get("list", []):
        if int(item.get("project_id", -1)) == project_id:
            tender_id = item.get("tender_id") or item.get("id")
            if tender_id is not None:
                return int(tender_id)

    tender_detail = bidder.get_tender_project(project_id, section_id)
    tender_id = extract_id(tender_detail, "tender_id", "id")
    if tender_id is not None:
        return tender_id
    raise ZjgjApiError(-1, "unable to resolve tender_id after registration", tender_list)


def build_register_files_payload(client: ZjgjClient, register_cfg: dict[str, Any]) -> str | None:
    return build_images_payload(client, register_cfg)


def build_publish_files_payload(client: ZjgjClient, publish_cfg: dict[str, Any]) -> str | None:
    return build_images_payload(client, publish_cfg)


def scan_bidding_files(project_dir: Path) -> list[str]:
    bidding_dir = next(
        (project_dir / name for name in BIDDING_DIR_NAMES if (project_dir / name).is_dir()),
        None,
    )
    if not bidding_dir:
        return []
    return sorted(
        str(path)
        for path in bidding_dir.iterdir()
        if path.is_file() and path.suffix.lower() in BIDDING_FILE_SUFFIXES
    )


def resolve_publish_upload_files(config: dict[str, Any]) -> list[str]:
    """Resolve ???? paths for stage1 publish (config ??project_folder ??disk scan)."""
    publish = config.get("publish") or {}
    folder = config.get("project_folder") or {}
    paths: list[str] = []
    if publish.get("upload_files"):
        paths.extend(str(path) for path in publish["upload_files"])
    if publish.get("upload_file"):
        paths.append(str(publish["upload_file"]))
    if not paths:
        paths.extend(str(path) for path in folder.get("bidding_files") or [])
    if not paths:
        project_dir = folder.get("project_dir")
        if project_dir:
            paths.extend(scan_bidding_files(Path(project_dir)))

    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def publish_change_publicity(
    client: ZjgjClient,
    project_id: int,
    *,
    upload_paths: list[str] | None = None,
    images: str | None = None,
) -> dict[str, Any]:
    """????: POST api/publicity/create with id (same as admin /project/change/:id form)."""
    project_info = client.get_publicity_project_info(project_id)
    data = project_info.get("data") or {}
    if not data:
        raise ZjgjApiError(-1, f"project {project_id} not found", project_info)

    if images is None:
        if not upload_paths:
            raise ZjgjApiError(-1, "upload_paths or images is required", None)
        images = build_publish_files_payload(client, {"upload_files": upload_paths})
    else:
        images = normalize_publish_images(images)
    if not images:
        raise ZjgjApiError(-1, "no attachment payload built", None)

    payload = {
        "id": project_id,
        "company_id": data.get("company_id"),
        "project_no": data.get("project_no"),
        "title": data.get("title"),
        "cate_id": data.get("cate_id"),
        "username": data.get("username"),
        "address": data.get("address"),
        "pattern_id": data.get("pattern_id"),
        "start_time": data.get("start_time"),
        "file_start_time": data.get("file_start_time"),
        "file_end_time": data.get("file_end_time"),
        "platform_price": data.get("platform_price", "1.00"),
        "file_price": data.get("file_price", "1.00"),
        "is_bid_section": data.get("is_bid_section", 0),
        "deposit": data.get("deposit", "0.00"),
        "intro": data.get("intro") or f"<p>{data.get('title', '')}</p>",
        "images": images,
        "is_min": data.get("is_min", 2),
        "is_audit": data.get("is_audit", 0),
        "region": data.get("region"),
        "industry_id": data.get("industry_id", 1),
    }
    if data.get("is_bid_section") == 1 and data.get("sections"):
        payload["sections"] = data.get("sections")
    return client.publish_change_project(project_id, payload)


def patch_publicity_attachments(
    client: ZjgjClient,
    project_id: int,
    *,
    upload_paths: list[str] | None = None,
    images: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible alias for publish_change_publicity."""
    return publish_change_publicity(
        client,
        project_id,
        upload_paths=upload_paths,
        images=images,
    )


def build_files_payload(bidder: ZjgjClient, submit_cfg: dict[str, Any]) -> str:
    files = submit_cfg.get("files")
    if files:
        return files if isinstance(files, str) else json.dumps(files, ensure_ascii=False)

    upload_paths: list[str] = []
    if submit_cfg.get("upload_files"):
        upload_paths.extend(str(path) for path in submit_cfg["upload_files"])
    if submit_cfg.get("upload_file"):
        upload_paths.append(str(submit_cfg["upload_file"]))
    if not upload_paths:
        raise SystemExit("submit.files, submit.upload_file or submit.upload_files is required for stage 3")

    uploaded_files: list[dict[str, str]] = []
    for upload_path in upload_paths:
        upload_resp = bidder.upload_image(upload_path)
        uploaded = (upload_resp.get("data") or upload_resp.get("result") or {}).get("url")
        if not uploaded:
            raise ZjgjApiError(-1, "upload succeeded but file url missing", upload_resp)
        uploaded_files.append({"name": Path(upload_path).name, "tempFilePath": uploaded})
    return json.dumps(uploaded_files, ensure_ascii=False)


def run_bidder_flow(
    bidder_cfg: dict[str, Any],
    *,
    base_url: str,
    pm: ZjgjClient,
    project_id: int,
    section_id: int,
    config: dict,
) -> dict[str, Any]:
    token = bidder_cfg["token"]
    client = make_client(base_url, token, config)
    profile = client.get_user_profile()
    label = bidder_label(bidder_cfg, profile)
    print(f"=== bidder: {label} ===")

    register_defaults = config.get("register", {})
    register_overrides = bidder_cfg.get("register", {})
    register_merged = {**register_defaults, **register_overrides}
    if register_merged.get("contact_phone") is None and register_merged.get("mobile"):
        register_merged["contact_phone"] = register_merged["mobile"]

    register_id = find_existing_register_id(client, project_id, section_id)
    register_resp = None
    register_skipped = False
    if register_id is not None:
        register_skipped = True
        print(f"[{label}] stage2 register skipped (existing): register_id={register_id}")
    else:
        register_payload = {
            "project_id": project_id,
            "section_id": section_id,
            **{k: v for k, v in register_merged.items() if k not in {"upload_file", "upload_files", "images", "mobile"}},
        }
        register_files = build_register_files_payload(client, register_merged)
        if register_files:
            register_payload["images"] = register_files

        client.check_register(project_id, section_id)
        register_resp = client.register_project(register_payload)
        register_id = extract_id(register_resp, "id", "register_id")
        if register_id is None:
            raise ZjgjApiError(-1, f"[{label}] register succeeded but register_id missing", register_resp)
        print(f"[{label}] stage2 register ok: register_id={register_id}")

    publish_cfg = config.get("publish", {})
    if publish_cfg.get("is_audit", 0) == 1:
        pm.audit_register(register_id, status=1)
        print(f"[{label}] stage2 register audit approved")

    reg_info = client.get_register_info(register_id).get("data") or {}
    pay_state = reg_info.get("pay_state")
    pay_state_name = reg_info.get("pay_state_name")

    pay_cfg = {**config.get("payment", {}), **bidder_cfg.get("payment", {})}
    payment_result = None
    payment_skipped = pay_state == 2
    if pay_cfg.get("enabled", True):
        if payment_skipped:
            print(f"[{label}] stage2 payment skipped (already paid): pay_state={pay_state}")
        else:
            payment_mode = pay_cfg.get("mode", "bidder")
            if payment_mode == "admin_mock":
                client.pay_register(
                    {"id": register_id, "pay_way": pay_cfg.get("pay_way", "bank")},
                    use_v3=False,
                )
                payment_result = pm.admin_mock_payment(register_id)
                print(f"[{label}] stage2 admin mock payment ok: register_id={register_id}")
                reg_info = client.get_register_info(register_id).get("data") or {}
                pay_state = reg_info.get("pay_state")
                pay_state_name = reg_info.get("pay_state_name")
            else:
                pay_payload = {
                    "id": register_id,
                    "pay_way": pay_cfg.get("pay_way", "bank"),
                    **{
                        k: v
                        for k, v in pay_cfg.items()
                        if k not in {"enabled", "mode", "pay_way", "use_v3", "wait_timeout_sec", "poll_sec"}
                    },
                }
                payment_result = client.pay_register(pay_payload, use_v3=pay_cfg.get("use_v3", True))
                print(f"[{label}] stage2 payment request sent")

            wait_timeout = int(pay_cfg.get("wait_timeout_sec", 0))
            if wait_timeout > 0:
                wait_register_completed(
                    client,
                    register_id,
                    timeout_sec=wait_timeout,
                    poll_sec=int(pay_cfg.get("poll_sec", 5)),
                )
                print(f"[{label}] stage2 payment completed")
                reg_info = client.get_register_info(register_id).get("data") or {}
                pay_state = reg_info.get("pay_state")
                pay_state_name = reg_info.get("pay_state_name")
    else:
        print(f"[{label}] stage2 payment skipped by config")

    tender_id = resolve_tender_id(client, project_id, section_id)
    submit_defaults = config.get("submit", {})
    submit_overrides = bidder_cfg.get("submit", {})
    submit_cfg = {**submit_defaults, **submit_overrides}
    if submit_cfg.get("mobile") is None and register_merged.get("contact_phone"):
        submit_cfg["mobile"] = register_merged["contact_phone"]
    submit_resp = None
    submit_skipped = has_submitted_tender(client, tender_id, section_id)
    if submit_skipped:
        print(f"[{label}] stage3 submit skipped (already submitted): tender_id={tender_id}")
    else:
        files = build_files_payload(client, submit_cfg)
        submit_payload = {
            "tender_id": tender_id,
            "section_id": section_id,
            "apply_id": register_id,
            "files": files,
            **{k: v for k, v in submit_cfg.items() if k not in {"files", "upload_file", "upload_files"}},
        }
        submit_resp = client.submit_tender_file(submit_payload)
        print(f"[{label}] stage3 submit ok")

    user = profile.get("data") or {}
    return {
        "name": label,
        "mobile": user.get("mobile"),
        "user_type": user.get("user_type"),
        "register_id": register_id,
        "register_skipped": register_skipped,
        "tender_id": tender_id,
        "pay_state": pay_state,
        "pay_state_name": pay_state_name,
        "payment_skipped": payment_skipped,
        "payment": payment_result,
        "submit_skipped": submit_skipped,
        "submit": submit_resp,
    }


def run_health_check(base_url: str, *, verify_ssl: bool = True) -> None:
    client = ZjgjClient(base_url=base_url, verify_ssl=verify_ssl)
    index = client.health_check()
    projects = client.list_public_projects(page=1, limit=3)
    print("health_check: ok")
    print(f"carousel_count={len((index.get('data') or {}).get('carousel', []))}")
    print(f"public_project_count={(projects.get('data') or {}).get('count')}")


def validate_tokens(config: dict) -> dict:
    base_url = config["base_url"]
    pm_token = config.get("tokens", {}).get("project_manager")
    bidders = normalize_bidders(config.get("tokens", {}))
    if not pm_token:
        raise SystemExit("tokens.project_manager is required")
    if not bidders:
        raise SystemExit("tokens.bidders (or tokens.bidder) is required")

    pm = make_client(base_url, pm_token, config)
    pm_profile = pm.get_user_profile()
    result = {
        "project_manager": {
            "profile": pm_profile.get("data"),
            "can_publish": True,
        },
        "bidders": [],
    }

    for bidder_cfg in bidders:
        client = make_client(base_url, bidder_cfg["token"], config)
        profile = client.get_user_profile()
        label = bidder_label(bidder_cfg, profile)
        data = profile.get("data") or {}
        result["bidders"].append(
            {
                "name": label,
                "mobile": data.get("mobile"),
                "user_type": data.get("user_type"),
                "status": data.get("status_name"),
                "registers": len((client.request("GET", "api/project_register/myList", params={"page": 1, "limit": 1}, require_auth=True).get("data") or {}).get("list", [])),
                "tenders": len((client.list_my_tenders(page=1, limit=1).get("data") or {}).get("list", [])),
            }
        )

    experts = normalize_experts(config.get("tokens", {}))
    result["experts"] = []
    for expert_cfg in experts:
        client = make_client(base_url, expert_cfg["token"], config)
        profile = client.get_expert_profile()
        label = expert_label(expert_cfg, profile)
        data = profile.get("data") or {}
        user = data.get("user") or {}
        result["experts"].append(
            {
                "name": label,
                "expert_id": data.get("id"),
                "uid": (data.get("user") or {}).get("id") or data.get("uid"),
                "mobile": user.get("mobile") or data.get("mobile"),
                "major_name": data.get("major_name"),
                "expert_status": data.get("status"),
                "projects": len((client.list_expert_projects(page=1, limit=1).get("data") or {}).get("list", [])),
            }
        )
    return result


def run_flow(config: dict, *, dry_run: bool) -> dict:
    base_url = config["base_url"]
    pm_token = config.get("tokens", {}).get("project_manager")
    bidders = normalize_bidders(config.get("tokens", {}))

    if dry_run:
        print("[dry-run] validating project manager, bidders and experts")
        return validate_tokens(config)

    if not pm_token or not bidders:
        raise SystemExit(
            "Missing tokens. Set tokens.project_manager and tokens.bidders. "
            "This environment does not expose /api/login/check."
        )

    pm = make_client(base_url, pm_token, config)
    experts = normalize_experts(config.get("tokens", {}))
    result: dict[str, Any] = {"base_url": base_url, "bidders": [], "experts": []}

    existing = config.get("existing_project") or {}
    project_id = existing.get("project_id")
    section_id = existing.get("section_id")
    if project_id is None:
        publish_cfg = config.setdefault("publish", {})
        upload_paths = resolve_publish_upload_files(config)
        if upload_paths:
            publish_cfg["upload_files"] = upload_paths

        publish_payload = build_publish_payload(config)
        publish_payload.pop("images", None)
        if upload_paths:
            publish_images = build_publish_files_payload(pm, {"upload_files": upload_paths})
            if publish_images:
                publish_payload["images"] = publish_images
                uploaded_count = len(json.loads(publish_images))
                print(f"stage1 publish: uploaded {uploaded_count} bidding file(s)")
        create_resp = pm.create_publicity_project(publish_payload)
        project_id = extract_id(create_resp, "project_id", "id")
        if project_id is None:
            project_id = resolve_created_project_id(pm, publish_payload)
        print(f"stage1 publish ok: project_id={project_id} start_time={publish_payload.get('start_time')}")

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

        review_cfg = config.get("review")
        if review_cfg:
            if review_cfg.get("categories"):
                total = review_categories_total(review_cfg["categories"])
                if total != 100:
                    raise ZjgjApiError(-1, f"review categories must sum to 100, got {total}")
                publish = config.get("publish", {})
                pm.save_review_config(
                    project_id,
                    section_id,
                    review_cfg["categories"],
                    cate_id=int(review_cfg.get("cate_id") or publish.get("cate_id") or 1),
                    pattern_id=int(review_cfg.get("pattern_id") or publish.get("pattern_id") or 1),
                )
            else:
                review_payload = {"project_id": project_id, **review_cfg}
                pm.save_publicity_review(review_payload)
            print("stage1 review config saved")
    else:
        project_id = int(project_id)
        if section_id is None:
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
        else:
            section_id = int(section_id)
        print(f"stage1 publish skipped: project_id={project_id}, section_id={section_id}")

    result["project_id"] = project_id
    result["section_id"] = section_id

    for bidder_cfg in bidders:
        try:
            bidder_result = run_bidder_flow(
                bidder_cfg,
                base_url=base_url,
                pm=pm,
                project_id=project_id,
                section_id=section_id,
                config=config,
            )
        except ZjgjApiError as exc:
            label = bidder_cfg.get("name") or bidder_cfg.get("token", "")[:8]
            print(f"[{label}] bidder flow failed: {exc}")
            bidder_result = {
                "name": label,
                "error": str(exc),
                "payload": exc.payload,
            }
        result["bidders"].append(bidder_result)

    expert_cfg_root = config.get("experts", {})
    run_experts = config.get("flow", {}).get("experts", True)
    if experts and expert_cfg_root.get("enabled", True) and run_experts:
        publish_cfg = config.get("publish", {})
        project_info = pm.get_publicity_project_info(project_id).get("data") or {}
        start_time_str = project_info.get("start_time") or publish_cfg.get("start_time")
        wait_open_sec = int(publish_cfg.get("wait_open_sec", 120))
        poll_sec = int(publish_cfg.get("poll_sec", 5))
        project_title = config.get("publish", {}).get("title") or project_info.get("title")

        review_resp = save_project_review_config(pm, project_id, section_id, config)
        if review_resp is not None:
            result["review_config"] = review_resp

        invite_resp = invite_project_experts(
            experts,
            base_url=base_url,
            pm=pm,
            project_id=project_id,
            section_id=section_id,
            config=config,
        )
        if invite_resp is not None:
            result["expert_invite"] = invite_resp

        audit_result = audit_all_expert_invites(
            project_id,
            section_id,
            experts,
            base_url=base_url,
            config=config,
            pm=pm,
        )
        if not audit_result.get("skipped"):
            result["expert_audit"] = audit_result

        if expert_agree_invite_enabled(config):
            confirm_results = confirm_all_expert_invites(
                project_id,
                section_id,
                experts,
                base_url=base_url,
                config=config,
                pm=pm,
                project_title=project_title,
            )
            result["expert_agree_invite"] = confirm_results

        wait_until_start_time(start_time_str, poll_sec=poll_sec, label=str(project_id))
        if section_state(pm, project_id) != 1 and wait_open_sec > 0:
            print(f"[{project_id}] start_time reached, polling section open...")
            opened = wait_for_section_open(pm, project_id, timeout_sec=wait_open_sec, poll_sec=poll_sec)
            result["section_open"] = {"opened": opened, "wait_sec": wait_open_sec}
            if not opened:
                print(f"[{project_id}] section still not opened after {wait_open_sec}s (state!=1)")

        sign_results = run_expert_sign_all(
            project_id,
            section_id,
            experts,
            base_url=base_url,
            config=config,
            pm=pm,
            project_title=project_title,
        )
        result["experts"] = sign_results

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="ZJGJ three-stage bidding automation")
    default_config = Path(__file__).resolve().parent / "config.example.json"
    parser.add_argument("--config", default=str(default_config), help="Path to JSON config")
    parser.add_argument("--health-check", action="store_true", help="Only verify public API connectivity")
    parser.add_argument("--dry-run", action="store_true", help="Validate tokens without mutating data")
    parser.add_argument("--validate-tokens", action="store_true", help="Alias of --dry-run")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")

    config = load_config(config_path)
    base_url = config.get("base_url", "https://www.bidding.shanxiguandian.com")

    if args.health_check:
        run_health_check(base_url, verify_ssl=client_verify_ssl(config))
        return

    dry_run = args.dry_run or args.validate_tokens
    try:
        result = run_flow(config, dry_run=dry_run)
    except ZjgjApiError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        if exc.payload is not None:
            print(json.dumps(exc.payload, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

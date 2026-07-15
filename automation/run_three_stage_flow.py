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


def find_expert_invite_id(
    client: ZjgjClient,
    project_id: int,
    *,
    project_title: str | None = None,
    timeout_sec: int,
    poll_sec: int,
) -> int | None:
    def lookup() -> int | None:
        listing = client.list_expert_projects(page=1, limit=50)
        for item in (listing.get("data") or {}).get("list", []):
            if int(item.get("project_id", -1)) == project_id:
                invite_id = extract_invite_id_from_item(item)
                if invite_id is not None:
                    return invite_id

        for status in (0, 1, 2, 3):
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
                client = ZjgjClient(base_url=base_url, token=expert_cfg["token"])
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
        "address": invite_cfg.get("address", "山西省太原市"),
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
            }
        },
    }


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

    expert_uids = [resolve_expert_uid(expert_cfg, ZjgjClient(base_url=base_url, token=expert_cfg["token"])) for expert_cfg in expert_cfgs]
    payload = build_expert_invite_payload(
        project_id=project_id,
        section_id=section_id,
        expert_uids=expert_uids,
        config=config,
        expert_cfgs=expert_cfgs,
        base_url=base_url,
    )
    invite_resp = pm.add_expert_to_project(payload)
    print(f"stage4 expert invite ok: users={payload['users']}")
    return invite_resp


def run_expert_flow(
    expert_cfg: dict[str, Any],
    *,
    base_url: str,
    project_id: int,
    section_id: int,
    config: dict,
    project_title: str | None = None,
) -> dict[str, Any]:
    token = expert_cfg["token"]
    client = ZjgjClient(base_url=base_url, token=token)
    profile = client.get_expert_profile()
    label = expert_label(expert_cfg, profile)
    print(f"=== expert: {label} ===")

    expert_data = profile.get("data") or {}
    expert_id = resolve_expert_id(expert_cfg, client)
    expert_uid = resolve_expert_uid(expert_cfg, client)
    invite_id = expert_cfg.get("invite_id")
    expert_actions = config.get("expert_actions", {})

    if invite_id is None:
        invite_id = find_expert_invite_id(
            client,
            project_id,
            project_title=project_title,
            timeout_sec=int(expert_actions.get("wait_invite_timeout_sec", 10)),
            poll_sec=int(expert_actions.get("poll_sec", 2)),
        )

    confirm_resp = None
    sign_resp = None
    sign_error = None
    if invite_id is not None and expert_actions.get("confirm", True):
        confirm_resp = client.confirm_expert_invite(int(invite_id), status=1)
        print(f"[{label}] expert invite confirmed: invite_id={invite_id}")

    if invite_id is not None and expert_actions.get("sign", False):
        try:
            sign_resp = client.expert_sign_in(project_id, section_id, int(invite_id))
            print(f"[{label}] expert signed in")
        except ZjgjApiError as exc:
            sign_error = str(exc)
            print(f"[{label}] expert sign skipped: {exc}")

    user = expert_data.get("user") or {}
    return {
        "name": label,
        "expert_id": expert_id,
        "uid": expert_uid,
        "mobile": user.get("mobile") or expert_data.get("mobile"),
        "major_name": expert_data.get("major_name"),
        "invite_id": invite_id,
        "confirm": confirm_resp,
        "sign": sign_resp,
        "sign_error": sign_error,
    }


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


def resolve_tender_id(bidder: ZjgjClient, project_id: int, section_id: int) -> int:
    tender_list = bidder.list_my_tenders(page=1, limit=50)
    for item in (tender_list.get("data") or {}).get("list", []):
        if int(item.get("project_id", -1)) == project_id:
            return int(item["id"])

    tender_detail = bidder.get_tender_project(project_id, section_id)
    tender_id = extract_id(tender_detail, "tender_id", "id")
    if tender_id is not None:
        return tender_id
    raise ZjgjApiError(-1, "unable to resolve tender_id after registration", tender_list)


def build_files_payload(bidder: ZjgjClient, submit_cfg: dict[str, Any]) -> str:
    files = submit_cfg.get("files")
    if files:
        return files if isinstance(files, str) else json.dumps(files, ensure_ascii=False)

    upload_path = submit_cfg.get("upload_file")
    if not upload_path:
        raise SystemExit("submit.files or submit.upload_file is required for stage 3")
    upload_resp = bidder.upload_image(upload_path)
    uploaded = (upload_resp.get("data") or upload_resp.get("result") or {}).get("url")
    if not uploaded:
        raise ZjgjApiError(-1, "upload succeeded but file url missing", upload_resp)
    return json.dumps([{"name": Path(upload_path).name, "url": uploaded}], ensure_ascii=False)


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
    client = ZjgjClient(base_url=base_url, token=token)
    profile = client.get_user_profile()
    label = bidder_label(bidder_cfg, profile)
    print(f"=== bidder: {label} ===")

    register_defaults = config.get("register", {})
    register_overrides = bidder_cfg.get("register", {})
    register_payload = {
        "project_id": project_id,
        "section_id": section_id,
        **register_defaults,
        **register_overrides,
    }

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

    pay_cfg = {**config.get("payment", {}), **bidder_cfg.get("payment", {})}
    payment_result = None
    if pay_cfg.get("enabled", True):
        pay_payload = {
            "id": register_id,
            "pay_way": pay_cfg.get("pay_way", "bank"),
            **{
                k: v
                for k, v in pay_cfg.items()
                if k not in {"enabled", "pay_way", "use_v3", "wait_timeout_sec", "poll_sec"}
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
    else:
        print(f"[{label}] stage2 payment skipped by config")

    tender_id = resolve_tender_id(client, project_id, section_id)
    submit_defaults = config.get("submit", {})
    submit_overrides = bidder_cfg.get("submit", {})
    submit_cfg = {**submit_defaults, **submit_overrides}
    files = build_files_payload(client, submit_cfg)
    submit_payload = {
        "tender_id": tender_id,
        "section_id": section_id,
        "apply_id": register_id,
        "files": files,
        **{k: v for k, v in submit_cfg.items() if k not in {"files", "upload_file"}},
    }
    submit_resp = client.submit_tender_file(submit_payload)
    print(f"[{label}] stage3 submit ok")

    user = profile.get("data") or {}
    return {
        "name": label,
        "mobile": user.get("mobile"),
        "user_type": user.get("user_type"),
        "register_id": register_id,
        "tender_id": tender_id,
        "payment": payment_result,
        "submit": submit_resp,
    }


def run_health_check(base_url: str) -> None:
    client = ZjgjClient(base_url=base_url)
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

    pm = ZjgjClient(base_url=base_url, token=pm_token)
    pm_profile = pm.get_user_profile()
    result = {
        "project_manager": {
            "profile": pm_profile.get("data"),
            "can_publish": True,
        },
        "bidders": [],
    }

    for bidder_cfg in bidders:
        client = ZjgjClient(base_url=base_url, token=bidder_cfg["token"])
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
        client = ZjgjClient(base_url=base_url, token=expert_cfg["token"])
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

    pm = ZjgjClient(base_url=base_url, token=pm_token)
    experts = normalize_experts(config.get("tokens", {}))
    result: dict[str, Any] = {"base_url": base_url, "bidders": [], "experts": []}

    publish_payload = build_publish_payload(config)
    create_resp = pm.create_publicity_project(publish_payload)
    project_id = extract_id(create_resp, "project_id", "id")
    if project_id is None:
        project_id = resolve_created_project_id(pm, publish_payload)
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

    for bidder_cfg in bidders:
        bidder_result = run_bidder_flow(
            bidder_cfg,
            base_url=base_url,
            pm=pm,
            project_id=project_id,
            section_id=section_id,
            config=config,
        )
        result["bidders"].append(bidder_result)

    expert_cfg_root = config.get("experts", {})
    if experts and expert_cfg_root.get("enabled", True):
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

        project_title = config.get("publish", {}).get("title")
        for expert_cfg in experts:
            expert_result = run_expert_flow(
                expert_cfg,
                base_url=base_url,
                project_id=project_id,
                section_id=section_id,
                config=config,
                project_title=project_title,
            )
            result["experts"].append(expert_result)

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
        run_health_check(base_url)
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

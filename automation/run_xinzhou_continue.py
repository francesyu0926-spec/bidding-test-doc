#!/usr/bin/env python3
"""Continue Xinzhou project from register_id 7742: pay + submit only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from run_three_stage_flow import load_config, make_client, run_bidder_flow
from zjgj_client import ZjgjApiError

PROJECT_ID = 2058
SECTION_ID = 1888


def main() -> None:
    config_path = Path(__file__).resolve().parent / "config.xinzhou-changcheng.json"
    config = load_config(config_path)
    base_url = config["base_url"]
    pm = make_client(base_url, config["tokens"]["project_manager"], config)
    bidder_cfg = config["tokens"]["bidders"][0]

    try:
        result = run_bidder_flow(
            bidder_cfg,
            base_url=base_url,
            pm=pm,
            project_id=PROJECT_ID,
            section_id=SECTION_ID,
            config=config,
        )
    except ZjgjApiError as exc:
        if "已报名" in str(exc) or "重复" in str(exc):
            print("register already exists, attempting pay+submit only")
            client = make_client(base_url, bidder_cfg["token"], config)
            listing = client.request(
                "GET",
                "api/project_register/myList",
                params={"page": 1, "limit": 50},
                require_auth=True,
            )
            register_id = None
            for item in (listing.get("data") or {}).get("list", []):
                if int(item.get("project_id", -1)) == PROJECT_ID:
                    register_id = int(item["id"])
                    break
            if register_id is None:
                raise
            pay_cfg = config.get("payment", {})
            client.pay_register(
                {"id": register_id, "pay_way": pay_cfg.get("pay_way", "bank")},
                use_v3=pay_cfg.get("use_v3", False),
            )
            print(f"payment ok: register_id={register_id}")
            from run_three_stage_flow import build_files_payload, resolve_tender_id

            tender_id = resolve_tender_id(client, PROJECT_ID, SECTION_ID)
            submit_cfg = {**config.get("submit", {}), **bidder_cfg.get("submit", {})}
            files = build_files_payload(client, submit_cfg)
            submit_resp = client.submit_tender_file(
                {
                    "tender_id": tender_id,
                    "section_id": SECTION_ID,
                    "apply_id": register_id,
                    "files": files,
                    **{k: v for k, v in submit_cfg.items() if k not in {"files", "upload_file", "upload_files"}},
                }
            )
            result = {"register_id": register_id, "tender_id": tender_id, "submit": submit_resp}
        else:
            print(f"API error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

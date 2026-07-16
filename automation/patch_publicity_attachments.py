#!/usr/bin/env python3
"""Patch missing 招标文件 via 发布变更 API (POST api/publicity/create with id)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from run_three_stage_flow import publish_change_publicity
from zjgj_client import ZjgjApiError, ZjgjClient

DEFAULT_PATCHES = {
    2060: [r"d:\文件\客户项目文件\项目集\3\招标文件\询比文件-剧场主舞台面光灯维护保养服务.pdf"],
    2061: [r"d:\文件\客户项目文件\项目集\4\招标文件\全国科普月太原主场活动项目询比文件（二次）（最终版）.pdf"],
    2062: [r"d:\文件\客户项目文件\项目集\5\招标文件\采购公告-南洋河天镇县一畔庄村南堤防及跨河桥梁项目全过程管理及监理.pdf"],
    2063: [r"d:\文件\客户项目文件\项目集\6\招标文件\中医院视频服务采购文件（3.26）最终稿.pdf"],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="发布变更补传招标文件 (api/publicity/create + id)")
    parser.add_argument("--base-url", default="https://www.bidding.shanxiguandian.com")
    parser.add_argument("--token", default="41ecfede938eb984fe6cfe94c185688f")
    parser.add_argument("--project-id", type=int, action="append", dest="project_ids")
    parser.add_argument("--file", action="append", dest="files", help="Attachment path (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="Only show current images state")
    args = parser.parse_args()

    client = ZjgjClient(base_url=args.base_url, token=args.token, verify_ssl=False)
    targets: dict[int, list[str]] = {}

    if args.project_ids:
        if not args.files:
            raise SystemExit("--file is required when --project-id is set")
        targets[int(args.project_ids[0])] = [str(path) for path in args.files]
    else:
        targets = DEFAULT_PATCHES

    results: list[dict] = []
    for project_id, upload_paths in targets.items():
        before = client.get_publicity_project_info(project_id).get("data") or {}
        entry = {
            "project_id": project_id,
            "endpoint": "POST api/publicity/create (发布变更, with id)",
            "title": before.get("title"),
            "images_before": before.get("images"),
            "upload_paths": upload_paths,
        }
        if args.dry_run:
            entry["status"] = "dry-run"
            results.append(entry)
            continue

        missing_paths = [path for path in upload_paths if not Path(path).exists()]
        if missing_paths:
            entry["status"] = "failed"
            entry["error"] = f"missing files: {missing_paths}"
            results.append(entry)
            continue

        try:
            resp = publish_change_publicity(client, project_id, upload_paths=upload_paths)
            after = client.get_publicity_project_info(project_id).get("data") or {}
            entry["status"] = "ok"
            entry["response"] = resp
            entry["images_after"] = after.get("images")
        except ZjgjApiError as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
            entry["payload"] = exc.payload
        results.append(entry)

    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    if any(item.get("status") == "failed" for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

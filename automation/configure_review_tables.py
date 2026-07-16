#!/usr/bin/env python3
"""Configure review/scoring tables (评审表格) for projects 2060-2063."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from zjgj_client import (
    DEFAULT_REVIEW_CATEGORIES,
    ZjgjApiError,
    ZjgjClient,
    build_review_form_data,
    review_categories_total,
)

PROJECTS = [
    {"project_id": 2060, "section_id": 1890, "set": 3},
    {"project_id": 2061, "section_id": 1891, "set": 4},
    {"project_id": 2062, "section_id": 1892, "set": 5},
    {"project_id": 2063, "section_id": 1893, "set": 6},
]

DEFAULT_BASE_URL = "https://www.bidding.shanxiguandian.com"
DEFAULT_PM_TOKEN = "41ecfede938eb984fe6cfe94c185688f"


def configure_project(
    client: ZjgjClient,
    project_id: int,
    section_id: int,
    *,
    categories: list[dict[str, Any]] | None = None,
    cate_id: int = 1,
    pattern_id: int = 1,
) -> dict[str, Any]:
    review_categories = categories or DEFAULT_REVIEW_CATEGORIES
    total = review_categories_total(review_categories)
    if total != 100:
        raise ValueError(f"review categories must sum to 100, got {total}")

    form_data = build_review_form_data(
        project_id,
        section_id,
        review_categories,
        cate_id=cate_id,
        pattern_id=pattern_id,
    )
    response = client.save_publicity_review(form_data)
    return {
        "project_id": project_id,
        "section_id": section_id,
        "total_score": total,
        "category_scores": {category["title"]: category["score"] for category in review_categories},
        "api_code": response.get("code"),
        "api_msg": response.get("msg"),
        "success": response.get("code") in (1, "1", 200, "200"),
        "form_field_count": len(form_data),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure review tables with total score 100")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=DEFAULT_PM_TOKEN)
    parser.add_argument("--verify-ssl", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("review_config_results.json"))
    parser.add_argument("--project-id", type=int, action="append", dest="project_ids")
    args = parser.parse_args()

    client = ZjgjClient(
        base_url=args.base_url,
        token=args.token,
        verify_ssl=args.verify_ssl,
    )

    targets = PROJECTS
    if args.project_ids:
        wanted = set(args.project_ids)
        targets = [item for item in PROJECTS if item["project_id"] in wanted]

    results: list[dict[str, Any]] = []
    for target in targets:
        project_id = target["project_id"]
        section_id = target["section_id"]
        try:
            project_info = client.get_publicity_project_info(project_id)
            project_data = project_info.get("data") or {}
            result = configure_project(
                client,
                project_id,
                section_id,
                cate_id=int(project_data.get("cate_id") or 1),
                pattern_id=int(project_data.get("pattern_id") or 1),
            )
            result["set"] = target["set"]
            print(
                f"project {project_id}: {result['api_msg']} "
                f"(total={result['total_score']}, categories={result['category_scores']})"
            )
        except (ZjgjApiError, ValueError) as exc:
            result = {
                "project_id": project_id,
                "section_id": section_id,
                "set": target["set"],
                "success": False,
                "error": str(exc),
            }
            print(f"project {project_id}: FAILED - {exc}")
        results.append(result)

    payload = {
        "base_url": args.base_url,
        "categories": DEFAULT_REVIEW_CATEGORIES,
        "total_score": review_categories_total(DEFAULT_REVIEW_CATEGORIES),
        "results": results,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"results written to {args.output}")
    return 0 if all(item.get("success") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

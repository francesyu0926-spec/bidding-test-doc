#!/usr/bin/env python3
"""Run publish / register / pay / submit flow from a client project folder.

Expected layout:
  <project-dir>/
    招标文件/   # optional bidding documents
    投标文件/   # tender files to upload at submit stage
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bid_pdf_extract import (
    _is_placeholder_contact,
    extract_project_name_from_pdfs,
    extract_publish_fields_from_pdfs,
    extract_register_fields,
    extract_tenderer_name_from_pdfs,
    publish_payload_from_extracted,
    register_payload_from_extracted,
)
from run_three_stage_flow import apply_publish_times, build_publish_payload, load_config, run_flow
from zjgj_client import ZjgjApiError, ZjgjClient

TENDER_DIR_NAMES = ("投标文件", "tender", "tenders")
BIDDING_DIR_NAMES = ("招标文件", "bidding", "bid-documents")
PDF_SUFFIXES = {".pdf", ".doc", ".docx", ".zip", ".rar"}


def scan_project_folder(project_dir: Path) -> dict[str, Any]:
    if not project_dir.is_dir():
        raise SystemExit(f"Project folder not found: {project_dir}")

    folder_title = project_dir.name.strip()
    tender_dir = next((project_dir / name for name in TENDER_DIR_NAMES if (project_dir / name).is_dir()), None)
    bidding_dir = next((project_dir / name for name in BIDDING_DIR_NAMES if (project_dir / name).is_dir()), None)

    tender_files = []
    if tender_dir:
        tender_files = sorted(
            path
            for path in tender_dir.iterdir()
            if path.is_file() and path.suffix.lower() in PDF_SUFFIXES
        )

    bidding_files = []
    if bidding_dir:
        bidding_files = sorted(
            path
            for path in bidding_dir.iterdir()
            if path.is_file() and path.suffix.lower() in PDF_SUFFIXES
        )

    project_info = extract_project_name_from_pdfs(
        bidding_files,
        tender_files,
        folder_title=folder_title,
    )
    title = project_info.get("project_name") or folder_title

    tenderer_info = extract_tenderer_name_from_pdfs(bidding_files)
    tenderer_name = tenderer_info.get("tenderer_name")

    publish_info = extract_publish_fields_from_pdfs(bidding_files)

    extracted_by_file: dict[str, dict] = {}
    for path in tender_files:
        extracted_by_file[str(path)] = extract_register_fields(path)

    return {
        "title": title,
        "tenderer_name": tenderer_name,
        "folder_title": folder_title,
        "project_name_source": project_info,
        "tenderer_name_source": tenderer_info,
        "publish_source": publish_info,
        "tender_files": [str(path) for path in tender_files],
        "bidding_files": [str(path) for path in bidding_files],
        "extracted_by_file": extracted_by_file,
        "project_dir": str(project_dir),
    }


def infer_company_name(tender_files: list[Path], title: str) -> str:
    for path in tender_files:
        stem = path.stem.strip()
        if stem and stem != title and "新建" not in stem and "DOCX" not in stem.upper():
            if len(stem) <= 30 and "投标文件" not in stem:
                return stem
    return "投标单位"


def build_bidders_from_tender_files(
    token_pool: list[dict[str, Any]],
    tender_paths: list[Path],
    extracted_by_file: dict[str, dict],
    *,
    config: dict[str, Any],
    bidding_files: list[str],
    title: str,
) -> list[dict[str, Any]]:
    """Create one bidder per tender file; map tokens round-robin when files exceed tokens."""
    if not token_pool:
        raise SystemExit("base config must define tokens.bidders")
    if not tender_paths:
        raise SystemExit("No tender files found in 投标文件/")

    bidders: list[dict[str, Any]] = []
    for index, tender_path in enumerate(tender_paths):
        template = token_pool[index % len(token_pool)]
        bidder = json.loads(json.dumps(template))
        extracted = extracted_by_file.get(str(tender_path), {})
        pdf_register = register_payload_from_extracted(extracted)
        company_name = (
            pdf_register.get("company_name")
            or infer_company_name([tender_path], title)
        )

        bidder.setdefault("register", {})
        reg = bidder["register"]
        contact_phone = reg.get("contact_phone") or reg.get("mobile")
        if not contact_phone:
            profile_client = ZjgjClient(
                base_url=config["base_url"],
                token=bidder["token"],
                verify_ssl=config.get("verify_ssl", False),
            )
            profile_data = profile_client.get_user_profile().get("data") or {}
            contact_phone = profile_data.get("mobile") or "13800000000"

        reg.update(
            {
                "company_name": company_name,
                "company_address": pdf_register.get("company_address")
                or reg.get("company_address")
                or config.get("register", {}).get("company_address"),
                "contact": pdf_register.get("contact")
                or (reg.get("contact") if not _is_placeholder_contact(reg.get("contact")) else None)
                or extracted.get("legal_person")
                or company_name,
                "contact_phone": contact_phone,
                "email": pdf_register.get("email") or reg.get("email"),
            }
        )
        if bidding_files:
            reg["upload_files"] = bidding_files

        bidder.setdefault("submit", {})
        bidder["submit"]["remark"] = bidder["submit"].get("remark") or f"{company_name} 自动递交"
        bidder["submit"]["upload_files"] = [str(tender_path)]
        bidder["name"] = bidder.get("name") or f"投标人-{index + 1}-{tender_path.stem}"
        if len(tender_paths) > len(token_pool):
            bidder["token_note"] = f"token reused (round-robin {index % len(token_pool) + 1}/{len(token_pool)})"
        bidders.append(bidder)

    return bidders


def build_project_config(base_config: dict[str, Any], scanned: dict[str, Any]) -> dict[str, Any]:
    config = json.loads(json.dumps(base_config))
    config.setdefault("verify_ssl", False)
    title = scanned["title"]
    tender_files = scanned["tender_files"]
    tender_paths = [Path(path) for path in tender_files]
    extracted_by_file = scanned.get("extracted_by_file") or {}

    bidding_files = scanned.get("bidding_files") or []
    publish_source = scanned.get("publish_source") or {}
    pdf_publish = publish_payload_from_extracted(
        publish_source,
        base_publish=config.get("publish", {}),
        fallback_title=title,
    )
    if not pdf_publish.get("username"):
        pdf_publish["username"] = scanned.get("tenderer_name") or config.get("publish", {}).get("username")
    config["publish"] = {
        **config.get("publish", {}),
        **pdf_publish,
    }
    apply_publish_times(config)
    if bidding_files:
        config["publish"]["upload_files"] = bidding_files

    config["flow"] = {
        "experts": False,
        "stages": ["publish", "register", "payment", "submit"],
    }
    config["experts"] = {"enabled": False}

    token_pool = config.get("tokens", {}).get("bidders") or []
    single_bidder = bool(config.get("single_bidder", False))
    if single_bidder:
        primary = next((b for b in token_pool if b.get("name", "").find("13246829826") >= 0), token_pool[0])
        token_pool = [primary]
        tender_paths = tender_paths[:1]

    bidders = build_bidders_from_tender_files(
        token_pool,
        tender_paths,
        extracted_by_file,
        config=config,
        bidding_files=scanned.get("bidding_files") or [],
        title=title,
    )

    config["tokens"]["bidders"] = bidders
    config["project_folder"] = scanned
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 4-stage bidding flow from a project folder")
    parser.add_argument("project_dir", help="Client project folder path")
    parser.add_argument(
        "--base-config",
        default=str(Path(__file__).resolve().parent / "config.example.json"),
        help="Base JSON config with API tokens",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate tokens only")
    parser.add_argument("--write-config", help="Write generated config to this path")
    parser.add_argument(
        "--single-bidder",
        action="store_true",
        help="Use only one bidder/token for the first tender file",
    )
    parser.add_argument(
        "--all-bidders",
        action="store_true",
        help="Deprecated alias: all tender files already map to bidders by default",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Only scan tender PDFs and print extracted registration fields",
    )
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    base_config = load_config(Path(args.base_config))
    if args.single_bidder:
        base_config["single_bidder"] = True
    scanned = scan_project_folder(project_dir)

    if args.extract_only:
        config = build_project_config(base_config, scanned)
        publish_preview = build_publish_payload(config)
        publish_preview.pop("images", None)
        summary = {
            "project_name": scanned.get("title"),
            "project_name_source": scanned.get("project_name_source"),
            "tenderer_name": scanned.get("tenderer_name"),
            "tenderer_name_source": scanned.get("tenderer_name_source"),
            "publish_source": scanned.get("publish_source"),
            "publish": config.get("publish"),
            "publish_upload_files": config.get("publish", {}).get("upload_files"),
            "publish_payload_preview": publish_preview,
            "tender_file_count": len(scanned.get("tender_files") or []),
            "bidder_count": len(config.get("tokens", {}).get("bidders", [])),
            "token_pool_size": len(base_config.get("tokens", {}).get("bidders") or []),
            "extracted_by_file": scanned.get("extracted_by_file"),
            "bidders": [
                {
                    "name": bidder.get("name"),
                    "token_note": bidder.get("token_note"),
                    "pdf": (bidder.get("submit") or {}).get("upload_files", [None])[0],
                    "register": bidder.get("register"),
                }
                for bidder in config.get("tokens", {}).get("bidders", [])
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    config = build_project_config(base_config, scanned)

    print("project folder scan:")
    print(json.dumps(scanned, ensure_ascii=False, indent=2))

    if args.write_config:
        out = Path(args.write_config)
        out.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"config written: {out}")

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

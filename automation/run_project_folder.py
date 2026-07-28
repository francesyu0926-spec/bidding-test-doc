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
    EQUITY_ANALYSIS_PREFIX,
    EQUITY_ASSOCIATED_PREFIX,
    _is_placeholder_contact,
    company_name_from_associated_pdf,
    extraction_use_ocr,
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
SIDECAR_SUFFIX = ".equity-relation.json"


def _is_supplementary_tender_file(path: Path) -> bool:
    name = path.name
    stem = path.stem
    if name.startswith("_backup_") or name.startswith("_upload"):
        return True
    if stem.startswith(EQUITY_ANALYSIS_PREFIX) or "投标股权分析" in name:
        return True
    return False


def _is_associated_tender_file(path: Path) -> bool:
    return path.stem.startswith(EQUITY_ASSOCIATED_PREFIX)


def _is_original_tender_file(path: Path) -> bool:
    if path.suffix.lower() not in PDF_SUFFIXES:
        return False
    if _is_supplementary_tender_file(path) or _is_associated_tender_file(path):
        return False
    return True


def _load_equity_report_index(report_path: Path, project_dir: Path) -> dict[str, str]:
    """Map bid PDF basename -> company_name from equity_tianyancha_report.json."""
    if not report_path.is_file():
        return {}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    folder_key = None
    for part in project_dir.parts:
        if part == "A" and project_dir.name.isdigit():
            folder_key = f"A/{project_dir.name}"
            break
    if folder_key is None:
        parent = project_dir.parent
        if parent.name == "A" and project_dir.name.isdigit():
            folder_key = f"A/{project_dir.name}"

    mapping: dict[str, str] = {}
    entries = report if isinstance(report, list) else [report]
    for entry in entries:
        if folder_key and entry.get("folder") != folder_key:
            continue
        for bidder in entry.get("updated_bidders") or entry.get("original_bidders") or []:
            pdf_name = bidder.get("pdf")
            company = bidder.get("company_name")
            if pdf_name and company:
                mapping[str(pdf_name)] = str(company)
        for item in entry.get("processed") or []:
            source = item.get("source_bid_pdf")
            company = item.get("company_name")
            if source and company:
                mapping[str(source)] = str(company)
    return mapping


def _direct_edit_mode(sidecar: dict[str, Any]) -> str | None:
    direct = sidecar.get("direct_edit") or {}
    mode = direct.get("mode")
    if mode in {"text_replace", "scan_overlay"}:
        return str(mode)
    edit_mode = str(sidecar.get("edit_mode") or "")
    if edit_mode in {"direct_text_replace", "direct_scan_overlay"}:
        return edit_mode
    return None


def _resolve_submit_pdf(sidecar: dict[str, Any], tender_dir: Path) -> Path | None:
    """Prefer in-place edited original over 股权关联 overlay copies."""
    source = sidecar.get("source_bid_pdf")
    if source:
        source_candidate = tender_dir / str(source)
        if source_candidate.is_file() and _direct_edit_mode(sidecar):
            return source_candidate

    outputs = sidecar.get("outputs") or {}
    for key in ("direct_edited_pdf", "adjusted_pdf", "company_named_copy"):
        name = outputs.get(key)
        if not name:
            continue
        candidate = tender_dir / str(name)
        if candidate.is_file():
            return candidate
    if source:
        candidate = tender_dir / str(source)
        if candidate.is_file():
            return candidate
    return None


def _find_equity_analysis_pdf(tender_dir: Path, company_name: str) -> str | None:
    if not company_name:
        return None
    exact = tender_dir / f"{EQUITY_ANALYSIS_PREFIX}{company_name}.pdf"
    if exact.is_file():
        return str(exact)
    for path in tender_dir.glob(f"{EQUITY_ANALYSIS_PREFIX}*.pdf"):
        stem = path.stem[len(EQUITY_ANALYSIS_PREFIX) :]
        if stem == company_name or company_name.startswith(stem) or stem.startswith(company_name):
            return str(path)
    return None


def scan_tender_files(
    tender_dir: Path | None,
    *,
    config: dict[str, Any] | None = None,
    project_dir: Path | None = None,
) -> dict[str, Any]:
    """Classify 投标文件 and select bidder submit PDFs (prefer 股权关联 over originals)."""
    config = config or {}
    equity_cfg = config.get("equity") or {}
    catalog: list[dict[str, Any]] = []
    bid_slots: list[dict[str, Any]] = []

    if not tender_dir or not tender_dir.is_dir():
        return {
            "use_associated_bids": False,
            "catalog": catalog,
            "bid_files": [],
            "supplementary_files": [],
        }

    all_files = sorted(
        path for path in tender_dir.iterdir() if path.is_file() and path.suffix.lower() in PDF_SUFFIXES
    )
    for path in all_files:
        if _is_supplementary_tender_file(path):
            kind = "equity_analysis" if "投标股权分析" in path.name else "backup"
        elif _is_associated_tender_file(path):
            kind = "equity_associated"
        else:
            kind = "original_bid"
        catalog.append({"path": str(path), "name": path.name, "kind": kind})

    use_associated = equity_cfg.get("use_associated_bids")
    if use_associated is None:
        use_associated = any(item["kind"] == "equity_associated" for item in catalog) or any(
            path.name.endswith(SIDECAR_SUFFIX) for path in tender_dir.iterdir() if path.is_file()
        )

    if not use_associated:
        bid_paths = [Path(item["path"]) for item in catalog if item["kind"] == "original_bid"]
        return {
            "use_associated_bids": False,
            "catalog": catalog,
            "bid_files": [{"path": str(path), "company_name": None, "kind": "original_bid", "source_pdf": path.name} for path in bid_paths],
            "supplementary_files": [item["path"] for item in catalog if item["kind"] == "equity_analysis"],
        }

    report_path = Path(equity_cfg["report_path"]) if equity_cfg.get("report_path") else Path(__file__).resolve().parent / "equity_tianyancha_report.json"
    report_index = _load_equity_report_index(report_path, project_dir or tender_dir.parent)

    used_paths: set[str] = set()
    used_submit_paths: set[str] = set()
    bid_slots = []

    for sidecar_path in sorted(tender_dir.glob(f"*{SIDECAR_SUFFIX}")):
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        submit_path = _resolve_submit_pdf(sidecar, tender_dir)
        source_pdf = sidecar.get("source_bid_pdf")
        if source_pdf:
            source_candidate = tender_dir / str(source_pdf)
            if source_candidate.is_file():
                used_paths.add(str(source_candidate.resolve()))
        for value in (sidecar.get("outputs") or {}).values():
            output_candidate = tender_dir / str(value)
            if output_candidate.is_file():
                used_paths.add(str(output_candidate.resolve()))

        if submit_path is None:
            continue
        submit_key = str(submit_path.resolve())
        if submit_key in used_submit_paths:
            continue

        company_name = sidecar.get("adjusted_company_name") or company_name_from_associated_pdf(submit_path)
        direct_mode = _direct_edit_mode(sidecar)
        if direct_mode and source_pdf and submit_path.name == str(source_pdf):
            kind = "direct_edited"
        elif _is_associated_tender_file(submit_path):
            kind = "equity_associated"
        else:
            kind = "company_named_copy"
        bid_slots.append(
            {
                "path": str(submit_path),
                "company_name": company_name,
                "kind": kind,
                "source_pdf": source_pdf,
                "relation_type": sidecar.get("relation_type"),
                "direct_edit_mode": direct_mode,
            }
        )
        used_submit_paths.add(submit_key)
        used_paths.add(submit_key)

    for path in all_files:
        if not _is_associated_tender_file(path):
            continue
        path_key = str(path.resolve())
        if path_key in used_submit_paths:
            continue
        company_name = company_name_from_associated_pdf(path)
        bid_slots.append(
            {
                "path": str(path),
                "company_name": company_name,
                "kind": "equity_associated",
                "source_pdf": None,
                "relation_type": None,
            }
        )
        used_submit_paths.add(path_key)
        used_paths.add(path_key)

    for path in all_files:
        if not _is_original_tender_file(path):
            continue
        path_key = str(path.resolve())
        if path_key in used_paths:
            continue
        associated = tender_dir / f"{EQUITY_ASSOCIATED_PREFIX}{path.stem}.pdf"
        if associated.is_file():
            continue
        company_name = report_index.get(path.name) or company_name_from_associated_pdf(path)
        bid_slots.append(
            {
                "path": str(path),
                "company_name": company_name,
                "kind": "original_bid",
                "source_pdf": path.name,
                "relation_type": None,
            }
        )
        used_paths.add(path_key)

    supplementary = [item["path"] for item in catalog if item["kind"] == "equity_analysis"]
    return {
        "use_associated_bids": True,
        "catalog": catalog,
        "bid_files": bid_slots,
        "supplementary_files": supplementary,
        "equity_report": str(report_path) if report_path.is_file() else None,
    }


def _log_pdf_extraction(path: Path, extracted: dict[str, Any], *, role: str) -> None:
    """Print a brief line when OCR fallback was used for a PDF."""
    if extracted.get("text_source") != "ocr":
        return
    detail = (
        extracted.get("company_name")
        or extracted.get("title")
        or extracted.get("username")
        or extracted.get("project_name")
    )
    suffix = f" -> {detail}" if detail else ""
    print(f"pdf extraction (text_source: ocr): {role} {path.name}{suffix}", flush=True)


def scan_project_folder(project_dir: Path, *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    if not project_dir.is_dir():
        raise SystemExit(f"Project folder not found: {project_dir}")

    folder_title = project_dir.name.strip()
    use_ocr = extraction_use_ocr(config)
    tender_dir = next((project_dir / name for name in TENDER_DIR_NAMES if (project_dir / name).is_dir()), None)
    bidding_dir = next((project_dir / name for name in BIDDING_DIR_NAMES if (project_dir / name).is_dir()), None)

    tender_scan = scan_tender_files(tender_dir, config=config, project_dir=project_dir)
    tender_files = [Path(item["path"]) for item in tender_scan.get("bid_files") or []]

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
        use_ocr=use_ocr,
    )
    if project_info.get("text_source") == "ocr":
        source_pdf = project_info.get("source_pdf")
        if source_pdf:
            _log_pdf_extraction(Path(source_pdf), project_info, role="project_name")
    title = project_info.get("project_name") or folder_title

    tenderer_info = extract_tenderer_name_from_pdfs(bidding_files, use_ocr=use_ocr)
    if tenderer_info.get("text_source") == "ocr":
        source_pdf = tenderer_info.get("source_pdf")
        if source_pdf:
            _log_pdf_extraction(Path(source_pdf), tenderer_info, role="tenderer")
    tenderer_name = tenderer_info.get("tenderer_name")

    publish_info = extract_publish_fields_from_pdfs(bidding_files, use_ocr=use_ocr)
    if publish_info.get("text_source") == "ocr":
        source_pdf = publish_info.get("source_pdf")
        if source_pdf:
            _log_pdf_extraction(Path(source_pdf), publish_info, role="publish")

    extracted_by_file: dict[str, dict] = {}
    for path in tender_files:
        extracted = extract_register_fields(path, use_ocr=use_ocr)
        extracted_by_file[str(path)] = extracted
        _log_pdf_extraction(path, extracted, role="register")

    return {
        "title": title,
        "tenderer_name": tenderer_name,
        "folder_title": folder_title,
        "project_name_source": project_info,
        "tenderer_name_source": tenderer_info,
        "publish_source": publish_info,
        "tender_files": [str(path) for path in tender_files],
        "tender_scan": tender_scan,
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


def _company_name_from_tender_filename(
    tender_path: Path,
    slot_meta: dict[str, Any] | None = None,
) -> str:
    """Resolve bidder company name from tender PDF basename (without .pdf)."""
    slot_meta = slot_meta or {}
    source_pdf = slot_meta.get("source_pdf")
    if source_pdf:
        stem = Path(str(source_pdf)).stem.strip()
        if stem:
            return stem
    stem = tender_path.stem.strip()
    if stem:
        return stem
    return "投标单位"


def _tenderer_name_from_bidding_filename(bidding_files: list[str]) -> str | None:
    """Resolve publish 招标人/招标方 from first 招标文件 PDF basename."""
    for path_str in bidding_files:
        stem = Path(path_str).stem.strip()
        if stem:
            return stem
    return None


def build_bidders_from_tender_files(
    token_pool: list[dict[str, Any]],
    tender_paths: list[Path],
    extracted_by_file: dict[str, dict],
    *,
    config: dict[str, Any],
    bidding_files: list[str],
    title: str,
    bid_file_meta: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Create one bidder per tender file; map tokens round-robin when files exceed tokens."""
    if not token_pool:
        raise SystemExit("base config must define tokens.bidders")
    if not tender_paths:
        raise SystemExit("No tender files found in 投标文件/")

    equity_cfg = config.get("equity") or {}
    attach_analysis = bool(equity_cfg.get("attach_analysis_pdfs", False))
    meta_by_path = {item["path"]: item for item in (bid_file_meta or []) if item.get("path")}

    bidders: list[dict[str, Any]] = []
    for index, tender_path in enumerate(tender_paths):
        template = token_pool[index % len(token_pool)]
        bidder = json.loads(json.dumps(template))
        extracted = extracted_by_file.get(str(tender_path), {})
        pdf_register = register_payload_from_extracted(extracted)
        slot_meta = meta_by_path.get(str(tender_path), {})
        if config.get("company_name_from_filename"):
            company_name = _company_name_from_tender_filename(tender_path, slot_meta)
        else:
            slot_company = slot_meta.get("company_name")
            if slot_meta.get("kind") == "original_bid":
                slot_company = None
            company_name = pdf_register.get("company_name") or slot_company or "投标单位"

        bidder.setdefault("register", {})
        reg = bidder["register"]
        contact_phone = (
            pdf_register.get("contact_phone")
            or reg.get("contact_phone")
            or reg.get("mobile")
        )
        if not contact_phone:
            profile_client = ZjgjClient(
                base_url=config["base_url"],
                token=bidder["token"],
                verify_ssl=config.get("verify_ssl", False),
            )
            profile_data = profile_client.get_user_profile().get("data") or {}
            contact_phone = profile_data.get("mobile") or "13800000000"

        email = (
            pdf_register.get("email")
            or reg.get("email")
            or config.get("register", {}).get("email")
        )
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
            }
        )
        if email:
            reg["email"] = email
        elif reg.get("email") is None:
            reg.pop("email", None)
        if bidding_files:
            reg["upload_files"] = bidding_files

        submit_files = [str(tender_path)]
        upload_overrides = (config.get("extraction") or {}).get("upload_file_overrides_by_pdf") or {}
        override_name = upload_overrides.get(tender_path.name)
        if override_name:
            override_path = tender_path.parent / override_name
            if override_path.is_file():
                submit_files = [str(override_path)]
        if attach_analysis:
            tender_dir = tender_path.parent
            analysis_pdf = _find_equity_analysis_pdf(tender_dir, str(company_name))
            if analysis_pdf and analysis_pdf not in submit_files:
                submit_files.append(analysis_pdf)

        bidder.setdefault("submit", {})
        bidder["submit"]["remark"] = bidder["submit"].get("remark") or f"{company_name} 自动递交"
        bidder["submit"]["upload_files"] = submit_files
        bidder["name"] = bidder.get("name") or f"投标人-{index + 1}-{tender_path.stem}"
        if slot_meta:
            bidder["equity"] = {
                "kind": slot_meta.get("kind"),
                "source_pdf": slot_meta.get("source_pdf"),
                "relation_type": slot_meta.get("relation_type"),
            }
        if len(tender_paths) > len(token_pool):
            bidder["token_note"] = f"token reused (round-robin {index % len(token_pool) + 1}/{len(token_pool)})"
        bidders.append(bidder)

    return bidders


def apply_title_prefix(publish: dict[str, Any]) -> None:
    """Prepend publish.title_prefix to title when configured (e.g. 投标股权关系-)."""
    prefix = str(publish.get("title_prefix") or "").strip()
    if not prefix:
        return
    title = str(publish.get("title") or "").strip()
    if title and not title.startswith(prefix):
        publish["title"] = f"{prefix}{title}"


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
    if config.get("tenderer_name_from_filename") and bidding_files:
        filename_tenderer = _tenderer_name_from_bidding_filename(bidding_files)
        if filename_tenderer:
            pdf_publish["username"] = filename_tenderer
    elif not pdf_publish.get("username"):
        pdf_publish["username"] = scanned.get("tenderer_name") or config.get("publish", {}).get("username")
    config["publish"] = {
        **config.get("publish", {}),
        **pdf_publish,
    }
    apply_title_prefix(config["publish"])
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
        bid_file_meta=scanned.get("tender_scan", {}).get("bid_files"),
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
        "--scan",
        action="store_true",
        dest="extract_only",
        help="Only scan project PDFs and print extracted fields (alias: --scan)",
    )
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    base_config = load_config(Path(args.base_config))
    if args.single_bidder:
        base_config["single_bidder"] = True
    scanned = scan_project_folder(project_dir, config=base_config)

    if args.extract_only:
        config = build_project_config(base_config, scanned)
        publish_preview = build_publish_payload(config)
        publish_preview.pop("images", None)
        tender_scan = scanned.get("tender_scan") or {}
        summary = {
            "project_name": scanned.get("title"),
            "project_name_source": scanned.get("project_name_source"),
            "tenderer_name": scanned.get("tenderer_name"),
            "tenderer_name_source": scanned.get("tenderer_name_source"),
            "publish_source": scanned.get("publish_source"),
            "publish": config.get("publish"),
            "publish_upload_files": config.get("publish", {}).get("upload_files"),
            "publish_payload_preview": publish_preview,
            "equity": {
                "use_associated_bids": tender_scan.get("use_associated_bids"),
                "catalog_file_count": len(tender_scan.get("catalog") or []),
                "bidder_slot_count": len(tender_scan.get("bid_files") or []),
                "supplementary_count": len(tender_scan.get("supplementary_files") or []),
                "equity_report": tender_scan.get("equity_report"),
            },
            "tender_scan": tender_scan,
            "tender_file_count": len(scanned.get("tender_files") or []),
            "bidder_count": len(config.get("tokens", {}).get("bidders", [])),
            "token_pool_size": len(base_config.get("tokens", {}).get("bidders") or []),
            "extracted_by_file": scanned.get("extracted_by_file"),
            "bidders": [
                {
                    "name": bidder.get("name"),
                    "token_note": bidder.get("token_note"),
                    "equity": bidder.get("equity"),
                    "pdf": (bidder.get("submit") or {}).get("upload_files", [None])[0],
                    "submit_upload_files": (bidder.get("submit") or {}).get("upload_files"),
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

"""Extract publish and register form fields from 招标文件 and 投标文件 PDFs."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - optional at import time
    PdfReader = None  # type: ignore[misc, assignment]

SKIP_STEMS = {"新建", "docx", "document"}
GENERIC_STEM_KEYWORDS = ("投标文件", "响应文件", "询比采购")
PROJECT_NAME_SUFFIXES = ("投标文件", "响应文件", "招标文件", "询比采购", "竞争性谈判", "公开招标", "邀请招标")
FILENAME_PREFIXES = ("采购公告-", "询比文件-", "招标文件-", "谈判文件-", "公告-", "采购文件-", "正本", "副本")
FILENAME_DOCUMENT_MARKERS = (
    "采购文件",
    "询比文件",
    "谈判文件",
    "招标文件",
    "最终稿",
    "最终版",
    "采购公告",
)
COVER_STOP_KEYWORDS = ("响应文件", "投标文件", "项目编号", "招标编号", "目录", "响 应 文 件", "投 标 文 件")
INVALID_PERSON_TOKENS = ("签字", "盖章", "委托", "签名", "________", "（", ")", "代表")
TENDERER_STOP_MARKERS = (
    "采购代理机构",
    "招标代理机构",
    "代理机构",
    "联系人",
    "联系地址",
    "地址",
    "电话",
    "采购编号",
    "项目编号",
    "招标编号",
    "2026",
    "2025",
    "2024",
)
PROJECT_NAME_FIELD_PATTERNS = [
    r"1\.1\s*采购项目名称[：:]\s*(.+?)(?=\n\s*1\.2|\n\s*项目编号|\n\s*采购编号|\Z)",
    r"采购项目名称[：:]\s*(.+?)(?=\n\s*(?:1\.\d|项目编号|采购编号|招标编号|采购人|。)|\Z)",
    r"项目名称[：:]\s*(.+?)(?=\n\s*(?:1\.\d|项目编号|采购编号|招标编号|采购人|。)|\Z)",
    r"工程名称[：:]\s*(.+?)(?=\n\s*(?:1\.\d|项目编号|采购编号|招标编号|。)|\Z)",
]
TENDERER_FIELD_PATTERNS = [
    r"招标人[：:]\s*(.+?)(?:\n|招标单位|采购人|采购单位|采购代理机构|招标代理机构|代理机构|联系人|地址|电话|采购编号|项目编号)",
    r"招标单位[：:]\s*(.+?)(?:\n|采购人|采购单位|采购代理机构|招标代理机构|代理机构|联系人|地址|电话|采购编号|项目编号)",
    r"采购人[：:]\s*(.+?)(?:\n|采购单位|采购代理机构|招标代理机构|代理机构|联系人|地址|电话|采购编号|项目编号)",
    r"采购单位[：:]\s*(.+?)(?:\n|采购代理机构|招标代理机构|代理机构|联系人|地址|电话|采购编号|项目编号)",
    r"比选人[：:]\s*(.+?)(?:\n|采购代理机构|招标代理机构|代理机构|联系人|地址|电话|采购编号|项目编号)",
    r"1\.2\s*采购人[：:]\s*(.+?)(?:\n|1\.3|采购代理机构|招标代理机构|代理机构)",
    r"采\s*购\s*人[：:]\s*(.+?)(?:\n|采购代理机构|招标代理机构|代理机构|联系人|地址|电话)",
]


def _clean_tenderer_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _normalize_space(value)
    cleaned = re.sub(r"[（(]盖(?:单位|公)?章[）)]", "", cleaned)
    cleaned = re.sub(r"[（(]公?章[）)]", "", cleaned)
    cleaned = re.sub(r"（盖公章）|\(盖公章\)|盖公章", "", cleaned).strip()
    for marker in TENDERER_STOP_MARKERS:
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0].strip()
    if not cleaned or len(cleaned) < 4 or len(cleaned) > 60:
        return None
    if any(token in cleaned for token in ("目录", "第一章", "响应文件", "投标文件")):
        return None
    return cleaned


def _clean_person_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _normalize_space(value)
    if len(cleaned) < 2 or len(cleaned) > 8:
        return None
    if any(token in cleaned for token in INVALID_PERSON_TOKENS):
        return None
    return cleaned


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_address_value(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = _normalize_space(value)
    cleaned = re.split(r"\s*(?:电子邮箱|E-mail|邮箱)[：:]", cleaned, maxsplit=1)[0].strip()
    cleaned = re.split(r"\s*邮编[：:]", cleaned, maxsplit=1)[0].strip()
    cleaned = re.split(r"\s*电\s*话[：:]", cleaned, maxsplit=1)[0].strip()
    cleaned = re.split(r"\s*供应商代表", cleaned, maxsplit=1)[0].strip()
    if len(cleaned) < 4:
        return None
    return cleaned


def _parse_money_amount(raw: str | None) -> str | None:
    if not raw:
        return None
    text = _normalize_space(raw)
    if any(token in text for token in ("不要求", "不采用", "无", "/")):
        return "0.00"
    match = re.search(r"([\d,，.]+)\s*万元", text)
    if match:
        amount = float(match.group(1).replace(",", "").replace("，", "")) * 10000
        return f"{amount:.2f}"
    match = re.search(r"([\d,，.]+)\s*元", text)
    if match:
        amount = float(match.group(1).replace(",", "").replace("，", ""))
        return f"{amount:.2f}"
    match = re.search(r"([\d,，.]+)", text)
    if match:
        amount = float(match.group(1).replace(",", "").replace("，", ""))
        return f"{amount:.2f}"
    return None


def _parse_chinese_datetime(raw: str | None) -> str | None:
    if not raw:
        return None
    text = _normalize_space(raw)
    match = re.search(
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日(?:\s*(\d{1,2})\s*(?:[：:时]\s*(\d{1,2})(?:\s*分)?|时))?",
        text,
    )
    if not match:
        return None
    year, month, day, hour, minute = match.groups()
    dt = datetime(int(year), int(month), int(day))
    if hour is not None:
        dt = dt.replace(hour=int(hour), minute=int(minute or 0))
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _infer_region_from_address(address: str | None) -> str | None:
    if not address:
        return None
    city_codes = {
        "太原": "140000,140100",
        "大同": "140000,140200",
        "阳泉": "140000,140300",
        "长治": "140000,140400",
        "晋城": "140000,140500",
        "朔州": "140000,140600",
        "晋中": "140000,140700",
        "运城": "140000,140800",
        "忻州": "140000,140900",
        "临汾": "140000,141000",
        "吕梁": "140000,141100",
    }
    for city, code in city_codes.items():
        if city in address:
            return code
    if "山西" in address:
        return "140000,140100"
    return None


def _clean_company_name_from_filename(stem: str) -> str | None:
    cleaned = stem.strip()
    cleaned = re.sub(r"^[（(]已签章[）)]", "", cleaned)
    cleaned = re.sub(r"-副本\d*$", "", cleaned)
    cleaned = re.sub(r"（.*?）|\(.*?\)", "", cleaned).strip()
    if not cleaned or len(cleaned) < 4:
        return None
    if any(keyword in cleaned for keyword in (*GENERIC_STEM_KEYWORDS, *SKIP_STEMS)):
        return None
    return cleaned


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        if match:
            value = _normalize_space(match.group(1))
            if value and value not in {"_", "_________________"}:
                return value
    return None


def _company_from_filename(path: Path) -> str | None:
    stem = path.stem.strip()
    if not stem:
        return None
    upper = stem.upper()
    if any(keyword in stem for keyword in SKIP_STEMS):
        return None
    if any(keyword in stem for keyword in GENERIC_STEM_KEYWORDS):
        return None
    if len(stem) > 40:
        return None
    return stem


def _read_pdf_text(path: Path, *, max_pages: int | None = 40) -> str:
    if PdfReader is None:
        raise SystemExit("pypdf is required for PDF extraction. Install with: pip install pypdf")

    reader = PdfReader(str(path))
    limit = len(reader.pages) if max_pages is None else min(max_pages, len(reader.pages))
    chunks: list[str] = []
    for index in range(limit):
        page_text = reader.pages[index].extract_text() or ""
        if page_text.strip():
            chunks.append(page_text)
    return "\n".join(chunks)


def _try_ocr_pdf_text(path: Path, *, max_pages: int = 3) -> str:
    try:
        import fitz  # type: ignore[import-untyped]
        import pytesseract  # type: ignore[import-untyped]
        from PIL import Image  # type: ignore[import-untyped]
    except ImportError:
        return ""

    try:
        doc = fitz.open(str(path))
        chunks: list[str] = []
        for index in range(min(max_pages, len(doc))):
            pixmap = doc[index].get_pixmap(matrix=fitz.Matrix(2, 2))
            image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            chunks.append(pytesseract.image_to_string(image, lang="chi_sim"))
        return "\n".join(chunks)
    except Exception:
        return ""


def _chinese_char_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def _is_valid_project_name(name: str) -> bool:
    cleaned = _normalize_space(name)
    if not cleaned or len(cleaned) < 8:
        return False
    if _chinese_char_count(cleaned) < 6:
        return False
    if any(token in cleaned for token in ("/", "i255", "\\")):
        return False
    return True


def _strip_project_suffix(name: str) -> str:
    cleaned = name.strip()
    for suffix in PROJECT_NAME_SUFFIXES:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
    return cleaned


def _clean_filename_stem(stem: str) -> str:
    cleaned = stem.strip()
    for prefix in FILENAME_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    cleaned = re.sub(r"[（(](?:二次|最终版|最终稿|\d+\.\d+)[）)]", "", cleaned)
    cleaned = re.sub(r"（最终版）|（最终稿）|\(最终版\)|\(最终稿\)", "", cleaned)
    for marker in FILENAME_DOCUMENT_MARKERS:
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0].strip()
    cleaned = re.sub(r"[（(]\d+\.\d+[）)]", "", cleaned).strip()
    return _strip_project_suffix(cleaned)


def _looks_like_document_filename(name: str) -> bool:
    cleaned = _normalize_space(name)
    if any(marker in cleaned for marker in FILENAME_DOCUMENT_MARKERS):
        return True
    if cleaned.startswith("采购公告"):
        return True
    if re.search(r"[（(]\d+\.\d+[）)]", cleaned):
        return True
    return False


def _project_name_from_announcement(text: str) -> str | None:
    patterns = [
        r"([\u4e00-\u9fff（）()、\-·\d]{6,}?)(?:谈判采购公告|谈判公告|询比公告|比选公告|采购公告|招标公告)",
        r"([\u4e00-\u9fff（）()、\-·\d]{6,}?)(?:谈判采购文件|询比采购文件|比选文件)",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            project = _strip_project_suffix(_normalize_space(match.group(1)))
            if any(token in project for token in ("目录", "第一章", "第二章", "第三章", "第四章", "第五章", "第六章")):
                continue
            if _is_valid_project_name(project):
                candidates.append(project)
    if not candidates:
        return None
    return max(candidates, key=len)


def _project_name_from_filename(path: Path) -> str | None:
    stem = path.stem.strip()
    if not stem:
        return None
    name = _clean_filename_stem(stem)
    if _is_valid_project_name(name):
        return name
    return None


def _project_name_from_cover(text: str) -> str | None:
    lines = [_normalize_space(line) for line in text.splitlines() if line.strip()]
    parts: list[str] = []
    for line in lines[:20]:
        compact = re.sub(r"\s+", "", line)
        if not compact or compact.startswith("."):
            continue
        if _chinese_char_count(compact) < 2:
            continue
        if any(keyword in compact for keyword in COVER_STOP_KEYWORDS):
            break
        if re.fullmatch(r"[\u4e00-\u9fff]+文件", compact):
            break
        parts.append(compact)

    if not parts:
        return None

    name = _strip_project_suffix("".join(parts))
    if _is_valid_project_name(name):
        return name
    return None


def _project_name_from_bidding_filename(path: Path) -> str | None:
    name = _clean_filename_stem(path.stem.strip())
    if name and _is_valid_project_name(name):
        return name
    return None


def _extract_bidding_text(path: Path, *, max_pages: int | None = 10) -> tuple[str, str | None]:
    try:
        text = _read_pdf_text(path, max_pages=max_pages)
    except Exception as exc:
        return "", str(exc)

    if text.strip():
        return text, None

    ocr_text = _try_ocr_pdf_text(path, max_pages=min(max_pages or 3, 3))
    if ocr_text.strip():
        return ocr_text, "ocr"
    return "", None


def extract_project_name(pdf_path: str | Path, *, max_pages: int | None = 10) -> dict[str, Any]:
    """Extract project name from a 招标文件 PDF only."""
    path = Path(pdf_path)
    result: dict[str, Any] = {"source_pdf": str(path)}

    text, text_source = _extract_bidding_text(path, max_pages=max_pages)
    if text_source:
        result["text_source"] = text_source
    if not text.strip():
        filename_name = _project_name_from_bidding_filename(path)
        if filename_name:
            result["project_name"] = filename_name
            result["source_field"] = "filename"
        return result

    project = _first_match(text, PROJECT_NAME_FIELD_PATTERNS)
    if project:
        project = _normalize_space(project)
        project = _strip_project_suffix(project)
        if _is_valid_project_name(project):
            result["project_name"] = project
            result["source_field"] = "项目名称"
            return result

    announcement_name = _project_name_from_announcement(text)
    if announcement_name:
        result["project_name"] = announcement_name
        result["source_field"] = "公告标题"
        return result

    cover_name = _project_name_from_cover(text)
    if cover_name and _is_valid_project_name(cover_name):
        result["project_name"] = cover_name
        result["source_field"] = "封面"
        return result

    filename_name = _project_name_from_bidding_filename(path)
    if filename_name:
        result["project_name"] = filename_name
        result["source_field"] = "filename"

    return result


def extract_tenderer_name(pdf_path: str | Path, *, max_pages: int | None = 10) -> dict[str, Any]:
    """Extract tenderer (招标人) from a 招标文件 PDF."""
    path = Path(pdf_path)
    result: dict[str, Any] = {"source_pdf": str(path)}

    text, text_source = _extract_bidding_text(path, max_pages=max_pages)
    if text_source:
        result["text_source"] = text_source
    if not text.strip():
        return result

    for pattern in TENDERER_FIELD_PATTERNS:
        match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        if not match:
            continue
        tenderer = _clean_tenderer_name(match.group(1))
        if tenderer:
            result["tenderer_name"] = tenderer
            field = pattern.split("[", 1)[0]
            result["source_field"] = field
            return result

    return result


def extract_project_name_from_pdfs(
    bidding_files: list[Path],
    tender_files: list[Path],
    *,
    folder_title: str | None = None,
    max_pages: int | None = 10,
) -> dict[str, Any]:
    """Resolve project name from 招标文件 when present; never fall back to 投标文件."""
    if bidding_files:
        for path in bidding_files:
            extracted = extract_project_name(path, max_pages=max_pages)
            project_name = extracted.get("project_name")
            if project_name and _is_valid_project_name(str(project_name)):
                return {
                    "project_name": project_name,
                    "source_pdf": extracted["source_pdf"],
                    "source_type": "bidding",
                    "source_field": extracted.get("source_field"),
                    "text_source": extracted.get("text_source"),
                }
        return {"project_name": None, "source_type": "bidding", "source_pdf": str(bidding_files[0])}

    for path in tender_files:
        extracted = extract_project_name(path, max_pages=max_pages)
        project_name = extracted.get("project_name")
        if project_name and _is_valid_project_name(str(project_name)):
            return {
                "project_name": project_name,
                "source_pdf": extracted["source_pdf"],
                "source_type": "tender",
                "source_field": extracted.get("source_field"),
            }

    if folder_title and _is_valid_project_name(folder_title):
        return {
            "project_name": folder_title.strip(),
            "source_type": "folder",
        }

    return {"project_name": None, "source_type": None}


def extract_tenderer_name_from_pdfs(
    bidding_files: list[Path],
    *,
    max_pages: int | None = 10,
) -> dict[str, Any]:
    """Resolve tenderer name from 招标文件 only."""
    for path in bidding_files:
        extracted = extract_tenderer_name(path, max_pages=max_pages)
        tenderer_name = extracted.get("tenderer_name")
        if tenderer_name:
            return {
                "tenderer_name": tenderer_name,
                "source_pdf": extracted["source_pdf"],
                "source_type": "bidding",
                "source_field": extracted.get("source_field"),
                "text_source": extracted.get("text_source"),
            }
    return {"tenderer_name": None, "source_type": None}


def extract_publish_fields(pdf_path: str | Path, *, max_pages: int | None = 20) -> dict[str, Any]:
    """Extract publish form fields from a 招标文件 PDF."""
    path = Path(pdf_path)
    result: dict[str, Any] = {"source_pdf": str(path)}

    text, text_source = _extract_bidding_text(path, max_pages=max_pages)
    if text_source:
        result["text_source"] = text_source
    if not text.strip():
        ocr_text = _try_ocr_pdf_text(path, max_pages=min(max_pages or 5, 5))
        if ocr_text.strip():
            text = ocr_text
            result["text_source"] = "ocr"
    if not text.strip():
        return result

    project_info = extract_project_name(path, max_pages=max_pages)
    if project_info.get("project_name"):
        result["title"] = project_info["project_name"]
        result["title_source_field"] = project_info.get("source_field")

    tenderer_info = extract_tenderer_name(path, max_pages=max_pages)
    if tenderer_info.get("tenderer_name"):
        result["username"] = tenderer_info["tenderer_name"]
        result["username_source_field"] = tenderer_info.get("source_field")

    project_no = _first_match(
        text,
        [
            r"1\.6\s*采购编号[：:]\s*(\S+)",
            r"项目编号[：:]\s*(\S+)",
            r"采购编号[：:]\s*(\S+)",
            r"招标编号[：:]\s*(\S+)",
        ],
    )
    if project_no:
        result["project_no"] = project_no.rstrip("。")

    address = _first_match(
        text,
        [
            r"采购单位[：:][\s\S]{0,120}?联系地址[：:]\s*(.+?)(?:\n|联系人|电话|邮编)",
            r"采购人[：:][\s\S]{0,120}?地\s*址[：:]\s*(.+?)(?:\n|联系人|电\s*话|邮编)",
            r"联\s*系\s*地\s*址[：:]\s*(.+?)(?:\n|联系人|电话|邮编)",
            r"联系地址[：:]\s*(.+?)(?:\n|联系人|电话|邮编)",
        ],
    )
    address = _clean_address_value(address)
    if address:
        result["address"] = address
        region = _infer_region_from_address(address)
        if region:
            result["region"] = region

    scope = _first_match(
        text,
        [
            r"2\.1\s*采购范围[：:]\s*(.+?)(?=\n\s*2\.2|\n\s*3\s)",
            r"2\.1\s*采购范围[：:]\s*(.+?)(?=\n)",
        ],
    )
    if scope:
        result["intro_text"] = _normalize_space(scope)

    file_price_raw = _first_match(
        text,
        [
            r"采购文件每套售价\s*(\d[\d,，.]*)\s*元",
            r"釆购文件每套售价\s*(\d[\d,，.]*)\s*元",
            r"询比文件售价每套人民币\s*(\d[\d,，.]*)\s*元",
            r"招标文件售价.*?(\d[\d,，.]*)\s*元",
            r"采购文件.*?售价.*?(\d[\d,，.]*)\s*元",
            r"文件费.*?(\d[\d,，.]*)\s*元",
        ],
    )
    file_price = _parse_money_amount(file_price_raw)
    if file_price:
        result["file_price"] = file_price

    deposit_section = _first_match(
        text,
        [
            r"3\.4\.1\s*响应保证金[\s\S]{0,300}?(?:投标保证金金额|保证金金额|保证金的金额)[：:]\s*([^\n]+)",
            r"(?:投标保证金金额|保证金金额|保证金的金额)[：:]\s*([^\n]+)",
        ],
    )
    if deposit_section and any(token in deposit_section for token in ("不要求", "不采用")):
        result["deposit"] = "0.00"
    else:
        deposit = _parse_money_amount(deposit_section)
        if deposit:
            result["deposit"] = deposit

    price_raw = _first_match(
        text,
        [
            r"最高限价[：:]\s*([\d,，.]+)\s*万元",
            r"最高控制价[：:]\s*([\d,，./]+)",
            r"3\.2\.5\s*预算金额\s*([\d,，.]+)\s*元",
            r"预算金额\s*([\d,，.]+)\s*元",
            r"3\.2\.3\s*最高限价或其计算方法[\s\S]{0,80}?有[，,]\s*([\d,，.]+)\s*元",
            r"最高限价[：:]\s*([\d,，.]+)\s*元",
        ],
    )
    if price_raw and price_raw.strip() not in {"/", "无"}:
        wan_match = re.search(r"最高限价[：:]\s*([\d,，.]+)\s*万元", text)
        if wan_match:
            amount = float(wan_match.group(1).replace(",", "").replace("，", "")) * 10000
            result["price"] = f"{amount:.2f}"
        else:
            price = _parse_money_amount(price_raw)
            if price and price != "0.00":
                result["price"] = price

    date_range = re.search(
        r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)\s*至\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)",
        text,
    )
    if date_range:
        start = _parse_chinese_datetime(date_range.group(1))
        end = _parse_chinese_datetime(date_range.group(2))
        if start:
            result["file_start_time"] = start
        if end:
            result["file_end_time"] = end.replace(" 00:00:00", " 23:59:59")

    bid_deadline_patterns = [
        r"4\.2\.1[\s\S]{0,200}?截止时间[：:]\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日[^\n]*)",
        r"截止时间[：:]\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*\d{1,2}\s*时)",
        r"响应文件递交的截止时间[为及：:]*\s*(\d{4}\s*年[^\n]+)",
        r"递交响应文件的截止时间[为及：:]*\s*(\d{4}\s*年[^\n]+)",
        r"响应文件递交的截止时间[为及：:]*\s*(.+?)(?:\n|，|,|地点)",
        r"递交响应文件的截止时间[为及：:]*\s*(.+?)(?:\n|，|,|地点)",
    ]
    bid_deadline_raw = None
    for pattern in bid_deadline_patterns:
        match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
        if not match:
            continue
        candidate = _normalize_space(match.group(1))
        if not candidate or "见采购文件" in candidate or candidate in {"。", "地点：见采购文件。"}:
            continue
        bid_deadline_raw = candidate
        break

    if bid_deadline_raw:
        start_time = _parse_chinese_datetime(bid_deadline_raw)
        if start_time:
            result["start_time"] = start_time

    return result


def extract_publish_fields_from_pdfs(
    bidding_files: list[Path],
    *,
    max_pages: int | None = 20,
) -> dict[str, Any]:
    """Resolve publish fields from 招标文件 only."""
    for path in bidding_files:
        extracted = extract_publish_fields(path, max_pages=max_pages)
        if extracted.get("title") or extracted.get("username") or extracted.get("project_no"):
            return {**extracted, "source_type": "bidding"}
    if bidding_files:
        return {"source_pdf": str(bidding_files[0]), "source_type": "bidding"}
    return {"source_type": None}


def publish_payload_from_extracted(
    extracted: dict[str, Any],
    *,
    base_publish: dict[str, Any] | None = None,
    fallback_title: str | None = None,
    skip_opening_time: bool = True,
) -> dict[str, Any]:
    """Map extracted 招标文件 fields to api/publicity/create config keys."""
    base = dict(base_publish or {})
    payload: dict[str, Any] = {}

    for key in (
        "title",
        "username",
        "address",
        "region",
        "project_no",
        "file_price",
        "platform_price",
        "deposit",
        "price",
        "file_start_time",
        "file_end_time",
        *(() if skip_opening_time else ("start_time",)),
    ):
        value = extracted.get(key)
        if value is not None and str(value).strip():
            payload[key] = value

    title = payload.get("title") or extracted.get("title") or fallback_title
    if title and not payload.get("title"):
        payload["title"] = title

    intro_text = extracted.get("intro_text") or title
    if intro_text:
        payload["intro"] = f"<p>{_normalize_space(str(intro_text))}</p>"

    for key in ("cate_id", "company_id", "pattern_id", "industry_id", "is_audit", "is_min", "is_bid_section"):
        if key in base:
            payload[key] = base[key]

    if not payload.get("platform_price"):
        payload["platform_price"] = base.get("platform_price") or payload.get("file_price") or "1.00"

    return payload


def extract_register_fields(pdf_path: str | Path, *, max_pages: int | None = 40) -> dict[str, Any]:
    path = Path(pdf_path)
    result: dict[str, Any] = {"source_pdf": str(path)}

    filename_company = _company_from_filename(path) or _clean_company_name_from_filename(path.stem)
    if filename_company:
        result.setdefault("company_name", filename_company)

    try:
        text = _read_pdf_text(path, max_pages=max_pages)
    except Exception as exc:
        result["extract_error"] = str(exc)
        return result

    if not text.strip():
        return result

    company = _first_match(
        text,
        [
            r"供应商全称[：:]\s*(.+?)(?:\s*[（(]盖单位章|$)",
            r"响应商全称[：:]\s*(.+?)(?:\s*[（(]盖单位章|$)",
            r"投标人[（(]单位[）)]?[：:]\s*(.+?)(?:\s|$)",
            r"投标人名称[：:]\s*(.+?)(?:\n|地址|邮编)",
            r"企业名称[：:]\s*(.+?)(?:\s|$)",
            r"单位名称[：:]\s*(.+?)(?:\n|地址|邮编)",
        ],
    )
    if company:
        company = re.sub(r"\s*[（(]盖(?:单位|公)?章[）)]?", "", company).strip()
        company = re.sub(r"[（(]盖.*$", "", company).strip()
        result["company_name"] = company

    address = _first_match(
        text,
        [
            r"注册地址[：:]\s*(.+?)(?:\n|邮编|电话|传真|邮政)",
            r"单位地址[：:]\s*(.+?)(?:\n|邮编|电话|传真|邮政)",
            r"有关本项目的进一步联系方式为[：:]\s*地址[：:]\s*(.+?)(?:\n|邮编|电话|传真|邮政)",
            r"地址[：:]\s*(.+?)(?:\n\s*邮编[：:]|邮编[：:]|电话[：:]|传真[：:]|邮政编码[：:])",
        ],
    )
    address = _clean_address_value(address)
    if address:
        result["company_address"] = address

    legal_person = _first_match(
        text,
        [
            r"供应商代表姓名[：:\s]*(\S{2,8})",
            r"法定代表人[：:]\s*(\S{2,8})(?:\s|身份证|性别|年龄|职务)",
            r"单位负责人[：:]\s*(\S{2,8})(?:\s|身份证|性别|年龄|职务)",
            r"姓\s*名[：:\s]*(\S{2,8}).{0,40}职\s*务[：:\s]*法定代表人",
        ],
    )
    legal_person = _clean_person_name(legal_person)
    if legal_person:
        result["legal_person"] = legal_person

    contact = _first_match(
        text,
        [
            r"联系方式\s*\n\s*联系人\s*(\S+)",
            r"联系人[：:]\s*(\S+)",
        ],
    )
    if contact:
        result["contact"] = contact

    contact_phone = _first_match(
        text,
        [
            r"联系方式[\s\S]{0,200}?电\s*话\s*(\d[\d\-]+)",
            r"联系人[\s\S]{0,80}?电\s*话\s*(\d[\d\-]+)",
            r"联系电话[：:]\s*(\d[\d\-]+)",
        ],
    )
    if contact_phone:
        result["contact_phone_doc"] = contact_phone

    email = _first_match(text, [r"E-mail[：:]\s*(\S+@\S+)", r"邮箱[：:]\s*(\S+@\S+)"])
    if email:
        result["email_doc"] = email

    return result


def register_payload_from_extracted(extracted: dict[str, Any]) -> dict[str, str]:
    payload: dict[str, str] = {}
    company_name = extracted.get("company_name")
    if company_name:
        payload["company_name"] = str(company_name)
    if extracted.get("company_address"):
        payload["company_address"] = str(extracted["company_address"])
    contact = extracted.get("contact")
    legal_person = extracted.get("legal_person")
    if contact and legal_person and contact == company_name:
        payload["contact"] = str(legal_person)
    elif contact:
        payload["contact"] = str(contact)
    elif legal_person:
        payload["contact"] = str(legal_person)
    if extracted.get("email_doc"):
        payload["email"] = str(extracted["email_doc"])
    return payload


def _is_generic_tender_path(path: Path, title: str) -> bool:
    stem = path.stem.strip()
    if not stem:
        return True
    if stem == title:
        return True
    return any(keyword in stem for keyword in GENERIC_STEM_KEYWORDS)


def _is_placeholder_contact(value: str | None) -> bool:
    if not value:
        return True
    if value.startswith("投标人"):
        return True
    return value in {"前端开发", "中言监理"}


def _bidder_hints(bidder_cfg: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    for key in ("name",):
        value = bidder_cfg.get(key)
        if value:
            hints.append(str(value))
    register = bidder_cfg.get("register") or {}
    for key in ("company_name", "contact"):
        value = register.get(key)
        if value and "投标人" not in str(value) and "example.com" not in str(value):
            hints.append(str(value))
    return hints


def _score_file_for_bidder(path: Path, hints: list[str], title: str) -> int:
    stem = path.stem
    if stem == title or any(keyword in stem for keyword in GENERIC_STEM_KEYWORDS):
        base_score = 0
    elif any(keyword in stem for keyword in SKIP_STEMS):
        base_score = 0
    else:
        base_score = 10

    score = base_score
    for hint in hints:
        hint = hint.strip()
        if not hint:
            continue
        if hint in stem:
            score += 100
        elif len(hint) >= 4 and hint[:4] in stem:
            score += 60
        elif len(hint) >= 2 and hint[:2] in stem:
            score += 20
    return score


def match_bidder_tender_files(
    bidders: list[dict[str, Any]],
    tender_files: list[Path],
    *,
    title: str,
) -> dict[int, Path]:
    """Assign one tender PDF per bidder, preferring filename and config hints."""
    assignments: dict[int, Path] = {}
    assigned_files: set[str] = set()

    scored_pairs: list[tuple[int, int, Path]] = []
    for bidder_index, bidder_cfg in enumerate(bidders):
        submit_files = (bidder_cfg.get("submit") or {}).get("upload_files") or []
        if submit_files:
            candidate = Path(str(submit_files[0]))
            if candidate.exists() and not _is_generic_tender_path(candidate, title):
                assignments[bidder_index] = candidate
                assigned_files.add(str(candidate))
                continue

        hints = _bidder_hints(bidder_cfg)
        for path in tender_files:
            score = _score_file_for_bidder(path, hints, title)
            scored_pairs.append((score, bidder_index, path))

    for score, bidder_index, path in sorted(scored_pairs, key=lambda item: item[0], reverse=True):
        if bidder_index in assignments:
            continue
        path_key = str(path)
        if path_key in assigned_files:
            continue
        if score <= 0:
            continue
        assignments[bidder_index] = path
        assigned_files.add(path_key)

    for bidder_index, bidder_cfg in enumerate(bidders):
        if bidder_index in assignments:
            continue
        for path in tender_files:
            path_key = str(path)
            if path_key not in assigned_files:
                assignments[bidder_index] = path
                assigned_files.add(path_key)
                break

    return assignments


def match_bidder_tender_file(
    bidder_cfg: dict[str, Any],
    tender_files: list[Path],
    *,
    title: str,
    assigned: set[str],
) -> Path | None:
    hints = _bidder_hints(bidder_cfg)
    ranked = sorted(
        ((path, _score_file_for_bidder(path, hints, title)) for path in tender_files if str(path) not in assigned),
        key=lambda item: item[1],
        reverse=True,
    )
    if ranked and ranked[0][1] > 0:
        return ranked[0][0]

    for path in tender_files:
        if str(path) not in assigned:
            return path
    return None

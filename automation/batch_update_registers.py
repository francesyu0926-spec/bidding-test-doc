"""Batch-update register company info from bid PDFs for project 2058."""
from __future__ import annotations

import json
from pathlib import Path

from bid_pdf_extract import extract_register_fields, register_payload_from_extracted
from zjgj_client import ZjgjClient

BASE_URL = "https://www.bidding.shanxiguandian.com"
PM_TOKEN = "41ecfede938eb984fe6cfe94c185688f"
PROJECT_ID = 2058
SECTION_ID = 1888

UPDATES = [
    {
        "register_id": 7742,
        "token": "7e8a8eb2eb79d2e50dc62765c4bef368",
        "contact_phone": "13246829826",
        "pdf": r"d:\文件\客户项目文件\忻州长城博物馆(园)室外展陈及相关配套工程总承包(EPC)项目工程监理\投标文件\中言监理有限公司.pdf",
    },
    {
        "register_id": 7743,
        "token": "e016124f0ee365edbe1440d91f9857e3",
        "contact_phone": "13825110210",
        "pdf": r"d:\文件\客户项目文件\忻州长城博物馆(园)室外展陈及相关配套工程总承包(EPC)项目工程监理\投标文件\忻州长城博物馆(园)室外展陈及相关配套工程总承包(EPC)项目工程监理投标文件.pdf",
    },
    {
        "register_id": 7744,
        "token": "6a717729bb9d4e75677db82ba7aae838",
        "contact_phone": "13266312331",
        "pdf": r"d:\文件\客户项目文件\忻州长城博物馆(园)室外展陈及相关配套工程总承包(EPC)项目工程监理\投标文件\新建 DOCX 文档.pdf",
    },
]

FIELDS = ("company_name", "company_address", "contact", "contact_phone", "email")


def snapshot(client: ZjgjClient, register_id: int) -> dict[str, str | None]:
    data = (client.get_register_info(register_id).get("data") or {})
    return {field: data.get(field) for field in FIELDS}


def main() -> None:
    pm = ZjgjClient(BASE_URL, token=PM_TOKEN, verify_ssl=False)
    results: list[dict] = []

    for item in UPDATES:
        register_id = item["register_id"]
        client = ZjgjClient(BASE_URL, token=item["token"], verify_ssl=False)
        before = snapshot(client, register_id)

        extracted = extract_register_fields(item["pdf"])
        pdf_fields = register_payload_from_extracted(extracted)
        current = (client.get_register_info(register_id).get("data") or {})

        payload = {
            "project_id": PROJECT_ID,
            "section_id": SECTION_ID,
            "company_name": pdf_fields.get("company_name") or current.get("company_name"),
            "company_address": pdf_fields.get("company_address") or current.get("company_address"),
            "contact": pdf_fields.get("contact") or current.get("contact"),
            "contact_phone": item["contact_phone"],
            "email": pdf_fields.get("email") or current.get("email"),
            "images": current.get("images"),
        }

        try:
            resp = client.update_register(register_id, payload)
            status = "ok"
            error = None
        except Exception as exc:
            resp = None
            status = "failed"
            error = str(exc)

        after = snapshot(client, register_id)
        results.append(
            {
                "register_id": register_id,
                "pdf": Path(item["pdf"]).name,
                "extracted": extracted,
                "payload_sent": payload,
                "before": before,
                "after": after,
                "status": status,
                "error": error,
                "response": resp,
            }
        )

    pm_list = pm.list_project_registers(PROJECT_ID).get("data", {}).get("list", [])
    print(json.dumps({"endpoint": "POST api/project_register/register (with id)", "results": results, "pm_list": pm_list}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

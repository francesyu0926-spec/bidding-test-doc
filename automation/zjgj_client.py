"""ZJGJ bidding platform API client for three-stage flow automation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests


ReviewCategory = dict[str, Any]
ReviewItem = dict[str, Any]

# Minimal 1x1 PNG for api/tender/signature (bidder 签字解密 step after password).
DEFAULT_TENDER_SIGNATURE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

# Review type codes used by api/publicity/saveReview:
# 1=technical, 2=business, 3=quote (price scoring).
DEFAULT_REVIEW_CATEGORIES: list[ReviewCategory] = [
    {
        "type": 1,
        "title": "技术评分",
        "score": 60,
        "factor": 60,
        "standard": "对投标人技术方案、实施能力等进行综合评价",
        "items": [
            {
                "title": "技术方案",
                "factor": 30,
                "score": 30,
                "standard": "方案完整可行，满足采购需求",
            },
            {
                "title": "实施计划",
                "factor": 30,
                "score": 30,
                "standard": "实施计划合理，保障措施到位",
            },
        ],
    },
    {
        "type": 2,
        "title": "商务评分",
        "score": 10,
        "factor": 10,
        "standard": "对投标人商务响应情况进行评价",
        "items": [
            {
                "title": "商务响应",
                "factor": 10,
                "score": 10,
                "standard": "响应招标文件商务条款要求",
            },
        ],
    },
    {
        "type": 3,
        "title": "报价评分",
        "score": 30,
        "factor": 30,
        "standard": "按报价评分方法一（去掉n个最高和最低后取平均）计算",
        "price_method": 1,
        "price_n": 5,
        "items": [],
    },
]


def build_review_form_data(
    project_id: int,
    section_id: int,
    categories: list[ReviewCategory],
    *,
    cate_id: int = 1,
    pattern_id: int = 1,
) -> list[tuple[str, str]]:
    """Build nested form fields for api/publicity/saveReview.

    The API expects PHP-style nested form keys (review_data[0][title]=...),
    not a JSON body. Each category and sub-item needs ``standard``; quote
    categories (type=3) also accept ``price_method`` and ``price_n``.
    """
    form: list[tuple[str, str]] = [("project_id", str(project_id))]
    for category_index, category in enumerate(categories):
        prefix = f"review_data[{category_index}]"
        base_fields = {
            "publicity_id": str(project_id),
            "section_id": str(section_id),
            "cate_id": str(cate_id),
            "pattern_id": str(pattern_id),
            "type": str(category["type"]),
            "title": str(category["title"]),
            "score": str(category["score"]),
            "factor": str(category.get("factor", category["score"])),
            "standard": str(category["standard"]),
        }
        for key, value in base_fields.items():
            form.append((f"{prefix}[{key}]", value))
        for optional in ("price_method", "price_n", "price_type"):
            if optional in category and category[optional] is not None:
                form.append((f"{prefix}[{optional}]", str(category[optional])))
        for item_index, item in enumerate(category.get("items") or []):
            for key, value in item.items():
                form.append((f"{prefix}[items][{item_index}][{key}]", str(value)))
    return form


def review_categories_total(categories: list[ReviewCategory]) -> int:
    return sum(int(category["score"]) for category in categories)


class ZjgjApiError(Exception):
    def __init__(self, code: int, message: str, payload: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.payload = payload


@dataclass
class ZjgjClient:
    base_url: str
    token: str | None = None
    timeout: int = 30
    verify_ssl: bool = True

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/") + "/"
        self.session = requests.Session()
        if not self.verify_ssl:
            self.session.verify = False
            try:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Token"] = self.token
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | list[tuple[str, str]] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        require_auth: bool = False,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        if require_auth and not self.token:
            raise ZjgjApiError(-1, "Token is required for this endpoint")

        url = urljoin(self.base_url, path.lstrip("/"))
        response = self.session.request(
            method=method.upper(),
            url=url,
            params=params,
            data=data,
            json=json_body,
            files=files,
            headers=self._headers(),
            timeout=timeout or self.timeout,
        )
        response.raise_for_status()

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ZjgjApiError(-1, f"Non-JSON response from {path}: {response.text[:200]}") from exc

        code = payload.get("code")
        if code not in (1, "1", 200, "200"):
            raise ZjgjApiError(code if code is not None else -1, payload.get("msg", "unknown error"), payload)

        return payload

    # --- public / health ---

    def health_check(self) -> dict[str, Any]:
        return self.request("GET", "api/index/index")

    def list_public_projects(self, page: int = 1, limit: int = 10) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/publicity/getList",
            params={"page": page, "limit": limit},
        )

    def get_public_project(self, project_id: int) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/publicity/info",
            params={"project_id": project_id},
        )

    def get_user_profile(self) -> dict[str, Any]:
        return self.request("GET", "api/user/index", require_auth=True)

    # --- stage 1: publish ---

    def get_publicity_cate(self) -> dict[str, Any]:
        return self.request("GET", "api/publicity/cate", require_auth=True)

    def get_publicity_pattern(self) -> dict[str, Any]:
        return self.request("GET", "api/publicity/pattern", require_auth=True)

    def get_publicity_company(self) -> dict[str, Any]:
        return self.request("GET", "api/publicity/company", require_auth=True)

    def get_publicity_project_info(self, project_id: int) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/publicity/projectInfo",
            params={"project_id": project_id},
            require_auth=True,
        )

    def create_publicity_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "api/publicity/create", data=payload, require_auth=True)

    def publish_change_project(self, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """发布变更 — admin UI route /project/change/:id submits here with id set."""
        data = {"id": project_id, **payload}
        return self.create_publicity_project(data)

    def update_publicity_project(self, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Alias for publish_change_project."""
        return self.publish_change_project(project_id, payload)

    def save_publicity_review(self, payload: dict[str, Any] | list[tuple[str, str]]) -> dict[str, Any]:
        return self.request("POST", "api/publicity/saveReview", data=payload, require_auth=True)

    def save_review_config(
        self,
        project_id: int,
        section_id: int,
        categories: list[ReviewCategory] | None = None,
        *,
        cate_id: int = 1,
        pattern_id: int = 1,
    ) -> dict[str, Any]:
        """Save review/scoring table config (评审表格) for a project section."""
        review_categories = categories or DEFAULT_REVIEW_CATEGORIES
        form_data = build_review_form_data(
            project_id,
            section_id,
            review_categories,
            cate_id=cate_id,
            pattern_id=pattern_id,
        )
        return self.save_publicity_review(form_data)

    def audit_register(self, register_id: int, status: int) -> dict[str, Any]:
        return self.request(
            "POST",
            "api/publicity/registerAudit",
            data={"register_id": register_id, "status": status},
            require_auth=True,
        )

    # --- stage 2: register & pay ---

    def check_register(self, project_id: int, section_id: int) -> dict[str, Any]:
        return self.request(
            "POST",
            "api/project_register/check",
            data={"project_id": project_id, "section_id": section_id},
            require_auth=True,
        )

    def register_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "api/project_register/register", data=payload, require_auth=True)

    def get_register_info(self, register_id: int) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/project_register/info",
            params={"id": register_id},
            require_auth=True,
        )

    def list_project_registers(self, project_id: int, *, page: int = 1, limit: int = 50) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/publicity/registerList",
            params={"project_id": project_id, "page": page, "limit": limit},
            require_auth=True,
        )

    def update_register(self, register_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Update an existing registration via POST api/project_register/register with id."""
        data = {"id": register_id, **payload}
        return self.request("POST", "api/project_register/register", data=data, require_auth=True)

    def pay_register(self, payload: dict[str, Any], *, use_v3: bool = True) -> dict[str, Any]:
        path = "api/project_register/paymentNew" if use_v3 else "api/project_register/payment"
        return self.request("POST", path, data=payload, require_auth=True)

    def admin_mock_payment(self, register_id: int) -> dict[str, Any]:
        """Admin-side simulated payment via paymentErrorHandler (GET only)."""
        return self.request(
            "GET",
            "api/project_register/paymentErrorHandler",
            params={"registerId": register_id},
            require_auth=True,
        )

    def mock_register_payment(self, register_id: int) -> dict[str, Any]:
        """Alias for admin_mock_payment."""
        return self.admin_mock_payment(register_id)

    # --- stage 3: submit tender file ---

    def list_my_tenders(self, page: int = 1, limit: int = 20, status: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if status is not None:
            params["status"] = status
        return self.request("GET", "api/tender/myList", params=params, require_auth=True)

    def get_tender_project(self, tender_id: int, section_id: int) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/tender/getProject",
            params={"tender_id": tender_id, "section_id": section_id},
            require_auth=True,
        )

    def upload_image(self, file_path: str, *, timeout: int | None = None) -> dict[str, Any]:
        with open(file_path, "rb") as handle:
            return self.request(
                "POST",
                "api/uploads/uploadImage",
                files={"file": handle},
                timeout=timeout or max(self.timeout, 180),
            )

    def submit_tender_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "api/tender/submitFile", data=payload, require_auth=True)

    def get_tender_file(self, tender_id: int, section_id: int) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/tender/getTenderFile",
            params={"tender_id": tender_id, "section_id": section_id},
            require_auth=True,
        )

    # --- expert ---

    def get_expert_profile(self) -> dict[str, Any]:
        return self.request("GET", "api/expert/info", require_auth=True)

    def list_expert_projects(self, page: int = 1, limit: int = 20, status: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if status is not None:
            params["status"] = status
        return self.request("GET", "api/expert/myList", params=params, require_auth=True)

    def list_expert_invites(self, page: int = 1, limit: int = 20, status: int = 0) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/expert/list",
            params={"page": page, "limit": limit, "status": status},
            require_auth=True,
        )

    def get_user_notifications(self, notify_type: int = 2, page: int = 1, limit: int = 20) -> dict[str, Any]:
        return self.request(
            "GET",
            f"api/user/notify/{notify_type}",
            params={"page": page, "limit": limit},
            require_auth=True,
        )

    def get_manage_invite_info(self, project_id: int, section_id: int) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/manage/inviteInfo",
            params={"project_id": project_id, "section_id": section_id},
            require_auth=True,
        )

    def add_expert_to_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "api/manage/addExpert", data=payload, require_auth=True)

    def audit_expert_invites(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Re-invite via addExpert (check/is_check ignored by backend).

        ZJGJ has no separate PM 通过审核 API. Re-calling addExpert destroys and
        recreates invite_expert rows; avoid in normal automation flows.
        """
        return self.add_expert_to_project(payload)

    def confirm_expert_invite(self, invite_id: int, status: int = 2) -> dict[str, Any]:
        """Expert agrees (status=2) or rejects (status=3) an invitation."""
        return self.request(
            "POST",
            "api/expert/confirm",
            data={"invite_id": invite_id, "status": status},
            require_auth=True,
        )

    def expert_sign_in(self, project_id: int, section_id: int, invite_id: int) -> dict[str, Any]:
        return self.request(
            "POST",
            "api/expert/sign",
            data={"project_id": project_id, "section_id": section_id, "invite_id": invite_id},
            require_auth=True,
        )

    # --- bid opening / evaluation ---

    def list_manage_projects(self, page: int = 1, limit: int = 20, status: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if status is not None:
            params["status"] = status
        return self.request("GET", "api/manage/myList", params=params, require_auth=True)

    def list_manage_tenders(
        self,
        project_id: int,
        section_id: int,
        *,
        page: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/manage/getList",
            params={"project_id": project_id, "section_id": section_id, "page": page, "limit": limit},
            require_auth=True,
        )

    def get_manage_progress(self, project_id: int, section_id: int) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/manage/getProgress",
            params={"project_id": project_id, "section_id": section_id},
            require_auth=True,
        )

    def get_manage_report(self, project_id: int, section_id: int) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/manage/getReport",
            params={"project_id": project_id, "section_id": section_id},
            require_auth=True,
        )

    def get_manage_candidates(self, project_id: int, section_id: int) -> dict[str, Any]:
        return self.request(
            "GET",
            "api/manage/getCandidate",
            params={"project_id": project_id, "section_id": section_id},
            require_auth=True,
        )

    def decrypt_tender_password(
        self,
        project_id: int,
        tender_id: int,
        section_id: int,
        password: str,
    ) -> dict[str, Any]:
        """Validate bidder decrypt password (step 1 of 签字解密)."""
        return self.request(
            "POST",
            "api/tender/password",
            data={
                "project_id": project_id,
                "tender_id": tender_id,
                "section_id": section_id,
                "password": password,
            },
            require_auth=True,
        )

    def submit_tender_signature(
        self,
        file_id: int,
        signature: str | None = None,
    ) -> dict[str, Any]:
        """Upload bidder signature image (step 2 of 签字解密; sets tender_project_files.sign)."""
        return self.request(
            "POST",
            "api/tender/signature",
            data={
                "id": file_id,
                "signature": signature or DEFAULT_TENDER_SIGNATURE,
            },
            require_auth=True,
        )

    def decrypt_and_sign_tender(
        self,
        project_id: int,
        tender_id: int,
        section_id: int,
        password: str,
        *,
        signature: str | None = None,
    ) -> dict[str, Any]:
        """Full bidder 签字解密: password validation then signature upload."""
        password_resp = self.decrypt_tender_password(project_id, tender_id, section_id, password)
        file_info = self.get_tender_file(tender_id, section_id).get("data") or {}
        file_id = file_info.get("id")
        if file_id is None:
            raise ZjgjApiError(-1, "tender file id not found after password decrypt")

        signature_resp: dict[str, Any] | None = None
        if not file_info.get("sign"):
            signature_resp = self.submit_tender_signature(int(file_id), signature)
            file_info = self.get_tender_file(tender_id, section_id).get("data") or {}

        return {
            "password": password_resp,
            "signature": signature_resp,
            "file_id": file_id,
            "sign": file_info.get("sign"),
        }

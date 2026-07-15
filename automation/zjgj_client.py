"""ZJGJ bidding platform API client for three-stage flow automation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests


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

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/") + "/"
        self.session = requests.Session()

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
        data: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        require_auth: bool = False,
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
            timeout=self.timeout,
        )
        response.raise_for_status()

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise ZjgjApiError(-1, f"Non-JSON response from {path}: {response.text[:200]}") from exc

        code = payload.get("code")
        if code not in (1, "1"):
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

    def create_publicity_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "api/publicity/create", data=payload, require_auth=True)

    def save_publicity_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "api/publicity/saveReview", data=payload, require_auth=True)

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

    def pay_register(self, payload: dict[str, Any], *, use_v3: bool = True) -> dict[str, Any]:
        path = "api/project_register/paymentNew" if use_v3 else "api/project_register/payment"
        return self.request("POST", path, data=payload, require_auth=True)

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

    def upload_image(self, file_path: str) -> dict[str, Any]:
        with open(file_path, "rb") as handle:
            return self.request(
                "POST",
                "api/uploads/uploadImage",
                files={"file": handle},
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

    def add_expert_to_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "api/manage/addExpert", data=payload, require_auth=True)

    def confirm_expert_invite(self, invite_id: int, status: int = 1) -> dict[str, Any]:
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

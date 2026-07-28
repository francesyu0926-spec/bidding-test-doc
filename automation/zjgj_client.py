"""ZJGJ bidding platform API client for three-stage flow automation."""

from __future__ import annotations

import json
import os
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


def _flow_max_score(flow: dict[str, Any]) -> int:
    """Max points for one scoring criterion (PublicityFlow.score, not factor title)."""
    for key in ("score", "factor"):
        raw = flow.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            value = int(float(raw))
            if value > 0:
                return value
        except (TypeError, ValueError):
            continue
    return 0


def _clamp_score(value: float, max_score: int, min_score: int = 0) -> int:
    """Clamp numeric score to [min_score, max_score] and return int."""
    if max_score > 0:
        value = min(value, max_score)
    return max(min_score, int(round(value)))


def _varied_criterion_score(max_score: int, item_index: int, bidder_index: int = 0) -> int:
    """Varied 商务/技术 score: 70%-100% of max by item index, small bidder offset.

    Cycles 70/80/90/100% across criteria (item_index % 4) and adds up to 10% by bidder
    so different bidders on the same criterion do not receive identical marks.
    """
    if max_score <= 0:
        return 0
    ratio = 0.7 + 0.1 * (item_index % 4) + 0.05 * (bidder_index % 3)
    ratio = min(ratio, 1.0)
    return _clamp_score(max_score * ratio, max_score)


def _varied_price_score(max_score: int, bidder_index: int) -> int:
    """Varied 报价 score per bidder: spread 85%-100% of max across bidders."""
    if max_score <= 0:
        return 0
    ratio = 0.85 + 0.075 * (bidder_index % 3)
    return _clamp_score(max_score * ratio, max_score)


def build_expert_scoring_items(
    review_list_data: Any,
    *,
    review_type: int,
    score_strategy: str = "full",
    uniform_score: int | None = None,
) -> list[dict[str, Any]]:
    """Build per-row scoring payload for ``saveOpinion`` / ``saveReview``.

    ``review_type`` 4=商务, 5=技术 (PublicityFlow.type). ``score_strategy``:
    ``full`` = max per criterion; ``uniform`` = same fixed score everywhere;
    ``varied`` = deterministic spread by item/bidder index within max bounds.
    """
    if not isinstance(review_list_data, dict):
        return []
    companies = review_list_data.get("company") or []
    flows = review_list_data.get("flow") or []
    flows = [f for f in flows if int(f.get("type") or 0) == review_type]
    if not companies or not flows:
        return []

    items: list[dict[str, Any]] = []
    for bidder_index, company in enumerate(companies):
        apply_id = company.get("apply_id") or company.get("id")
        if apply_id is None:
            continue
        for item_index, flow in enumerate(flows):
            flow_id = flow.get("id") or flow.get("project_flow_id")
            if flow_id is None:
                continue
            max_score = _flow_max_score(flow)
            if score_strategy == "uniform" and uniform_score is not None:
                score = min(uniform_score, max_score) if max_score else uniform_score
            elif score_strategy == "varied":
                score = _varied_criterion_score(max_score, item_index, bidder_index)
            else:
                score = max_score
            items.append(
                {
                    "type": review_type,
                    "apply_id": int(apply_id),
                    "project_flow_id": int(flow_id),
                    "score": score,
                    "status": 0,
                }
            )
    return items


def build_expert_price_score_items(
    review_list_data: Any,
    *,
    apply_ids: list[int] | None = None,
    default_score: int = 30,
    score_strategy: str = "varied",
) -> list[dict[str, Any]]:
    """Build type=6 rows for flow_type=9 (报价得分).

    Production ``TenderFlow::saveReview`` omits ``project_flow_id`` from the
    lookup for flow_type 9/10; include it when present in reviewList flows.
    ``score_strategy`` ``varied`` spreads 85%-100% of max across bidders.
    """
    if not isinstance(review_list_data, dict):
        return []
    companies = review_list_data.get("company") or []
    flows = [f for f in (review_list_data.get("flow") or []) if int(f.get("type") or 0) == 6]
    flow_id = None
    max_score = default_score
    if flows:
        flow_id = flows[0].get("id") or flows[0].get("project_flow_id")
        max_score = _flow_max_score(flows[0]) or default_score

    allowed = set(apply_ids or [])
    items: list[dict[str, Any]] = []
    for bidder_index, company in enumerate(companies):
        apply_id = company.get("apply_id") or company.get("id")
        if apply_id is None:
            continue
        if allowed and int(apply_id) not in allowed:
            continue
        if score_strategy == "uniform":
            score = max_score
        elif score_strategy == "varied":
            score = _varied_price_score(max_score, bidder_index)
        else:
            score = max_score
        entry: dict[str, Any] = {
            "type": 6,
            "apply_id": int(apply_id),
            "score": score,
            "status": 0,
        }
        if flow_id is not None:
            entry["project_flow_id"] = int(flow_id)
        items.append(entry)
    return items


def build_expert_review_items(
    review_list_data: Any,
    *,
    pass_status: int = 2,
    review_type: int = 1,
    default_score: int = 0,
    pass_fail_only: bool = True,
) -> list[dict[str, Any]]:
    """Build per-row review payload for ``saveOpinion`` / ``saveReview``.

    Production (``origin/dev``) stores one ``tender_flow`` row per expert uid.
    Pass/fail preliminary rows use ``status=2`` (通过).
    """
    if isinstance(review_list_data, dict) and review_list_data.get("company") and review_list_data.get("flow"):
        companies = review_list_data.get("company") or []
        flows = review_list_data.get("flow") or []
        if pass_fail_only:
            flows = [f for f in flows if float(f.get("score") or 0) == 0.0] or flows
        flows = [f for f in flows if int(f.get("type") or review_type) == review_type] or flows
        items: list[dict[str, Any]] = []
        for company in companies:
            apply_id = company.get("apply_id") or company.get("id")
            if apply_id is None:
                continue
            for flow in flows:
                flow_id = flow.get("id") or flow.get("project_flow_id")
                if flow_id is None:
                    continue
                items.append(
                    {
                        "type": review_type,
                        "apply_id": int(apply_id),
                        "project_flow_id": int(flow_id),
                        "status": pass_status,
                        "score": default_score,
                    }
                )
        return items

    items: list[dict[str, Any]] = []
    rows = review_list_data
    if isinstance(rows, dict):
        rows = rows.get("list") or rows.get("data") or rows.get("apply") or rows.get("apply_list") or []
    if not isinstance(rows, list):
        return []
    for row in rows:
        if not isinstance(row, dict):
            continue
        apply_id = row.get("apply_id") or row.get("id") or row.get("register_id")
        if apply_id is None:
            continue
        entry: dict[str, Any] = {
            "type": review_type,
            "apply_id": int(apply_id),
            "status": pass_status,
            "score": default_score,
        }
        flow_id = row.get("project_flow_id") or row.get("flow_id")
        if flow_id is not None:
            entry["project_flow_id"] = int(flow_id)
        items.append(entry)
    return items


def build_expert_review_data(
    review_list_data: Any,
    *,
    pass_status: int = 2,
    review_type: int = 1,
    default_score: int = 0,
    pass_fail_only: bool = True,
) -> str:
    """Build JSON ``data`` field (legacy) — prefer nested form via :func:`expert_review_items_to_form`."""
    items = build_expert_review_items(
        review_list_data,
        pass_status=pass_status,
        review_type=review_type,
        default_score=default_score,
        pass_fail_only=pass_fail_only,
    )
    return json.dumps(items, ensure_ascii=False)


def expert_review_items_to_form(
    project_id: int,
    section_id: int,
    flow_type: int,
    items: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """PHP-style nested form body for expert ``saveOpinion`` / ``saveReview``."""
    form: list[tuple[str, str]] = [
        ("project_id", str(project_id)),
        ("section_id", str(section_id)),
        ("flow_type", str(flow_type)),
    ]
    for index, item in enumerate(items):
        for key, value in item.items():
            form.append((f"data[{index}][{key}]", str(value)))
    return form


# flow_type (progress step) -> reviewList type (PublicityFlow.type / tender_flow.type)
PRELIMINARY_REVIEW_STEPS: list[tuple[int, int, str]] = [
    (3, 1, "形式评审"),
    (4, 2, "资格评审"),
    (5, 3, "响应性评审"),
]

# Scoring: getProgress step id -> reviewList type (Manage.php case 7/8/9)
SCORING_REVIEW_STEPS: list[tuple[int, int, str]] = [
    (7, 4, "商务评分"),  # tender_flow.type=4, summed into TenderBusinessStat
    (8, 5, "技术评分"),  # tender_flow.type=5, per-expert TenderScienceStat
    (9, 6, "报价得分"),  # tender_flow.type=6, may aggregate via flow_type=9
]


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

    def upload_image(self, file_path: str, *, timeout: int | None = None, max_attempts: int = 5) -> dict[str, Any]:
        import time

        last_error: Exception | None = None
        upload_timeout = timeout or max(self.timeout, 180)
        for attempt in range(1, max_attempts + 1):
            try:
                with open(file_path, "rb") as handle:
                    return self.request(
                        "POST",
                        "api/uploads/uploadImage",
                        files={"file": handle},
                        timeout=upload_timeout,
                    )
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
                last_error = exc
                if attempt >= max_attempts:
                    raise
                time.sleep(min(2 * attempt, 10))
        raise last_error or ZjgjApiError(-1, f"upload failed for {file_path}")

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

    def vote_expert_leader(self, project_id: int, section_id: int, sign_id: int) -> dict[str, Any]:
        """Cast one 推选组长 vote for an ``expert_sign`` row (GET api/expert/leaderVote).

        Production API only (not present in local ``zjgj230214_2JGT3`` PHP snapshot).
        Each signed expert may vote once per section; pick ``sign_id`` from
        :meth:`discover_leader_candidate_sign_ids`.
        """
        return self.request(
            "GET",
            "api/expert/leaderVote",
            params={"project_id": project_id, "section_id": section_id, "sign_id": sign_id},
            require_auth=True,
        )


    def discover_leader_candidate_sign_ids(
        self,
        project_id: int,
        section_id: int,
        *,
        start: int = 70,
        end: int = 160,
    ) -> list[int]:
        """Return contiguous ``expert_sign.id`` values that are valid leader-vote targets.

        Uses GET ``api/expert/leaderVote`` error text to detect the candidate block.
        Side effect: this caller's first successful probe casts their vote (``投票成功``).
        """
        candidates: list[int] = []
        for sign_id in range(start, end + 1):
            try:
                resp = self.vote_expert_leader(project_id, section_id, sign_id)
                msg = str(resp.get("msg", ""))
            except ZjgjApiError as exc:
                msg = str(exc)
            if "不存在" in msg and "重复" not in msg:
                if candidates:
                    break
                continue
            candidates.append(sign_id)
        return candidates

    def elect_expert_leader(self, project_id: int, section_id: int, sign_id: int) -> dict[str, Any]:
        """Alias for :meth:`vote_expert_leader`."""
        return self.vote_expert_leader(project_id, section_id, sign_id)

    def get_expert_review_list(
        self,
        project_id: int,
        section_id: int,
        review_type: int = 1,
    ) -> dict[str, Any]:
        """GET ``api/expert/reviewList`` — bidder rows for one review step."""
        return self.request(
            "GET",
            "api/expert/reviewList",
            params={"project_id": project_id, "section_id": section_id, "type": review_type},
            require_auth=True,
        )

    def save_expert_opinion(
        self,
        project_id: int,
        section_id: int,
        flow_type: int,
        data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """POST ``api/expert/saveOpinion`` — per-expert draft/submit (no sync gate).

        On production, experts 1..N-1 call this; the last expert calls
        :meth:`save_expert_review` which runs ``ExpertSign::checkSignAndScore``.
        """
        return self.request(
            "POST",
            "api/expert/saveOpinion",
            data=expert_review_items_to_form(project_id, section_id, flow_type, data),
            require_auth=True,
        )

    def save_expert_review(
        self,
        project_id: int,
        section_id: int,
        flow_type: int,
        data: str | list[dict[str, Any]],
    ) -> dict[str, Any]:
        """POST ``api/expert/saveReview`` — final expert submit for a flow step.

        ``flow_type`` matches progress step id (e.g. 3=形式评审, 4=资格评审, 5=响应性评审).
        For flow_type 3/4/5 on production, only the **last** expert may call this after
        all other signed experts have ``tender_flow`` rows (via ``saveOpinion``).
        """
        if isinstance(data, list):
            payload: dict[str, Any] | list[tuple[str, str]] = expert_review_items_to_form(
                project_id, section_id, flow_type, data
            )
        else:
            payload = {
                "project_id": project_id,
                "section_id": section_id,
                "flow_type": flow_type,
                "data": data,
            }
        return self.request(
            "POST",
            "api/expert/saveReview",
            data=payload,
            require_auth=True,
        )

    def check_expert_review(
        self,
        project_id: int,
        section_id: int,
        flow_type: int,
        data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """POST ``api/expert/checkReview`` — validate consensus before final submit."""
        return self.request(
            "POST",
            "api/expert/checkReview",
            data=expert_review_items_to_form(project_id, section_id, flow_type, data),
            require_auth=True,
        )

    def probe_expert_review_gate(
        self,
        project_id: int,
        section_id: int,
        flow_type: int = 3,
    ) -> dict[str, Any]:
        """Minimal saveReview probe — leader not elected vs expert sync gate."""
        return self.save_expert_review(project_id, section_id, flow_type, "[]")

    def run_preliminary_review_step(
        self,
        project_id: int,
        section_id: int,
        flow_type: int,
        review_type: int,
        expert_tokens: list[str],
        *,
        pass_status: int = 2,
        review_list_data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Run one pass/fail review step for all experts (形式/资格/响应性).

        Uses ``saveOpinion`` for every expert except the last, then ``saveReview``.
        """
        if not expert_tokens:
            raise ZjgjApiError(-1, "expert_tokens required for preliminary review")
        if review_list_data is None:
            review_list_data = self.get_expert_review_list(project_id, section_id, review_type).get("data") or {}
        items = build_expert_review_items(review_list_data, pass_status=pass_status, review_type=review_type)
        if not items:
            raise ZjgjApiError(-1, f"no review rows for type={review_type}")

        results: list[dict[str, Any]] = []
        for index, token in enumerate(expert_tokens):
            client = ZjgjClient(self.base_url.rstrip("/") + "/", token=token, verify_ssl=self.verify_ssl)
            is_last = index == len(expert_tokens) - 1
            if is_last:
                resp = client.save_expert_review(project_id, section_id, flow_type, items)
                phase = "saveReview"
            else:
                resp = client.save_expert_opinion(project_id, section_id, flow_type, items)
                phase = "saveOpinion"
            results.append({"phase": phase, "expert_index": index, "code": resp.get("code"), "msg": resp.get("msg")})
        return results

    def run_formal_review(
        self,
        project_id: int,
        section_id: int,
        expert_tokens: list[str],
        *,
        review_list_data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Submit 形式评审 (``flow_type=3``, ``reviewList`` type=1) for all experts."""
        return self.run_preliminary_review_step(
            project_id,
            section_id,
            flow_type=3,
            review_type=1,
            expert_tokens=expert_tokens,
            review_list_data=review_list_data,
        )

    def run_scoring_review_step(
        self,
        project_id: int,
        section_id: int,
        flow_type: int,
        review_type: int,
        expert_tokens: list[str],
        *,
        review_list_data: dict[str, Any] | None = None,
        score_strategy: str = "varied",
        uniform_score: int | None = None,
        use_price_builder: bool = False,
        apply_ids: list[int] | None = None,
        price_default_score: int = 30,
    ) -> list[dict[str, Any]]:
        """Run one scoring step (商务/技术/报价) for all experts.

        Same saveOpinion×(N-1) + saveReview gate as preliminary review.
        ``flow_type`` 7/8/9 maps to reviewList types 4/5/6 per Manage.php.
        Default ``score_strategy`` is ``varied`` so test runs do not assign
        identical marks to every bidder/criterion.
        """
        if not expert_tokens:
            raise ZjgjApiError(-1, "expert_tokens required for scoring review")
        if review_list_data is None:
            review_list_data = self.get_expert_review_list(project_id, section_id, review_type).get("data") or {}
        if use_price_builder or flow_type == 9:
            items = build_expert_price_score_items(
                review_list_data,
                apply_ids=apply_ids,
                default_score=price_default_score,
                score_strategy=score_strategy,
            )
        else:
            items = build_expert_scoring_items(
                review_list_data,
                review_type=review_type,
                score_strategy=score_strategy,
                uniform_score=uniform_score,
            )
        if not items:
            raise ZjgjApiError(-1, f"no scoring rows for reviewList type={review_type}")

        scores = [item.get("score") for item in items if item.get("score") is not None]
        score_summary = {
            "sample_score": items[0].get("score") if items else None,
            "score_min": min(scores) if scores else None,
            "score_max": max(scores) if scores else None,
            "score_unique_count": len(set(scores)) if scores else 0,
        }

        results: list[dict[str, Any]] = []
        for index, token in enumerate(expert_tokens):
            client = ZjgjClient(self.base_url.rstrip("/") + "/", token=token, verify_ssl=self.verify_ssl)
            is_last = index == len(expert_tokens) - 1
            if is_last:
                resp = client.save_expert_review(project_id, section_id, flow_type, items)
                phase = "saveReview"
            else:
                resp = client.save_expert_opinion(project_id, section_id, flow_type, items)
                phase = "saveOpinion"
            results.append(
                {
                    "phase": phase,
                    "expert_index": index,
                    "code": resp.get("code"),
                    "msg": resp.get("msg"),
                    "item_count": len(items),
                    **score_summary,
                }
            )
        return results

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

    def check_manage_report(self, project_id: int, section_id: int) -> dict[str, Any]:
        """Whether PM has submitted 评标报告.

        Production routes ``checkReport`` under ``api/expert/`` (handler: Manage/checkReport).
        """
        return self.request(
            "GET",
            "api/expert/checkReport",
            params={"project_id": project_id, "section_id": section_id},
            require_auth=True,
        )

    def save_evaluation_report(
        self,
        project_id: int,
        section_id: int,
        *,
        content1: str,
        content2: str = "无",
        content3: str = "无",
        apply_id1: int | None = None,
        apply_id2: int | None = None,
        apply_id3: int | None = None,
        candidate_apply_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Submit PM 评标报告 via ``api/manage/saveReport``.

        Required by backend: ``content1``, ``content2``, ``content3``, ``apply_id1``.
        When ``candidate_apply_ids`` is omitted, loads ranked companies from
        ``getReport`` (highest ``total_score`` first) and fills ``apply_id1..3``.
        """
        payload: dict[str, Any] = {
            "project_id": project_id,
            "section_id": section_id,
            "content1": content1,
            "content2": content2,
            "content3": content3,
        }

        ids = list(candidate_apply_ids or [])
        if not ids:
            report = self.get_manage_report(project_id, section_id)
            companies = (report.get("data") or {}).get("company") or []
            ids = [int(c["apply_id"]) for c in companies if c.get("apply_id") is not None]

        if apply_id1 is None and ids:
            apply_id1 = ids[0]
        if apply_id1 is None:
            raise ZjgjApiError(-1, "apply_id1 required for saveReport (no candidates from getReport)")

        payload["apply_id1"] = apply_id1
        if apply_id2 is None and len(ids) > 1:
            apply_id2 = ids[1]
        if apply_id3 is None and len(ids) > 2:
            apply_id3 = ids[2]
        if apply_id2 is not None:
            payload["apply_id2"] = apply_id2
        if apply_id3 is not None:
            payload["apply_id3"] = apply_id3

        return self.request(
            "POST",
            "api/manage/saveReport",
            data=payload,
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


def leader_vote_already_done(message: str) -> bool:
    """Return True when leaderVote indicates the expert already cast their vote."""
    msg = str(message or "")
    return "已投过票" in msg or "重复投票" in msg


@dataclass
class ZjgjAdminClient:
    """Legacy ThinkPHP admin panel client (session cookie auth).

    Admin UI is mapped to ``/zjgj230214/`` on production (see ZJGJ ``.env``
    ``ADMIN_MAP``), not ``/admin/``. Use env vars for credentials — never commit
    passwords to config files.
    """

    base_url: str
    admin_prefix: str = "/zjgj230214"
    admin_name: str | None = None
    admin_password: str | None = None
    timeout: int = 30
    verify_ssl: bool = True
    _logged_in: bool = False

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.admin_prefix = "/" + self.admin_prefix.strip("/")
        self.session = requests.Session()
        if not self.verify_ssl:
            self.session.verify = False
            try:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:
                pass
        if self.admin_name is None:
            self.admin_name = os.environ.get("ZJGJ_ADMIN_NAME")
        if self.admin_password is None:
            self.admin_password = os.environ.get("ZJGJ_ADMIN_PASSWORD")

    def _url(self, path: str) -> str:
        return f"{self.base_url}{self.admin_prefix}/{path.lstrip('/')}"

    def _solve_captcha(self, image_bytes: bytes) -> str:
        try:
            import ddddocr
        except ImportError as exc:
            raise ZjgjApiError(
                -1,
                "ddddocr is required for admin captcha OCR; pip install ddddocr",
            ) from exc

        ocr = ddddocr.DdddOcr(show_ad=False)
        captcha = "".join(ch for ch in ocr.classification(image_bytes) if ch in "123456")
        if len(captcha) != 4:
            raise ZjgjApiError(-1, f"admin captcha OCR failed: {captcha!r}")
        return captcha

    def admin_login(
        self,
        *,
        captcha: str | None = None,
        max_attempts: int = 10,
    ) -> dict[str, Any]:
        """POST ``login/check.html`` with admin_name, password, captcha."""
        if not self.admin_name or not self.admin_password:
            raise ZjgjApiError(-1, "Set ZJGJ_ADMIN_NAME and ZJGJ_ADMIN_PASSWORD env vars")

        last_error: str | None = None
        for _ in range(max_attempts):
            if captcha is None:
                image = self.session.get(f"{self.base_url}/captcha.html", timeout=self.timeout).content
                captcha_value = self._solve_captcha(image)
            else:
                captcha_value = captcha
                captcha = None

            response = self.session.post(
                self._url("login/check.html"),
                data={
                    "admin_name": self.admin_name,
                    "password": self.admin_password,
                    "captcha": captcha_value,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") == 1:
                self._logged_in = True
                return payload

            last_error = str(payload.get("msg", "admin login failed"))
            if "验证码" not in last_error:
                raise ZjgjApiError(payload.get("code", -1), last_error, payload)

        raise ZjgjApiError(-1, last_error or "admin login failed after captcha retries")

    def _require_admin_session(self) -> None:
        if not self._logged_in and not self.session.cookies.get("PHPSESSID"):
            self.admin_login()

    def list_bidder_users(
        self,
        *,
        page: int = 1,
        limit: int = 20,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return bidder rows from admin user list (includes ``token`` field)."""
        self._require_admin_session()
        params: dict[str, Any] = {
            "page": page,
            "limit": limit,
            "tableUniqueStr": "admin_user_ordinary",
            "0[0]": "user_type",
            "0[1]": "like",
            "0[2]": "%1%",
        }
        if search:
            params["code__nickname__mobile"] = search

        response = self.session.get(
            self._url("user/getList.html"),
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") not in (0, "0"):
            raise ZjgjApiError(payload.get("code", -1), payload.get("msg", "user list failed"), payload)
        data = payload.get("data")
        return data if isinstance(data, list) else []

    def get_user_token_by_phone(self, phone: str) -> str:
        rows = self.list_bidder_users(search=phone, limit=10)
        for row in rows:
            if str(row.get("mobile", "")) == str(phone) and row.get("token"):
                return str(row["token"])
        raise ZjgjApiError(-1, f"bidder token not found for phone {phone}")

    def impersonate_user(self, user_id: int) -> str:
        """GET ``user/login.html?id=`` — sets member ``token`` cookie, returns token."""
        self._require_admin_session()
        response = self.session.get(
            self._url("user/login.html"),
            params={"id": user_id},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 1:
            raise ZjgjApiError(payload.get("code", -1), payload.get("msg", "impersonation failed"), payload)

        token = self.session.cookies.get("token")
        if not token:
            raise ZjgjApiError(-1, f"impersonation succeeded but no token cookie for user_id={user_id}")
        return str(token)


def bidder_client_from_admin_phone(
    base_url: str,
    phone: str,
    *,
    admin_prefix: str = "/zjgj230214",
    verify_ssl: bool = True,
) -> ZjgjClient:
    """Admin login + user-list lookup → ``ZjgjClient`` with bidder token."""
    admin = ZjgjAdminClient(base_url, admin_prefix=admin_prefix, verify_ssl=verify_ssl)
    token = admin.get_user_token_by_phone(phone)
    return ZjgjClient(base_url, token=token, verify_ssl=verify_ssl)

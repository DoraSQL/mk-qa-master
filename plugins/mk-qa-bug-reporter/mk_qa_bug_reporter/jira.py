"""把 bug report 送到 Jira Cloud。

- 這個 bug 第一次出現 → 建立一張 issue。
- 同一個 bug 再次出現 → 在原本那張 issue 加一則留言，不重複開單。
  「哪個 Bug ID 對應哪張 issue」記在 bug-reports/.index.json。

設定全部來自環境變數（教學見 README 的「送到 Jira」）：

| 環境變數                         | 必填 | 說明                                          |
|----------------------------------|------|-----------------------------------------------|
| QA_BUG_REPORT_JIRA_URL           | 是   | 例如 https://your-team.atlassian.net          |
| QA_BUG_REPORT_JIRA_EMAIL         | 是   | 登入 Jira 用的 email                          |
| QA_BUG_REPORT_JIRA_API_TOKEN     | 是   | API token（不是密碼）                         |
| QA_BUG_REPORT_JIRA_PROJECT       | 是   | 專案代碼，例如 QA                             |
| QA_BUG_REPORT_JIRA_ISSUE_TYPE    | 否   | 預設 Bug                                      |
| QA_BUG_REPORT_JIRA_LABELS        | 否   | 逗號分隔，預設 mk-qa-bug-reporter；設成 none 則不加標籤 |
| QA_BUG_REPORT_JIRA_DRY_RUN       | 否   | 設 1 → 只顯示將會送出什麼，不真的送           |
| QA_BUG_REPORT_JIRA_TIMEOUT       | 否   | 連線逾時秒數，預設 15                         |

關於 API token 的安全：
- 只從環境變數讀，只放在記憶體裡，只用在 HTTP 的驗證標頭。
- 不會寫進任何檔案（包含 .index.json 與 dry-run 預覽檔）。
- 所有對外的文字（錯誤訊息、回傳給 AI 的結果）都先經過 redact() 把它遮掉。
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .adf import bullet_list, document, markdown_to_adf, paragraph
from .base import Submitter
from .models import BugReport, SubmitResult
from .settings import Settings

ENV_URL = "QA_BUG_REPORT_JIRA_URL"
ENV_EMAIL = "QA_BUG_REPORT_JIRA_EMAIL"
ENV_TOKEN = "QA_BUG_REPORT_JIRA_API_TOKEN"
ENV_PROJECT = "QA_BUG_REPORT_JIRA_PROJECT"
ENV_ISSUE_TYPE = "QA_BUG_REPORT_JIRA_ISSUE_TYPE"
ENV_LABELS = "QA_BUG_REPORT_JIRA_LABELS"
ENV_DRY_RUN = "QA_BUG_REPORT_JIRA_DRY_RUN"
ENV_TIMEOUT = "QA_BUG_REPORT_JIRA_TIMEOUT"

DEFAULT_ISSUE_TYPE = "Bug"
DEFAULT_LABELS = ("mk-qa-bug-reporter",)
DEFAULT_TIMEOUT_S = 15.0
DRY_RUN_DIR_NAME = "jira-dry-run"
MAX_SUMMARY_CHARS = 255          # Jira 的 Summary 欄位上限
MAX_ERROR_CHARS = 300            # 錯誤訊息最多保留幾個字
MAX_COMMENT_TESTS = 20           # 留言裡最多列幾個失敗的測試
REDACTED = "***"

_TRUTHY = ("1", "true", "yes", "on")

_STATUS_HINTS = {
    401: "帳號或 API token 不正確（或 token 已過期、被撤銷）",
    403: "這個帳號沒有權限在該專案建立 issue 或留言",
    404: "找不到專案或 issue（請確認網址與專案代碼）",
    429: "Jira 暫時限制請求次數，稍後再試",
}


def redact(text: object, secrets: tuple[str, ...]) -> str:
    """把機密字串從文字中遮掉。任何要離開這個模組的訊息都要先經過這裡。"""
    out = str(text)
    for secret in secrets:
        if secret:
            out = out.replace(secret, REDACTED)
    return out


def mask_email(email: str) -> str:
    """do***@example.com：看得出是哪個帳號，但不完整顯示。"""
    name, sep, domain = email.partition("@")
    if not sep:
        return REDACTED if email else ""
    return f"{name[:2]}{REDACTED}@{domain}"


class JiraError(Exception):
    """Jira 連線或回應的錯誤。訊息已遮掉機密，可以安全地顯示或記錄。"""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class JiraConfig:
    base_url: str = ""
    email: str = ""
    token: str = field(default="", repr=False)   # repr=False：印出物件時不會帶出 token
    project: str = ""
    issue_type: str = DEFAULT_ISSUE_TYPE
    labels: tuple[str, ...] = DEFAULT_LABELS
    dry_run: bool = False
    timeout: float = DEFAULT_TIMEOUT_S

    @classmethod
    def from_env(cls) -> "JiraConfig":
        raw_labels = os.getenv(ENV_LABELS)
        if raw_labels is None:
            labels = DEFAULT_LABELS
        elif raw_labels.strip().lower() in ("", "none"):
            labels = ()
        else:
            # Jira 的標籤不能有空白
            labels = tuple(part.strip().replace(" ", "-") for part in raw_labels.split(",") if part.strip())
        try:
            timeout = float(os.getenv(ENV_TIMEOUT, "") or DEFAULT_TIMEOUT_S)
        except ValueError:
            timeout = DEFAULT_TIMEOUT_S
        return cls(
            base_url=os.getenv(ENV_URL, "").strip().rstrip("/"),
            email=os.getenv(ENV_EMAIL, "").strip(),
            token=os.getenv(ENV_TOKEN, "").strip(),
            project=os.getenv(ENV_PROJECT, "").strip(),
            issue_type=os.getenv(ENV_ISSUE_TYPE, "").strip() or DEFAULT_ISSUE_TYPE,
            labels=labels,
            dry_run=os.getenv(ENV_DRY_RUN, "").strip().lower() in _TRUTHY,
            timeout=timeout if timeout > 0 else DEFAULT_TIMEOUT_S,
        )

    def problems(self) -> list[str]:
        """設定有哪些問題。只會提到環境變數的「名稱」，不會帶出任何值。"""
        found = [
            f"尚未設定 {name}"
            for name, value in (
                (ENV_URL, self.base_url),
                (ENV_EMAIL, self.email),
                (ENV_TOKEN, self.token),
                (ENV_PROJECT, self.project),
            )
            if not value
        ]
        if self.base_url and not self.base_url.lower().startswith("https://"):
            found.append(f"{ENV_URL} 必須以 https:// 開頭（避免 token 以未加密的方式傳送）")
        return found

    @property
    def secrets(self) -> tuple[str, ...]:
        """需要從所有輸出中遮掉的字串：token 本身，以及它在驗證標頭裡的編碼形式。"""
        if not self.token:
            return ()
        encoded = base64.b64encode(f"{self.email}:{self.token}".encode("utf-8")).decode("ascii")
        return (self.token, encoded)


HttpCallable = Callable[..., Any]


class JiraClient:
    """和 Jira Cloud REST API 溝通的最小實作：建立 issue、新增留言。"""

    def __init__(self, config: JiraConfig, http: HttpCallable | None = None):
        self._config = config
        self._http = http          # 測試時傳入假的；平常為 None，使用 requests

    def __repr__(self) -> str:
        return f"JiraClient(base_url={self._config.base_url!r}, project={self._config.project!r})"

    def create_issue(self, fields: dict) -> str:
        data = self._post("/rest/api/3/issue", {"fields": fields})
        key = str(data.get("key") or "")
        if not key:
            raise JiraError("Jira 回應裡沒有 issue 編號")
        return key

    def add_comment(self, issue_key: str, body: dict) -> str:
        data = self._post(f"/rest/api/3/issue/{issue_key}/comment", {"body": body})
        return str(data.get("id") or "")

    def _post(self, path: str, payload: dict) -> dict:
        config = self._config
        http = self._http
        if http is None:
            try:
                import requests
            except ImportError as e:  # pragma: no cover — requests 是 mk-qa-master 的相依套件
                raise JiraError("找不到 requests 套件，無法連線到 Jira") from e
            http = requests.request
        try:
            response = http(
                "POST",
                f"{config.base_url}{path}",
                json=payload,
                auth=(config.email, config.token),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=config.timeout,
                allow_redirects=False,
            )
        except Exception as e:  # noqa: BLE001 — 連不上、逾時、DNS 失敗等一律轉成 JiraError
            detail = redact(e, config.secrets)[:MAX_ERROR_CHARS]
            raise JiraError(f"連不上 Jira（{type(e).__name__}）：{detail}") from None

        status = int(getattr(response, "status_code", 0) or 0)
        try:
            data = response.json()
        except Exception:  # noqa: BLE001 — 回應不是 JSON
            data = {}
        if not isinstance(data, dict):
            data = {}
        if not 200 <= status < 300:
            raise JiraError(self._describe_error(status, data), status=status)
        return data

    def _describe_error(self, status: int, data: dict) -> str:
        parts: list[str] = [str(m) for m in (data.get("errorMessages") or []) if m]
        errors = data.get("errors")
        if isinstance(errors, dict):
            parts += [f"{name}: {message}" for name, message in errors.items()]
        text = f"Jira 回傳 HTTP {status}"
        hint = _STATUS_HINTS.get(status)
        if hint:
            text += f"（{hint}）"
        if parts:
            text += "：" + "；".join(parts)
        return redact(text, self._config.secrets)[: MAX_ERROR_CHARS + 60]


class JiraSubmitter(Submitter):
    name = "jira"

    def __init__(self, config: JiraConfig, output_dir: Path, client: JiraClient | None = None):
        self.config = config
        self.output_dir = Path(output_dir)
        self.client = client or JiraClient(config)

    @classmethod
    def from_settings(cls, settings: Settings) -> "JiraSubmitter":
        config = JiraConfig.from_env()
        problems = config.problems()
        if problems and not config.dry_run:
            # dry-run 時允許設定不完整：先讓使用者看到「將會送出什麼」，問題列在預覽裡。
            raise ValueError("Jira 設定不完整：" + "；".join(problems))
        return cls(config, settings.output_dir)

    # ---- 要送出的內容 -------------------------------------------------------

    def issue_fields(self, report: BugReport, markdown: str) -> dict:
        summary = " ".join((report.title or report.summary).split())[:MAX_SUMMARY_CHARS]
        fields: dict = {
            "project": {"key": self.config.project},
            "issuetype": {"name": self.config.issue_type},
            "summary": summary,
            "description": markdown_to_adf(markdown),
        }
        if self.config.labels:
            # 多加一個帶指紋的標籤，之後可以在 Jira 用它搜尋同一個 bug。
            fields["labels"] = [*self.config.labels, f"bug-{report.fingerprint}"]
        return fields

    def comment_body(self, report: BugReport) -> dict:
        items = [f"時間：{report.last_seen}"] if report.last_seen else []
        runner = report.environment.get("runner")
        if runner:
            items.append(f"Runner：{runner}")
        if report.devices:
            items.append("裝置：" + "、".join(report.devices))
        items.append(f"錯誤摘要：{report.summary}")
        tests = [f"`{f.nodeid}`" for f in report.failures[:MAX_COMMENT_TESTS]]
        if len(report.failures) > MAX_COMMENT_TESTS:
            tests.append(f"…其餘 {len(report.failures) - MAX_COMMENT_TESTS} 個省略")
        nodes = [
            paragraph(f"同一個錯誤再次出現（第 {report.occurrences} 次，Bug ID：{report.bug_id}）。"),
            bullet_list(items),
            paragraph("本次失敗的測試："),
        ]
        if tests:
            nodes.append(bullet_list(tests))
        nodes.append(paragraph("由 mk-qa-bug-reporter 自動留言。"))
        return document(nodes)

    # ---- 送出 ---------------------------------------------------------------

    def submit(self, report: BugReport, markdown: str) -> SubmitResult:
        try:
            return self._submit(report, markdown)
        except JiraError as e:
            return SubmitResult(ok=False, detail=redact(e, self.config.secrets))
        except Exception as e:  # noqa: BLE001 — 任何意外都不能讓測試流程失敗，也不能洩漏 token
            return SubmitResult(ok=False, detail=redact(f"{type(e).__name__}: {e}", self.config.secrets)[:MAX_ERROR_CHARS])

    def _submit(self, report: BugReport, markdown: str) -> SubmitResult:
        existing = report.refs.get(self.name, "")

        if self.config.dry_run:
            return self._dry_run(report, markdown, existing)

        note = ""
        if existing:
            try:
                self.client.add_comment(existing, self.comment_body(report))
            except JiraError as e:
                if e.status != 404:
                    raise
                # 原本的 issue 已被刪除或搬走 → 重新開一張。
                note = f"原本的 {existing} 已不存在，重新建立"
            else:
                return SubmitResult(
                    ok=True, ref=existing, detail=f"已在 {existing} 新增留言",
                    info={"action": "commented", "url": self._browse_url(existing)},
                )

        key = self.client.create_issue(self.issue_fields(report, markdown))
        detail = f"已建立 {key}" + (f"（{note}）" if note else "")
        return SubmitResult(ok=True, ref=key, detail=detail, info={"action": "created", "url": self._browse_url(key)})

    def _browse_url(self, key: str) -> str:
        return f"{self.config.base_url}/browse/{key}"

    def _dry_run(self, report: BugReport, markdown: str, existing: str) -> SubmitResult:
        """不連線，只把「將會送出什麼」整理出來，並存成檔案方便檢視。"""
        config = self.config
        if existing:
            action = "add_comment"
            path = f"/rest/api/3/issue/{existing}/comment"
            payload: dict = {"body": self.comment_body(report)}
            what = f"將在 {existing} 新增留言"
        else:
            action = "create_issue"
            path = "/rest/api/3/issue"
            payload = {"fields": self.issue_fields(report, markdown)}
            what = f"將在專案 {config.project or '（未設定）'} 建立一張 {config.issue_type}"

        preview = {
            "說明": "這是 dry-run 預覽：以下內容「沒有」送到 Jira。",
            "method": "POST",
            "url": f"{config.base_url or '（未設定 Jira 網址）'}{path}",
            "auth": f"帳號 {mask_email(config.email) or '（未設定）'} + API token（已隱藏）",
            "payload": payload,
        }
        problems = config.problems()
        if problems:
            preview["設定問題"] = problems

        info: dict = {
            "dry_run": True,
            "action": action,
            "url": preview["url"],
            "auth": preview["auth"],
            "summary": payload["fields"]["summary"] if action == "create_issue" else None,
            "labels": payload.get("fields", {}).get("labels"),
        }
        if problems:
            info["problems"] = problems
        try:
            directory = self.output_dir / DRY_RUN_DIR_NAME
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{report.bug_id}.json"
            text = json.dumps(preview, ensure_ascii=False, indent=2)
            target.write_text(redact(text, config.secrets), encoding="utf-8")
            info["preview_file"] = str(target)
        except OSError as e:
            info["preview_file_error"] = type(e).__name__

        # ref 留空：dry-run 沒有真的建立 issue，不能記成「已經開過單」。
        return SubmitResult(ok=True, ref="", detail=f"dry-run：{what}（沒有真的送出）", info=info)

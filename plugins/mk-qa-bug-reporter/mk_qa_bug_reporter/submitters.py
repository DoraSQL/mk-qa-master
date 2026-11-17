"""步驟 ④：把報告「送出」。

Submitter 是「送出管道」的共同介面。目前有兩個：

    file → FileSubmitter（這個檔案）：存成 Markdown 檔
    jira → JiraSubmitter（jira.py）：建立 Jira issue 或留言

用環境變數 QA_BUG_REPORT_SUBMITTERS 選擇，例如 file,jira。

要再接別的系統（Slack、GitHub Issues…），只要：

1. 新增一個繼承 Submitter（定義在 base.py）的類別，實作 submit()
2. 把它加進最下面的 SUBMITTERS 字典
3. 在 QA_BUG_REPORT_SUBMITTERS 加上它的名稱

前面三個步驟（收集、合併、產生 Markdown）完全不用改。
"""
from __future__ import annotations

from pathlib import Path

from .base import Submitter
from .jira import JiraSubmitter
from .models import BugReport, SubmitResult
from .settings import Settings


class FileSubmitter(Submitter):
    """把報告存成 <輸出資料夾>/<Bug ID>.md。相同的 bug 會覆寫同一個檔案。"""

    name = "file"

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)

    @classmethod
    def from_settings(cls, settings: Settings) -> "FileSubmitter":
        return cls(settings.output_dir)

    def submit(self, report: BugReport, markdown: str) -> SubmitResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{report.bug_id}.md"
        path.write_text(markdown, encoding="utf-8")
        return SubmitResult(ok=True, ref=str(path))


# 名稱 → 類別。QA_BUG_REPORT_SUBMITTERS 裡寫的名稱會到這裡查。
SUBMITTERS: dict[str, type[Submitter]] = {
    "file": FileSubmitter,
    "jira": JiraSubmitter,
}


def _make_one(name: str, settings: Settings) -> Submitter:
    cls = SUBMITTERS.get(name)
    if cls is None:
        raise ValueError(
            f"未知的送出管道 {name!r}（QA_BUG_REPORT_SUBMITTERS）。可用：{sorted(SUBMITTERS)}"
        )
    return cls.from_settings(settings)


def make_submitters(settings: Settings) -> list[Submitter]:
    """建立所有設定的送出管道；任何一個有問題就直接報錯。"""
    return [_make_one(name, settings) for name in settings.submitters]


def build_submitters(settings: Settings) -> tuple[list[Submitter], dict[str, str]]:
    """和 make_submitters 一樣，但不會因為其中一個管道設定錯誤而全部停擺。

    回傳 (可用的管道, {無法建立的管道名稱: 原因})。hook 用這個版本，
    所以 Jira 設定有誤時，檔案報告仍然照常產生。
    """
    ready: list[Submitter] = []
    errors: dict[str, str] = {}
    for name in settings.submitters:
        try:
            ready.append(_make_one(name, settings))
        except Exception as e:  # noqa: BLE001
            errors[name] = str(e) or type(e).__name__
    return ready, errors


__all__ = ["Submitter", "FileSubmitter", "JiraSubmitter", "SUBMITTERS", "make_submitters", "build_submitters"]

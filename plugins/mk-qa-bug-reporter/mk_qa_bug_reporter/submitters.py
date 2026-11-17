"""步驟 ④：把報告「送出」。

Submitter 是預留的介面：今天只有 FileSubmitter（存成檔案）。
以後要接 Jira，只要：

1. 在這個檔案新增一個繼承 Submitter 的類別，實作 submit()
2. 把它加進最下面的 SUBMITTERS 字典，例如 "jira": JiraSubmitter
3. 設定環境變數 QA_BUG_REPORT_SUBMITTERS=file,jira

前面三個步驟（收集、合併、產生 Markdown）完全不用改。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .models import BugReport, SubmitResult
from .settings import Settings


class Submitter(ABC):
    """送出管道的共同介面。"""

    name: str = "base"

    @classmethod
    def from_settings(cls, settings: Settings) -> "Submitter":
        """用設定建立物件。需要額外設定（網址、金鑰）的管道可以覆寫這個方法，
        並自行從環境變數讀取。"""
        return cls()

    @abstractmethod
    def submit(self, report: BugReport, markdown: str) -> SubmitResult:
        """送出一份報告。

        report   — 結構化資料。常用欄位：
                   report.title        標題（可當 Jira 的 Summary）
                   report.severity     嚴重度
                   report.fingerprint  錯誤指紋（可當 Jira label 來找既有的單）
                   report.is_new       這個 bug 是不是第一次出現
                   report.refs         先前各管道回傳的位置，例如 {"jira": "QA-123"}
        markdown — 已排版好的完整報告內文（可當 Jira 的 Description）

        回傳 SubmitResult；其中的 ref 會被記進索引，下次同一個 bug 再出現時
        可從 report.refs[self.name] 取回，用來「更新」而不是「重開」。
        """


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
}


def make_submitters(settings: Settings) -> list[Submitter]:
    submitters: list[Submitter] = []
    for name in settings.submitters:
        cls = SUBMITTERS.get(name)
        if cls is None:
            raise ValueError(
                f"未知的送出管道 {name!r}（QA_BUG_REPORT_SUBMITTERS）。可用：{sorted(SUBMITTERS)}"
            )
        submitters.append(cls.from_settings(settings))
    return submitters

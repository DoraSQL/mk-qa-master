"""Submitter：所有「送出管道」都要遵守的共同介面。

獨立成一個檔案，是為了讓 submitters.py（登記表）和 jira.py（Jira 的實作）
都能引用它，而不會互相等對方先載入。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .models import BugReport, SubmitResult
from .settings import Settings


class Submitter(ABC):
    """送出管道的共同介面。"""

    name: str = "base"

    @classmethod
    def from_settings(cls, settings: Settings) -> "Submitter":
        """用設定建立物件。需要額外設定（網址、金鑰）的管道可以覆寫這個方法，
        並自行從環境變數讀取。設定有問題時請丟出 ValueError，訊息裡不要帶機密。"""
        return cls()

    @abstractmethod
    def submit(self, report: BugReport, markdown: str) -> SubmitResult:
        """送出一份報告。

        report   — 結構化資料。常用欄位：
                   report.title        標題
                   report.severity     嚴重度
                   report.fingerprint  錯誤指紋
                   report.is_new       這個 bug 是不是第一次出現
                   report.occurrences  第幾次出現
                   report.refs         先前各管道回傳的位置，例如 {"jira": "QA-123"}
        markdown — 已排版好的完整報告內文

        回傳 SubmitResult：
        - ok=True 時，ref 會被記進索引。下次同一個 bug 再出現，可從
          report.refs[self.name] 取回，用來「更新」而不是「重開」。
        - ok=False 時，detail 請寫原因（不可包含機密）。也可以直接丟例外，
          hook 會接住，不會影響其他管道與測試流程。
        """

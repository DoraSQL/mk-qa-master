"""資料結構：整個插件在各步驟之間傳遞的幾種「表單」。

Failure      = 一個失敗的測試（從 runner 拿到的原始資料）
BugReport    = 一份 bug report（一個或多個「錯誤相同」的 Failure 合併而成）
SubmitResult = 送出一份報告後的結果
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Failure:
    nodeid: str                      # 測試的完整名稱，例如 tests/test_a.py::test_login
    message: str = ""                # runner 給的完整錯誤訊息
    title: str | None = None         # 測試函式的 docstring（有些 runner 沒有）
    duration: float | None = None
    steps: list[dict] = field(default_factory=list)  # [{"api": ..., "title": ...}]
    screenshot: str | None = None
    trace: str | None = None
    video: str | None = None

    @property
    def short_name(self) -> str:
        return self.nodeid.split("::")[-1] or self.nodeid


@dataclass
class BugReport:
    bug_id: str                      # 例如 BUG-3f9a1c2b，同時也是檔名
    fingerprint: str                 # 錯誤指紋（雜湊），用來判斷「是不是同一個 bug」
    signature: str                   # 正規化後的錯誤文字（指紋就是它的雜湊）
    summary: str                     # 一行錯誤摘要
    failures: list[Failure]          # 這次執行中屬於這個 bug 的失敗測試
    severity: str = "Medium"
    environment: dict[str, str] = field(default_factory=dict)
    title: str = ""                  # 由 render.render_title() 填入
    # 以下由 store.py 依歷史紀錄填入
    occurrences: int = 1
    first_seen: str = ""
    last_seen: str = ""
    known_tests: list[str] = field(default_factory=list)  # 歷來受影響過的所有測試
    refs: dict[str, str] = field(default_factory=dict)    # 各送出管道的位置，例如 {"file": "...md"}
    is_new: bool = True


@dataclass
class SubmitResult:
    ok: bool
    ref: str = ""        # 報告的位置：檔案路徑，或未來的 Jira issue key
    detail: str = ""     # 失敗時的原因

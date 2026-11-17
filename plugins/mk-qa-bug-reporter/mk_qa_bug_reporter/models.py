"""資料結構：整個插件在各步驟之間傳遞的幾種「表單」。

Failure      = 一個失敗的測試（從 runner 拿到的原始資料）
BugReport    = 一份 bug report（一個或多個「錯誤相同」的 Failure 合併而成）
SubmitResult = 送出一份報告後的結果
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .devices import split_device


def _unique(values) -> list[str]:
    """去除重複並保留第一次出現的順序。"""
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(value, None)
    return list(seen)


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
    # 以下兩項由 nodeid 自動算出，不需要自己填
    device: str | None = field(init=False, default=None)   # 例如 "iPhone 15"；沒有裝置時為 None
    base_nodeid: str = field(init=False, default="")       # 去掉裝置後的測試名稱

    def __post_init__(self) -> None:
        self.device, self.base_nodeid = split_device(self.nodeid)

    @property
    def short_name(self) -> str:
        return self.nodeid.split("::")[-1] or self.nodeid

    @property
    def base_short_name(self) -> str:
        return self.base_nodeid.split("::")[-1] or self.base_nodeid


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

    @property
    def devices(self) -> list[str]:
        """這次執行中受影響的裝置（不重複，依出現順序）。"""
        return _unique(f.device for f in self.failures)

    @property
    def base_tests(self) -> list[str]:
        """這次執行中受影響的測試，同一個測試在不同裝置上只算一個。"""
        return _unique(f.base_nodeid for f in self.failures)


@dataclass
class SubmitResult:
    ok: bool
    ref: str = ""        # 報告的位置：檔案路徑，或 Jira issue key
    detail: str = ""     # 補充說明；失敗時是原因
    info: dict = field(default_factory=dict)   # 想讓 AI／使用者看到的額外資訊（不可放機密）

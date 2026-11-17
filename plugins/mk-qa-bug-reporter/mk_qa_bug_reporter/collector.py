"""步驟 ①：收集這次執行中失敗的測試。

result hook 收到的 event 只有結束代碼和輸出尾段，沒有「哪些測試失敗」，
所以這裡改向目前的 runner 要資料。好處是 pytest / jest / maestro 各自的
報告格式差異由 runner 處理，本插件不用管。
"""
from __future__ import annotations

from typing import Any

from .models import Failure

# 視為「失敗」的結果。"error" 是 pytest 在 setup/teardown 階段出錯時的結果。
FAILED_OUTCOMES = ("failed", "error")


def collect_failures(runner: Any = None) -> list[Failure]:
    if runner is None:
        from mk_qa_master.runners import get_runner

        runner = get_runner()

    # 優先用「全部測試明細」（含步驟與附件）；runner 不支援時會回傳空清單，
    # 這時退回每個 runner 都必須實作的 get_failure_details()。
    details = runner.get_all_test_details() or []
    if details:
        rows = [d for d in details if isinstance(d, dict) and d.get("outcome") in FAILED_OUTCOMES]
    else:
        rows = runner.get_failure_details() or []

    failures: list[Failure] = []
    seen: set[str] = set()
    for row in rows:
        # 沒有報告時 runner 會回傳 [{"error": "找不到報告"}] 這種列，跳過。
        if not isinstance(row, dict) or not row.get("nodeid"):
            continue
        nodeid = str(row["nodeid"])
        if nodeid in seen:
            continue
        seen.add(nodeid)
        title = str(row.get("title") or "").strip() or None
        duration = row.get("duration")
        failures.append(
            Failure(
                nodeid=nodeid,
                message=str(row.get("message") or ""),
                title=title,
                duration=duration if isinstance(duration, (int, float)) else None,
                steps=[s for s in (row.get("steps") or []) if isinstance(s, dict)],
                screenshot=row.get("screenshot") or None,
                trace=row.get("trace") or None,
                video=row.get("video") or None,
            )
        )
    return failures

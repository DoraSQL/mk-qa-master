"""步驟 ③：把 BugReport 變成 Markdown 文字。

想改報告的「長相」，幾乎都只需要改這個檔案：

- 改段落標題或欄位名稱的文字 → 改 LABELS
- 調整段落順序、拿掉某個段落 → 改 SECTION_ORDER
- 改某個段落的內容或排版 → 改對應的 _section_xxx() 函式
- 改報告標題的格式 → 改 render_title()

輸出是標準 Markdown（標題、清單、表格、程式碼區塊），可直接貼進
Jira Cloud 的新版編輯器。
"""
from __future__ import annotations

from typing import Callable

from .grouping import strip_ansi
from .models import BugReport, Failure

# ---- 可調整的文字 -----------------------------------------------------------

LABELS = {
    # 摘要表
    "field": "欄位",
    "value": "內容",
    "bug_id": "Bug ID",
    "severity": "嚴重度",
    "occurrences": "出現次數",
    "affected_count": "受影響測試數",
    # 段落標題
    "environment": "環境",
    "steps": "重現步驟",
    "expected": "預期結果",
    "actual": "實際結果",
    "error": "錯誤訊息",
    "attachments": "截圖／Trace／影片",
    "affected": "受影響的測試",
    # 附件
    "screenshot": "截圖",
    "trace": "Trace",
    "video": "影片",
    "none": "無",
}

# 報告由上到下的段落順序。刪掉某一項，該段落就不會出現。
SECTION_ORDER = [
    "summary",
    "environment",
    "steps",
    "expected",
    "actual",
    "error",
    "attachments",
    "affected",
]

ENVIRONMENT_LABELS = {
    "runner": "Runner",
    "tool": "觸發工具",
    "os": "作業系統",
    "python": "Python",
    "mk_qa_master": "mk-qa-master",
    "project_root": "專案路徑",
    "reported_at": "報告時間",
}

MAX_TITLE_CHARS = 120       # 標題最長幾個字
MAX_ERROR_CHARS = 6000      # 錯誤訊息最多保留幾個字（保留尾段，因為結論通常在最後）
MAX_STEPS = 30              # 重現步驟最多列幾個操作

# 這些 runner 的測試可以直接用 pytest 指令重跑。
_PYTEST_RUNNERS = ("pytest", "pytest-playwright", "playwright", "edge", "rtsp")


# ---- 標題 -------------------------------------------------------------------

def render_title(report: BugReport) -> str:
    """報告標題，例如：[test_login] TimeoutError: ...（共 2 個測試）"""
    first = report.failures[0]
    title = f"[{first.short_name}] {report.summary}"
    if len(title) > MAX_TITLE_CHARS:
        title = title[: MAX_TITLE_CHARS - 1] + "…"
    if len(report.failures) > 1:
        title += f"（共 {len(report.failures)} 個測試）"
    return title


# ---- 各段落 -----------------------------------------------------------------

def _cell(text: object) -> str:
    """表格儲存格內不能有換行或直線符號。"""
    return str(text).replace("|", "\\|").replace("\n", " ")


def _section_summary(report: BugReport) -> str:
    occurrences = f"{report.occurrences} 次"
    if report.first_seen and report.last_seen:
        occurrences += f"（首次 {report.first_seen}，最近 {report.last_seen}）"
    rows = [
        (LABELS["bug_id"], report.bug_id),
        (LABELS["severity"], report.severity),
        (LABELS["occurrences"], occurrences),
        (LABELS["affected_count"], len(report.failures)),
    ]
    lines = [f"| {LABELS['field']} | {LABELS['value']} |", "|---|---|"]
    lines += [f"| {_cell(k)} | {_cell(v)} |" for k, v in rows]
    return "\n".join(lines)


def _section_environment(report: BugReport) -> str:
    lines = [f"## {LABELS['environment']}", ""]
    for key, label in ENVIRONMENT_LABELS.items():
        value = report.environment.get(key)
        if value:
            lines.append(f"- {label}：{value}")
    return "\n".join(lines)


def _rerun_instruction(report: BugReport, failure: Failure) -> str:
    runner = report.environment.get("runner", "")
    if runner in _PYTEST_RUNNERS:
        return f'執行失敗的測試：`pytest "{failure.nodeid}"`'
    return f"以 `{runner or '目前的 runner'}` 執行測試 `{failure.nodeid}`（可透過 mk-qa-master 的 `run_tests`）"


def _section_steps(report: BugReport) -> str:
    first = report.failures[0]
    lines = [f"## {LABELS['steps']}", ""]
    project_root = report.environment.get("project_root")
    lines.append(f"1. 進入專案目錄：`{project_root}`" if project_root else "1. 進入受測專案目錄")
    lines.append(f"2. {_rerun_instruction(report, first)}")
    if first.steps:
        lines.append("3. 測試會依序執行以下操作，並在最後一步或其後的檢查失敗：")
        for step in first.steps[:MAX_STEPS]:
            api = str(step.get("api") or "").strip()
            detail = str(step.get("title") or "").strip()
            text = f"`{api}`" if api else ""
            if detail and detail != api:
                text = f"{text} {detail}".strip()
            lines.append(f"   - {text}")
        if len(first.steps) > MAX_STEPS:
            lines.append(f"   - …（其餘 {len(first.steps) - MAX_STEPS} 個操作省略）")
    else:
        lines.append("3. 觀察測試結果（此 runner 未提供逐步操作紀錄）")
    return "\n".join(lines)


def _section_expected(report: BugReport) -> str:
    first = report.failures[0]
    if first.title:
        body = f"{first.title}（測試 `{first.short_name}` 應通過）"
    else:
        body = f"測試 `{first.short_name}` 應通過，不應出現下方的錯誤。"
    return f"## {LABELS['expected']}\n\n{body}"


def _section_actual(report: BugReport) -> str:
    count = len(report.failures)
    scope = "測試失敗" if count == 1 else f"{count} 個測試以相同的錯誤失敗"
    return f"## {LABELS['actual']}\n\n{scope}：{report.summary}"


def _section_error(report: BugReport) -> str:
    first = report.failures[0]
    message = strip_ansi(first.message).strip()
    if not message:
        return f"## {LABELS['error']}\n\n（runner 未提供錯誤訊息）"
    note = ""
    if len(message) > MAX_ERROR_CHARS:
        message = message[-MAX_ERROR_CHARS:]
        note = f"\n\n（訊息過長，只保留最後 {MAX_ERROR_CHARS} 個字元）"
    message = message.replace("```", "'''")  # 避免訊息內容提早結束程式碼區塊
    source = f"取自 `{first.nodeid}`" if len(report.failures) > 1 else ""
    header = f"## {LABELS['error']}\n\n"
    if source:
        header += f"{source}\n\n"
    return f"{header}```text\n{message}\n```{note}"


def _section_attachments(report: BugReport) -> str:
    lines = [f"## {LABELS['attachments']}", ""]
    for failure in report.failures:
        lines.append(f"- `{failure.nodeid}`")
        for key in ("screenshot", "trace", "video"):
            path = getattr(failure, key)
            lines.append(f"  - {LABELS[key]}：{f'`{path}`' if path else LABELS['none']}")
    return "\n".join(lines)


def _section_affected(report: BugReport) -> str:
    lines = [f"## {LABELS['affected']}", "", "本次執行失敗："]
    for failure in report.failures:
        suffix = f" — {failure.title}" if failure.title else ""
        lines.append(f"- `{failure.nodeid}`{suffix}")
    current = {f.nodeid for f in report.failures}
    earlier = [t for t in report.known_tests if t not in current]
    if earlier:
        lines += ["", "先前也曾因同一錯誤失敗（本次未失敗）："]
        lines += [f"- `{t}`" for t in earlier]
    return "\n".join(lines)


_SECTIONS: dict[str, Callable[[BugReport], str]] = {
    "summary": _section_summary,
    "environment": _section_environment,
    "steps": _section_steps,
    "expected": _section_expected,
    "actual": _section_actual,
    "error": _section_error,
    "attachments": _section_attachments,
    "affected": _section_affected,
}


# ---- 組合 -------------------------------------------------------------------

def render_markdown(report: BugReport) -> str:
    """把整份報告組成一段 Markdown 文字。"""
    parts = [f"# {report.title or render_title(report)}"]
    for key in SECTION_ORDER:
        body = _SECTIONS[key](report)
        if body:
            parts.append(body)
    return "\n\n".join(parts) + "\n"

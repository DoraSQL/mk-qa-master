"""步驟 ②：把「錯誤相同」的失敗合併成同一份 bug report。

做法：把錯誤訊息「正規化」（抹掉每次都會變的部分），再算雜湊當作指紋。
指紋相同 = 同一個 bug。
"""
from __future__ import annotations

import hashlib
import re

from .models import BugReport, Failure

MAX_SIGNATURE_LINES = 8      # 指紋最多取幾行錯誤
MAX_SIGNATURE_CHARS = 600
MAX_SUMMARY_CHARS = 160

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_PYTEST_E_LINE_RE = re.compile(r"^E(?:\s+|$)")
_STACK_FRAME_RE = re.compile(r"^\s*(at\s+\S|File \")")   # JS / Python 的呼叫堆疊列
_RETRY_COUNT_RE = re.compile(r"\d+\s*×")                  # Playwright「9 × ...」重試次數
# 遇到這些開頭的列就停止：後面是當下頁面內容的快照，不是錯誤本身，
# 放進指紋會讓同一個 bug 因為頁面稍有不同而被當成不同的 bug。
_SIGNATURE_STOP_PREFIXES = ("Aria snapshot",)


def strip_ansi(text: str) -> str:
    """移除終端機顏色控制碼。"""
    return _ANSI_RE.sub("", text or "")


def error_lines(message: str) -> list[str]:
    """從完整錯誤訊息中挑出「真正在講錯誤」的那幾行。

    - pytest 的訊息裡，錯誤內容是以 `E   ` 開頭的列，其餘是原始碼片段。
    - 其他 runner（jest 等）沒有這個慣例，就取非堆疊的列。
    """
    lines = [ln.rstrip() for ln in strip_ansi(message).splitlines()]
    e_lines = [_PYTEST_E_LINE_RE.sub("", ln).strip() for ln in lines if _PYTEST_E_LINE_RE.match(ln)]
    e_lines = [ln for ln in e_lines if ln]
    if e_lines:
        return e_lines
    return [ln.strip() for ln in lines if ln.strip() and not _STACK_FRAME_RE.match(ln)]


def normalize_error(message: str) -> str:
    """把錯誤訊息變成穩定的「簽名」：同一個 bug 每次都應得到同一段文字。"""
    kept: list[str] = []
    for ln in error_lines(message):
        if ln.startswith(_SIGNATURE_STOP_PREFIXES):
            break
        if _RETRY_COUNT_RE.search(ln):
            continue                                   # 重試次數每次不同
        ln = re.sub(r"0x[0-9a-fA-F]+", "0xMEM", ln)    # 記憶體位址
        ln = re.sub(r":\d+\b", ":N", ln)               # 行號、連接埠
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln:
            kept.append(ln)
        if len(kept) >= MAX_SIGNATURE_LINES:
            break
    return "\n".join(kept)[:MAX_SIGNATURE_CHARS]


def summarize_error(message: str) -> str:
    """一行摘要：用在標題與「實際結果」。"""
    lines = error_lines(message)
    if not lines:
        return "（runner 未提供錯誤訊息）"
    first = re.sub(r"\s+", " ", lines[0]).strip()
    first = first.replace("```", "'''")  # 摘要會放進標題與內文，不能夾帶程式碼區塊符號
    if len(first) > MAX_SUMMARY_CHARS:
        first = first[: MAX_SUMMARY_CHARS - 1] + "…"
    return first


def loosen_for_devices(signature: str, device: str) -> str:
    """更寬鬆的簽名：再抹掉「裝置名稱」和「所有數字」。

    同一個問題在不同手機上，量到的數字通常不一樣（例如 `assert 800 <= 393`
    與 `assert 801 <= 412`），錯誤訊息裡也可能帶著裝置名稱。抹掉之後才比得出
    它們是同一種錯誤。
    """
    loose = signature
    for variant in (device, device.lower().replace(" ", "-")):   # "iPhone 15" 與 "iphone-15"
        loose = loose.replace(variant, "<device>")
    return re.sub(r"\d+(?:\.\d+)?", "N", loose)


def fingerprint_of(failure: Failure) -> tuple[str, str]:
    """回傳 (指紋, 簽名)。指紋相同的失敗會被放進同一份報告。

    規則有三條，依序判斷：

    1. 沒有錯誤訊息 → 用測試名稱當指紋，避免把不相干的失敗全併在一起。
    2. 測試有標示裝置，而且錯誤訊息含有數字或裝置名稱 → 用「去掉裝置的測試名稱
       ＋寬鬆簽名」當指紋。效果：同一個測試在不同裝置上以同一種錯誤失敗時會合併，
       但不會因為忽略數字而把「不同的測試」誤併在一起。
    3. 其他情況 → 用嚴格簽名當指紋。效果：錯誤訊息完全相同的失敗會合併，
       不論是哪個測試、哪個裝置。
    """
    signature = normalize_error(failure.message)
    if not signature:
        basis = f"no-message::{failure.base_nodeid if failure.device else failure.nodeid}"
    else:
        basis = signature
        if failure.device:
            loose = loosen_for_devices(signature, failure.device)
            if loose != signature:
                basis = f"cross-device::{failure.base_nodeid}\n{loose}"
                signature = loose
    digest = hashlib.sha1(basis.encode("utf-8", errors="replace")).hexdigest()[:8]
    return digest, signature


def group_failures(
    failures: list[Failure],
    severity: str = "Medium",
    environment: dict[str, str] | None = None,
) -> list[BugReport]:
    """指紋相同的 Failure 放進同一份 BugReport。順序依第一次出現的先後。"""
    reports: dict[str, BugReport] = {}
    for failure in failures:
        fingerprint, signature = fingerprint_of(failure)
        report = reports.get(fingerprint)
        if report is None:
            report = BugReport(
                bug_id=f"BUG-{fingerprint}",
                fingerprint=fingerprint,
                signature=signature,
                summary=summarize_error(failure.message),
                failures=[],
                severity=severity,
                environment=dict(environment or {}),
            )
            reports[fingerprint] = report
        report.failures.append(failure)
    return list(reports.values())

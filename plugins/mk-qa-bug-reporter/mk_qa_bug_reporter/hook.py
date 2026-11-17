"""入口：mk-qa-master 在 run_tests / run_failed 跑完後會呼叫 on_result(event)。

event 的內容（來自 mk_qa_master/tools/runner.py 的 _attach_result_hooks）：

    {
        "tool": "run_tests" 或 "run_failed",
        "runner": "pytest-playwright",          # runner 名稱
        "result": {"exit_code": 1, ...},        # runner 的回傳，不含失敗明細
        "report_path": ".../report.json",
        "project_root": "...",                  # 受測專案根目錄
    }

這個檔案只負責把四個步驟串起來：
    ① collector  收集失敗
    ② grouping   合併相同錯誤（+ store 對照歷史）
    ③ render     產生 Markdown
    ④ submitters 送出（今天 = 存檔）

回傳的 dict 會出現在 AI 看到的 run_tests 回應裡（result_hooks[].output）。
"""
from __future__ import annotations

import platform
from datetime import datetime
from pathlib import Path
from typing import Any

from .collector import collect_failures
from .grouping import group_failures
from .render import render_markdown, render_title
from .settings import Settings
from .store import IndexStore
from .submitters import build_submitters


def _mk_qa_master_version() -> str:
    try:
        from importlib.metadata import version

        return version("mk-qa-master")
    except Exception:  # noqa: BLE001 — 版本只是附帶資訊，查不到就留空
        return ""


def build_environment(event: dict, now: str) -> dict[str, str]:
    """報告「環境」段落的資料。"""
    return {
        "runner": str(event.get("runner") or ""),
        "tool": str(event.get("tool") or ""),
        "os": platform.platform(),
        "python": platform.python_version(),
        "mk_qa_master": _mk_qa_master_version(),
        "project_root": str(event.get("project_root") or ""),
        "reported_at": now,
    }


def _report_mtime(event: dict) -> float | None:
    path = event.get("report_path")
    try:
        return Path(path).stat().st_mtime if path else None
    except OSError:
        return None


def process(event: dict, runner: Any = None, now: str | None = None) -> dict:
    """實際的處理流程。runner / now 可由測試傳入，平常留空即可。"""
    settings = Settings.from_env(event.get("project_root"))
    if not settings.enabled:
        return {"reports": 0, "note": "QA_BUG_REPORT_ENABLED=0，已略過"}

    now = now or datetime.now().isoformat(timespec="seconds")
    store = IndexStore(settings.output_dir)

    # 如果這次執行沒有產生新的 report.json（例如測試根本沒跑起來），
    # 就不要拿舊報告再算一次，否則「出現次數」會灌水。
    mtime = _report_mtime(event)
    if mtime is not None and store.last_report_mtime == mtime:
        return {"reports": 0, "note": "report.json 與上次處理時相同，已略過"}

    failures = collect_failures(runner)
    if not failures:
        if store.existed:
            store.last_report_mtime = mtime
            store.save()
        return {"reports": 0, "note": "沒有失敗的測試"}

    # 某個管道設定有誤（例如 Jira 少了環境變數）時，其他管道照常運作。
    submitters, unavailable = build_submitters(settings)
    reports = group_failures(failures, settings.severity, build_environment(event, now))

    rows: list[dict] = []
    submit_failures: list[dict] = []

    def record_failure(report, row: dict, name: str, error: str) -> None:
        row["submitted"][name] = {"ok": False, "error": error}
        store.record_submit(report, name, False, now, error)
        submit_failures.append({"bug_id": report.bug_id, "submitter": name, "error": error})

    for report in reports:
        store.merge(report, now)
        report.title = render_title(report)
        markdown = render_markdown(report)
        row = {
            "bug_id": report.bug_id,
            "title": report.title,
            "status": "new" if report.is_new else "updated",
            "occurrences": report.occurrences,
            "tests": len(report.failures),
            "devices": report.devices,
            "submitted": {},
        }
        for submitter in submitters:
            # 一個管道失敗不影響其他管道，也不影響其他報告。
            try:
                result = submitter.submit(report, markdown)
            except Exception as e:  # noqa: BLE001
                record_failure(report, row, submitter.name, f"{type(e).__name__}: {e}")
                continue
            if not result.ok:
                record_failure(report, row, submitter.name, result.detail or "送出失敗（未提供原因）")
                continue
            store.set_ref(report, submitter.name, result.ref)
            store.record_submit(report, submitter.name, True, now, dry_run=bool(result.info.get("dry_run")))
            entry = {"ok": True, "ref": result.ref}
            if result.detail:
                entry["detail"] = result.detail
            entry.update(result.info)
            row["submitted"][submitter.name] = entry
        for name, error in unavailable.items():
            record_failure(report, row, name, error)
        rows.append(row)

    store.last_report_mtime = mtime
    store.save()

    summary = {
        "reports": len(rows),
        "new": sum(1 for r in rows if r["status"] == "new"),
        "updated": sum(1 for r in rows if r["status"] == "updated"),
        "failed_tests": len(failures),
        "output_dir": str(settings.output_dir),
        "items": rows,
    }
    if submit_failures:
        # 放在最外層，讓 AI 和使用者一眼看到「哪一份沒送成功」。
        summary["submit_failures"] = submit_failures
    return summary


def on_result(event: dict) -> dict | None:
    """mk-qa-master 的 result hook 入口（登記在 pyproject.toml）。"""
    return process(event)

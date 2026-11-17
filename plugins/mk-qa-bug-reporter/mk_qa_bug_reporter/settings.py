"""設定：全部來自環境變數，每次測試跑完時重新讀一次。

| 環境變數                 | 預設值                 | 用途                      |
|--------------------------|------------------------|---------------------------|
| QA_BUG_REPORT_ENABLED    | 1                      | 設 0 可暫時關閉本插件     |
| QA_BUG_REPORT_SEVERITY   | Medium                 | 每份報告的預設嚴重度      |
| QA_BUG_REPORT_DIR        | <受測專案>/bug-reports | 報告輸出資料夾            |
| QA_BUG_REPORT_SUBMITTERS | file                   | 送出管道，逗號分隔        |
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SEVERITY = "Medium"
DEFAULT_DIR_NAME = "bug-reports"
DEFAULT_SUBMITTERS = ("file",)

_FALSEY = ("0", "false", "no", "off")


@dataclass
class Settings:
    enabled: bool
    severity: str
    output_dir: Path
    submitters: tuple[str, ...]

    @classmethod
    def from_env(cls, project_root: str | os.PathLike | None) -> "Settings":
        root = Path(project_root) if project_root else Path.cwd()
        raw_dir = os.getenv("QA_BUG_REPORT_DIR", "").strip()
        output_dir = Path(raw_dir) if raw_dir else root / DEFAULT_DIR_NAME
        if not output_dir.is_absolute():
            output_dir = root / output_dir
        raw_subs = os.getenv("QA_BUG_REPORT_SUBMITTERS", "").strip()
        submitters = tuple(s.strip().lower() for s in raw_subs.split(",") if s.strip())
        return cls(
            enabled=os.getenv("QA_BUG_REPORT_ENABLED", "1").strip().lower() not in _FALSEY,
            severity=os.getenv("QA_BUG_REPORT_SEVERITY", "").strip() or DEFAULT_SEVERITY,
            output_dir=output_dir,
            submitters=submitters or DEFAULT_SUBMITTERS,
        )

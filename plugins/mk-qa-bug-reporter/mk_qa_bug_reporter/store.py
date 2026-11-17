"""歷史紀錄：記住「哪些 bug 已經開過報告」，讓相同錯誤不會重複開。

資料存在輸出資料夾裡的 `.index.json`。同一個指紋再次出現時，只會把
出現次數 +1、更新最後發生時間，並沿用同一個檔名。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .models import BugReport

INDEX_FILENAME = ".index.json"
INDEX_VERSION = 1


class IndexStore:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.path = self.output_dir / INDEX_FILENAME
        self.data: dict = {"version": INDEX_VERSION, "last_report_mtime": None, "bugs": {}}
        self.existed = self.path.is_file()
        if self.existed:
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("bugs"), dict):
                    self.data.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass  # 索引壞掉就當作沒有歷史、重新開始，不讓插件整個失敗

    @property
    def last_report_mtime(self) -> float | None:
        return self.data.get("last_report_mtime")

    @last_report_mtime.setter
    def last_report_mtime(self, value: float | None) -> None:
        self.data["last_report_mtime"] = value

    def merge(self, report: BugReport, now: str) -> None:
        """把歷史資訊填進 report，並更新索引（尚未寫入磁碟，需再呼叫 save）。"""
        bugs = self.data["bugs"]
        entry = bugs.get(report.fingerprint)
        if entry is None:
            entry = {
                "bug_id": report.bug_id,
                "first_seen": now,
                "last_seen": now,
                "occurrences": 0,
                "tests": [],
                "refs": {},
            }
            bugs[report.fingerprint] = entry
            report.is_new = True
        else:
            report.is_new = False
        current_tests = {f.nodeid for f in report.failures}
        entry["occurrences"] = int(entry.get("occurrences", 0)) + 1
        entry["last_seen"] = now
        entry["summary"] = report.summary
        entry["tests"] = sorted(set(entry.get("tests") or []) | current_tests)

        report.occurrences = entry["occurrences"]
        report.first_seen = entry.get("first_seen") or now
        report.last_seen = now
        report.known_tests = list(entry["tests"])
        report.refs = dict(entry.get("refs") or {})

    def set_ref(self, report: BugReport, submitter_name: str, ref: str) -> None:
        """記下某個送出管道把這份報告放在哪裡（未來 Jira 可用來更新同一張單）。"""
        if not ref:
            return
        self.data["bugs"][report.fingerprint].setdefault("refs", {})[submitter_name] = ref
        report.refs[submitter_name] = ref

    def record_submit(
        self, report: BugReport, submitter_name: str, ok: bool, now: str, error: str = "", dry_run: bool = False
    ) -> None:
        """記下每個管道最近一次送出的結果，方便事後查「哪一份沒送成功」。

        error 必須是已經遮掉機密的文字。dry_run=True 表示只是預覽、沒有真的送出。
        """
        entry = self.data["bugs"][report.fingerprint]
        record: dict = {"ok": ok, "at": now}
        if error:
            record["error"] = error
        if dry_run:
            record["dry_run"] = True
        entry.setdefault("last_submit", {})[submitter_name] = record

    def save(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)  # 先寫暫存檔再換名，避免寫到一半當掉留下壞檔

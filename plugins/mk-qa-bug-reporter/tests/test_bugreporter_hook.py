"""整合測試：hook 把四個步驟串起來，以及和 mk-qa-master 的接合。"""
import json
import os
from importlib.metadata import EntryPoint

from bugreporter_helpers import FakeRunner
from mk_qa_bug_reporter.hook import on_result, process
from mk_qa_bug_reporter.models import SubmitResult
from mk_qa_bug_reporter.store import INDEX_FILENAME
from mk_qa_bug_reporter.submitters import SUBMITTERS, Submitter


def _event(tmp_path, tool="run_tests"):
    return {
        "tool": tool,
        "runner": "pytest-playwright",
        "result": {"exit_code": 1},
        "report_path": str(tmp_path / "report.json"),
        "project_root": str(tmp_path),
    }


def _touch_report(tmp_path, mtime):
    path = tmp_path / "report.json"
    path.write_text("{}", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_process_writes_one_file_per_distinct_error(tmp_path, fake_runner):
    out = process(_event(tmp_path), runner=fake_runner, now="2026-01-01T10:00:00")

    assert out["reports"] == 2 and out["new"] == 2 and out["updated"] == 0
    assert out["failed_tests"] == 3
    files = sorted(p.name for p in (tmp_path / "bug-reports").glob("*.md"))
    assert files == sorted(f"{item['bug_id']}.md" for item in out["items"])
    merged = out["items"][0]
    assert merged["tests"] == 2
    assert merged["submitted"]["file"]["ok"] is True
    text = (tmp_path / "bug-reports" / f"{merged['bug_id']}.md").read_text(encoding="utf-8")
    assert "- Runner：pytest-playwright" in text
    assert "- 觸發工具：run_tests" in text
    assert "- 報告時間：2026-01-01T10:00:00" in text


def test_second_run_updates_instead_of_duplicating(tmp_path, fake_runner):
    _touch_report(tmp_path, 1_000)
    process(_event(tmp_path), runner=fake_runner, now="2026-01-01T10:00:00")
    _touch_report(tmp_path, 2_000)
    out = process(_event(tmp_path, "run_failed"), runner=fake_runner, now="2026-01-02T10:00:00")

    assert out["new"] == 0 and out["updated"] == 2
    assert len(list((tmp_path / "bug-reports").glob("*.md"))) == 2
    text = (tmp_path / "bug-reports" / f"{out['items'][0]['bug_id']}.md").read_text(encoding="utf-8")
    assert "2 次（首次 2026-01-01T10:00:00，最近 2026-01-02T10:00:00）" in text


def test_stale_report_is_not_counted_twice(tmp_path, fake_runner):
    _touch_report(tmp_path, 1_000)
    process(_event(tmp_path), runner=fake_runner, now="t1")
    out = process(_event(tmp_path), runner=fake_runner, now="t2")   # report.json 沒變

    assert out["reports"] == 0 and "相同" in out["note"]
    index = json.loads((tmp_path / "bug-reports" / INDEX_FILENAME).read_text(encoding="utf-8"))
    assert all(b["occurrences"] == 1 for b in index["bugs"].values())


def test_no_failures_creates_nothing(tmp_path):
    out = process(_event(tmp_path), runner=FakeRunner())
    assert out == {"reports": 0, "note": "沒有失敗的測試"}
    assert not (tmp_path / "bug-reports").exists()


def test_disabled_by_env(tmp_path, fake_runner, monkeypatch):
    monkeypatch.setenv("QA_BUG_REPORT_ENABLED", "0")
    out = process(_event(tmp_path), runner=fake_runner)
    assert out["reports"] == 0
    assert not (tmp_path / "bug-reports").exists()


def test_severity_and_dir_from_env(tmp_path, fake_runner, monkeypatch):
    monkeypatch.setenv("QA_BUG_REPORT_SEVERITY", "High")
    monkeypatch.setenv("QA_BUG_REPORT_DIR", str(tmp_path / "elsewhere"))
    out = process(_event(tmp_path), runner=fake_runner)
    md = next((tmp_path / "elsewhere").glob("*.md")).read_text(encoding="utf-8")
    assert "| 嚴重度 | High |" in md
    assert out["output_dir"] == str(tmp_path / "elsewhere")


def test_one_failing_submitter_does_not_block_file_output(tmp_path, fake_runner, monkeypatch):
    class Broken(Submitter):
        name = "broken"

        def submit(self, report, markdown):
            raise RuntimeError("network down")

    class Refuses(Submitter):
        name = "refuses"

        def submit(self, report, markdown):
            return SubmitResult(ok=False, detail="quota exceeded")

    monkeypatch.setitem(SUBMITTERS, "broken", Broken)
    monkeypatch.setitem(SUBMITTERS, "refuses", Refuses)
    monkeypatch.setenv("QA_BUG_REPORT_SUBMITTERS", "broken,refuses,file")
    out = process(_event(tmp_path), runner=fake_runner)

    submitted = out["items"][0]["submitted"]
    assert submitted["broken"] == {"ok": False, "error": "RuntimeError: network down"}
    assert submitted["refuses"] == {"ok": False, "error": "quota exceeded"}
    assert submitted["file"]["ok"] is True
    assert len(list((tmp_path / "bug-reports").glob("*.md"))) == 2


def test_on_result_uses_the_active_runner(tmp_path, fake_runner, monkeypatch):
    """不傳 runner 時，會向 mk-qa-master 目前的 runner 要資料。"""
    monkeypatch.setattr("mk_qa_master.runners.get_runner", lambda: fake_runner)
    out = on_result(_event(tmp_path))
    assert out["reports"] == 2


def test_loads_through_mk_qa_master_plugin_discovery(tmp_path, fake_runner, monkeypatch):
    """用 mk-qa-master 真正的插件載入器與 run_result_hooks 走一遍。"""
    from mk_qa_master import plugins

    monkeypatch.setenv("MK_QA_PLUGINS", "1")
    ep = EntryPoint("bug_reporter", "mk_qa_bug_reporter.hook:on_result", plugins.GROUP_RESULT_HOOKS)
    state = plugins.discover(eps_for=lambda group: [ep] if group == plugins.GROUP_RESULT_HOOKS else [])
    assert state.errors == []
    assert [name for name, _ in state.result_hooks] == ["bug_reporter"]

    monkeypatch.setattr("mk_qa_master.runners.get_runner", lambda: fake_runner)
    monkeypatch.setattr(plugins, "_STATE", state)
    rows = plugins.run_result_hooks(_event(tmp_path))
    assert rows[0]["hook"] == "bug_reporter" and rows[0]["ok"] is True
    assert rows[0]["output"]["reports"] == 2
    json.dumps(rows, ensure_ascii=False)   # 回傳值必須能被 server 轉成 JSON

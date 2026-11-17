"""各步驟的單元測試：collector / grouping / store / render / submitters / settings。"""
import json
from pathlib import Path

import pytest

from bugreporter_helpers import PYTEST_TIMEOUT_MESSAGE, PYTEST_TITLE_MESSAGE, FakeRunner
from mk_qa_bug_reporter.collector import collect_failures
from mk_qa_bug_reporter.grouping import (
    fingerprint_of,
    group_failures,
    normalize_error,
    summarize_error,
)
from mk_qa_bug_reporter.models import Failure, SubmitResult
from mk_qa_bug_reporter.render import SECTION_ORDER, render_markdown, render_title
from mk_qa_bug_reporter.settings import Settings
from mk_qa_bug_reporter.store import INDEX_FILENAME, IndexStore
from mk_qa_bug_reporter.submitters import SUBMITTERS, FileSubmitter, Submitter, make_submitters


# ---- collector --------------------------------------------------------------

def test_collect_keeps_only_failed_tests(fake_runner):
    failures = collect_failures(fake_runner)
    assert [f.short_name for f in failures] == [
        "test_login_with_password",
        "test_login_remember_me",
        "test_page_title",
    ]
    first = failures[0]
    assert first.title == "輸入帳密後按「登入」應進入首頁"
    assert first.screenshot.endswith("test-failed-1.png")
    assert len(first.steps) == 2


def test_collect_includes_setup_errors():
    runner = FakeRunner(details=[{"nodeid": "t.py::test_a", "outcome": "error", "message": ""}])
    assert [f.nodeid for f in collect_failures(runner)] == ["t.py::test_a"]


def test_collect_falls_back_to_failure_details():
    """jest / cypress / go 沒有 get_all_test_details 的資料，只有失敗清單。"""
    runner = FakeRunner(
        details=[],
        failure_details=[{"nodeid": "a.test.js::adds", "message": "Error: boom", "duration": 3}],
    )
    failures = collect_failures(runner)
    assert len(failures) == 1
    assert failures[0].message == "Error: boom"
    assert failures[0].screenshot is None


def test_collect_skips_error_rows_and_duplicates():
    runner = FakeRunner(
        failure_details=[
            {"error": "找不到報告"},
            {"nodeid": "t.py::test_a", "message": "x"},
            {"nodeid": "t.py::test_a", "message": "x"},
        ]
    )
    assert len(collect_failures(runner)) == 1


# ---- grouping ---------------------------------------------------------------

def test_same_error_at_different_lines_shares_fingerprint():
    a = Failure("t.py::test_a", PYTEST_TIMEOUT_MESSAGE.format(line=12))
    b = Failure("t.py::test_b", PYTEST_TIMEOUT_MESSAGE.format(line=99))
    assert fingerprint_of(a)[0] == fingerprint_of(b)[0]


def test_retry_counts_do_not_change_fingerprint():
    a = Failure("t.py::test_a", PYTEST_TITLE_MESSAGE.format(retries=9))
    b = Failure("t.py::test_a", PYTEST_TITLE_MESSAGE.format(retries=4))
    assert fingerprint_of(a)[0] == fingerprint_of(b)[0]


def test_page_snapshot_does_not_change_fingerprint():
    base = PYTEST_TITLE_MESSAGE.format(retries=9)
    snapshot = "E       Aria snapshot:\nE       - button \"{label}\"\n"
    a = Failure("t.py::test_a", base + snapshot.format(label="Sign in"))
    b = Failure("t.py::test_a", base + snapshot.format(label="Log in"))
    assert fingerprint_of(a)[0] == fingerprint_of(b)[0] == fingerprint_of(Failure("t.py::test_a", base))[0]


def test_different_errors_get_different_fingerprints():
    a = Failure("t.py::test_a", PYTEST_TIMEOUT_MESSAGE.format(line=1))
    b = Failure("t.py::test_b", PYTEST_TITLE_MESSAGE.format(retries=9))
    assert fingerprint_of(a)[0] != fingerprint_of(b)[0]


def test_normalize_uses_only_pytest_error_lines():
    signature = normalize_error(PYTEST_TIMEOUT_MESSAGE.format(line=12))
    assert signature.startswith("playwright._impl._errors.TimeoutError")
    assert "def click_login" not in signature
    assert 'waiting for get_by_role("button", name="登入")' in signature


def test_non_pytest_message_drops_stack_frames():
    msg = "Error: expected 1 to be 2\n    at Object.<anonymous> (a.test.js:12:5)\n    at run (x.js:3:1)"
    assert normalize_error(msg) == "Error: expected 1 to be 2"
    assert summarize_error(msg) == "Error: expected 1 to be 2"


def test_empty_messages_are_not_merged_together():
    a = Failure("t.py::test_a", "")
    b = Failure("t.py::test_b", "")
    assert fingerprint_of(a)[0] != fingerprint_of(b)[0]
    assert summarize_error("") == "（runner 未提供錯誤訊息）"


def test_group_failures_merges_identical_errors(fake_runner):
    reports = group_failures(collect_failures(fake_runner), severity="High", environment={"runner": "x"})
    assert len(reports) == 2
    merged, single = reports
    assert [f.short_name for f in merged.failures] == ["test_login_with_password", "test_login_remember_me"]
    assert len(single.failures) == 1
    assert merged.bug_id == f"BUG-{merged.fingerprint}"
    assert merged.severity == "High"
    assert merged.environment == {"runner": "x"}


# ---- store ------------------------------------------------------------------

def test_store_counts_occurrences_across_runs(tmp_path, fake_runner):
    report = group_failures(collect_failures(fake_runner))[0]

    store = IndexStore(tmp_path)
    store.merge(report, "2026-01-01T10:00:00")
    store.save()
    assert report.is_new is True
    assert report.occurrences == 1

    again = group_failures(collect_failures(fake_runner))[0]
    again.failures = again.failures[:1]          # 第二次只有一個測試失敗
    store2 = IndexStore(tmp_path)
    store2.merge(again, "2026-01-02T10:00:00")
    assert again.is_new is False
    assert again.occurrences == 2
    assert again.first_seen == "2026-01-01T10:00:00"
    assert again.last_seen == "2026-01-02T10:00:00"
    assert len(again.known_tests) == 2           # 歷來受影響的測試仍記得兩個


def test_store_remembers_refs(tmp_path, fake_runner):
    report = group_failures(collect_failures(fake_runner))[0]
    store = IndexStore(tmp_path)
    store.merge(report, "t1")
    store.set_ref(report, "jira", "QA-123")
    store.save()

    again = group_failures(collect_failures(fake_runner))[0]
    IndexStore(tmp_path).merge(again, "t2")
    assert again.refs == {"jira": "QA-123"}


def test_store_survives_corrupt_index(tmp_path):
    (tmp_path / INDEX_FILENAME).write_text("{not json", encoding="utf-8")
    store = IndexStore(tmp_path)
    assert store.data["bugs"] == {}


# ---- render -----------------------------------------------------------------

@pytest.fixture
def rendered(fake_runner, tmp_path):
    env = {"runner": "pytest-playwright", "os": "TestOS", "python": "3.12", "project_root": "/proj"}
    report = group_failures(collect_failures(fake_runner), "Medium", env)[0]
    IndexStore(tmp_path).merge(report, "2026-01-01T10:00:00")
    report.title = render_title(report)
    return report, render_markdown(report)


def test_title_names_first_test_and_count(rendered):
    report, _ = rendered
    assert report.title.startswith("[test_login_with_password] playwright._impl._errors.TimeoutError")
    assert report.title.endswith("（共 2 個測試）")


def test_markdown_has_every_required_section(rendered):
    report, md = rendered
    assert md.startswith(f"# {report.title}\n")
    for heading in ("## 環境", "## 重現步驟", "## 預期結果", "## 實際結果", "## 錯誤訊息", "## 截圖／Trace／影片"):
        assert heading in md
    assert "| 嚴重度 | Medium |" in md
    assert f"| Bug ID | {report.bug_id} |" in md


def test_markdown_content(rendered):
    _, md = rendered
    assert '`pytest "tests/test_login.py::test_login_with_password"`' in md
    assert "`Locator.click` Click get_by_role" in md                    # 重現步驟取自 trace
    assert "輸入帳密後按「登入」應進入首頁" in md                        # 預期結果取自 docstring
    assert "2 個測試以相同的錯誤失敗" in md
    assert "```text\n" in md and "E       Call log:" in md
    assert "截圖：`/proj/test-results/a/test-failed-1.png`" in md
    assert "影片：無" in md                                             # 第二個測試沒有附件
    assert "`tests/test_login.py::test_login_remember_me`" in md


def test_markdown_without_steps_or_docstring():
    report = group_failures([Failure("a.test.js::adds", "Error: boom")], environment={"runner": "jest"})[0]
    md = render_markdown(report)
    assert "以 `jest` 執行測試 `a.test.js::adds`" in md
    assert "未提供逐步操作紀錄" in md
    assert "測試 `adds` 應通過" in md


def test_code_fence_in_message_is_neutralised():
    report = group_failures([Failure("t.py::test_a", "E   boom ``` end")])[0]
    assert render_markdown(report).count("```") == 2


def test_section_order_is_configurable(monkeypatch, rendered):
    report, _ = rendered
    monkeypatch.setattr("mk_qa_bug_reporter.render.SECTION_ORDER", ["error"])
    md = render_markdown(report)
    assert "## 錯誤訊息" in md and "## 環境" not in md
    assert "summary" in SECTION_ORDER


# ---- submitters / settings --------------------------------------------------

def test_file_submitter_writes_markdown(tmp_path, rendered):
    report, md = rendered
    result = FileSubmitter(tmp_path / "out").submit(report, md)
    assert result.ok
    path = Path(result.ref)
    assert path.name == f"{report.bug_id}.md"
    assert path.read_text(encoding="utf-8") == md


def test_submitter_interface_can_be_extended(tmp_path, monkeypatch, rendered):
    """確認「以後加 Jira」的路徑可行：新增類別 + 登記名稱即可。"""
    report, md = rendered
    sent = []

    class FakeJira(Submitter):
        name = "jira"

        def submit(self, report, markdown):
            sent.append((report.title, markdown))
            return SubmitResult(ok=True, ref="QA-1")

    monkeypatch.setitem(SUBMITTERS, "jira", FakeJira)
    monkeypatch.setenv("QA_BUG_REPORT_SUBMITTERS", "file, jira")
    submitters = make_submitters(Settings.from_env(tmp_path))
    assert [s.name for s in submitters] == ["file", "jira"]
    assert submitters[1].submit(report, md).ref == "QA-1"
    assert sent[0][0] == report.title


def test_unknown_submitter_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_BUG_REPORT_SUBMITTERS", "jira")
    with pytest.raises(ValueError, match="未知的送出管道"):
        make_submitters(Settings.from_env(tmp_path))


def test_settings_defaults_and_overrides(tmp_path, monkeypatch):
    s = Settings.from_env(tmp_path)
    assert (s.enabled, s.severity, s.submitters) == (True, "Medium", ("file",))
    assert s.output_dir == tmp_path / "bug-reports"

    monkeypatch.setenv("QA_BUG_REPORT_SEVERITY", "Critical")
    monkeypatch.setenv("QA_BUG_REPORT_DIR", "qa/bugs")
    monkeypatch.setenv("QA_BUG_REPORT_ENABLED", "0")
    s = Settings.from_env(tmp_path)
    assert (s.enabled, s.severity) == (False, "Critical")
    assert s.output_dir == tmp_path / "qa" / "bugs"


def test_index_is_valid_json(tmp_path, fake_runner):
    report = group_failures(collect_failures(fake_runner))[0]
    store = IndexStore(tmp_path)
    store.merge(report, "t")
    store.save()
    data = json.loads((tmp_path / INDEX_FILENAME).read_text(encoding="utf-8"))
    assert data["bugs"][report.fingerprint]["occurrences"] == 1

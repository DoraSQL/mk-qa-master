"""JiraSubmitter 的測試。全部使用假的 Jira（FakeJira），不會連到任何真實服務。"""
import base64
import json

import pytest

from bugreporter_helpers import FakeRunner
from mk_qa_bug_reporter import jira as jira_module
from mk_qa_bug_reporter.adf import markdown_to_adf
from mk_qa_bug_reporter.grouping import group_failures
from mk_qa_bug_reporter.hook import process
from mk_qa_bug_reporter.jira import JiraClient, JiraConfig, JiraError, JiraSubmitter, mask_email, redact
from mk_qa_bug_reporter.models import Failure
from mk_qa_bug_reporter.render import render_markdown, render_title
from mk_qa_bug_reporter.settings import Settings
from mk_qa_bug_reporter.store import INDEX_FILENAME, IndexStore
from mk_qa_bug_reporter.submitters import SUBMITTERS, build_submitters, make_submitters

TOKEN = "fake-token-for-tests-0123456789"
EMAIL = "dora@example.com"
BASE_URL = "https://example.atlassian.net"
BASIC = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()


# ---- 假的 Jira --------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code, data=None, text=""):
        self.status_code = status_code
        self._data = data
        self.text = text

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


class FakeJira:
    """取代 requests.request。記錄每次呼叫，並依序回傳預先排好的回應。"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.next_key = 101

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.responses:
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if url.endswith("/comment"):
            return FakeResponse(201, {"id": "9001"})
        key = f"QA-{self.next_key}"
        self.next_key += 1
        return FakeResponse(201, {"id": "1", "key": key, "self": f"{BASE_URL}/rest/api/3/issue/1"})


@pytest.fixture
def jira_env(monkeypatch):
    for name in list(jira_module.__dict__):
        if name.startswith("ENV_"):
            monkeypatch.delenv(getattr(jira_module, name), raising=False)
    monkeypatch.setenv("QA_BUG_REPORT_JIRA_URL", BASE_URL + "/")
    monkeypatch.setenv("QA_BUG_REPORT_JIRA_EMAIL", EMAIL)
    monkeypatch.setenv("QA_BUG_REPORT_JIRA_API_TOKEN", TOKEN)
    monkeypatch.setenv("QA_BUG_REPORT_JIRA_PROJECT", "QA")
    monkeypatch.setenv("QA_BUG_REPORT_SUBMITTERS", "file,jira")


@pytest.fixture
def fake_jira(monkeypatch):
    """讓 JiraClient 預設使用假的 Jira，而不是 requests。"""
    fake = FakeJira()
    original = JiraClient.__init__

    def patched(self, config, http=None):
        original(self, config, http or fake)

    monkeypatch.setattr(JiraClient, "__init__", patched)
    return fake


def _config(**overrides):
    values = dict(base_url=BASE_URL, email=EMAIL, token=TOKEN, project="QA")
    values.update(overrides)
    return JiraConfig(**values)


def _report(tmp_path=None, refs=None):
    failures = [
        Failure("t.py::test_scroll[iPhone 15-chromium]", "E   AssertionError: 太寬\nE   assert 800 <= 393\n"),
        Failure("t.py::test_scroll[Pixel 7-chromium]", "E   AssertionError: 太寬\nE   assert 801 <= 412\n"),
    ]
    report = group_failures(failures, "Medium", {"runner": "pytest-playwright"})[0]
    report.last_seen = "2026-01-02T10:00:00"
    report.occurrences = 2
    report.refs = dict(refs or {})
    report.title = render_title(report)
    return report, render_markdown(report)


def _event(tmp_path):
    return {"tool": "run_tests", "runner": "pytest-playwright", "result": {"exit_code": 1},
            "report_path": str(tmp_path / "report.json"), "project_root": str(tmp_path)}


def _everything_written(tmp_path):
    """輸出資料夾裡所有檔案的內容，用來檢查有沒有洩漏。"""
    return "\n".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*") if p.is_file())


def _assert_no_secret(*texts):
    for text in texts:
        blob = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
        assert TOKEN not in blob
        assert BASIC not in blob


# ---- 設定 -------------------------------------------------------------------

def test_config_from_env(jira_env):
    config = JiraConfig.from_env()
    assert config.base_url == BASE_URL                 # 結尾的斜線會被去掉
    assert (config.email, config.project, config.issue_type) == (EMAIL, "QA", "Bug")
    assert config.labels == ("mk-qa-bug-reporter",)
    assert config.dry_run is False and config.timeout == 15.0
    assert config.problems() == []


def test_config_optional_settings(jira_env, monkeypatch):
    monkeypatch.setenv("QA_BUG_REPORT_JIRA_ISSUE_TYPE", "Task")
    monkeypatch.setenv("QA_BUG_REPORT_JIRA_LABELS", "qa team, mobile")
    monkeypatch.setenv("QA_BUG_REPORT_JIRA_DRY_RUN", "1")
    monkeypatch.setenv("QA_BUG_REPORT_JIRA_TIMEOUT", "abc")
    config = JiraConfig.from_env()
    assert config.issue_type == "Task"
    assert config.labels == ("qa-team", "mobile")       # 標籤不能有空白
    assert config.dry_run is True and config.timeout == 15.0


def test_labels_can_be_disabled(jira_env, monkeypatch):
    monkeypatch.setenv("QA_BUG_REPORT_JIRA_LABELS", "none")
    assert JiraConfig.from_env().labels == ()


def test_problems_name_variables_but_never_values(jira_env, monkeypatch):
    monkeypatch.delenv("QA_BUG_REPORT_JIRA_PROJECT")
    monkeypatch.setenv("QA_BUG_REPORT_JIRA_URL", "http://example.atlassian.net")
    problems = JiraConfig.from_env().problems()
    assert any("QA_BUG_REPORT_JIRA_PROJECT" in p for p in problems)
    assert any("https://" in p for p in problems)
    _assert_no_secret(problems)


def test_incomplete_config_is_rejected_unless_dry_run(jira_env, monkeypatch, tmp_path):
    monkeypatch.delenv("QA_BUG_REPORT_JIRA_API_TOKEN")
    with pytest.raises(ValueError, match="QA_BUG_REPORT_JIRA_API_TOKEN"):
        JiraSubmitter.from_settings(Settings.from_env(tmp_path))
    monkeypatch.setenv("QA_BUG_REPORT_JIRA_DRY_RUN", "1")
    assert JiraSubmitter.from_settings(Settings.from_env(tmp_path)).config.dry_run is True


def test_jira_is_registered(jira_env, tmp_path):
    assert SUBMITTERS["jira"] is JiraSubmitter
    assert [s.name for s in make_submitters(Settings.from_env(tmp_path))] == ["file", "jira"]


# ---- token 不外洩 -----------------------------------------------------------

def test_repr_never_shows_token():
    config = _config()
    submitter = JiraSubmitter(config, "out", JiraClient(config, FakeJira()))
    _assert_no_secret(repr(config), str(config), repr(submitter.client), repr(vars(submitter.client)["_config"]))


def test_redact_and_mask_email():
    config = _config()
    assert redact(f"token={TOKEN} header=Basic {BASIC}", config.secrets) == "token=*** header=Basic ***"
    assert mask_email(EMAIL) == "do***@example.com"
    assert mask_email("") == ""


def test_token_is_only_sent_as_basic_auth():
    fake = FakeJira()
    report, md = _report()
    JiraSubmitter(_config(), "out", JiraClient(_config(), fake)).submit(report, md)
    call = fake.calls[0]
    assert call["auth"] == (EMAIL, TOKEN)
    assert call["url"].startswith(BASE_URL) and TOKEN not in call["url"]
    _assert_no_secret(call["json"], call["headers"])
    assert call["allow_redirects"] is False and call["timeout"] == 15.0


# ---- 建立 issue -------------------------------------------------------------

def test_first_occurrence_creates_issue():
    fake = FakeJira()
    report, md = _report()
    result = JiraSubmitter(_config(), "out", JiraClient(_config(), fake)).submit(report, md)

    assert result.ok and result.ref == "QA-101"
    assert result.info == {"action": "created", "url": f"{BASE_URL}/browse/QA-101"}
    call = fake.calls[0]
    assert (call["method"], call["url"]) == ("POST", f"{BASE_URL}/rest/api/3/issue")
    fields = call["json"]["fields"]
    assert fields["project"] == {"key": "QA"}
    assert fields["issuetype"] == {"name": "Bug"}
    assert fields["summary"] == report.title
    assert fields["labels"] == ["mk-qa-bug-reporter", f"bug-{report.fingerprint}"]
    assert fields["description"]["type"] == "doc" and fields["description"]["version"] == 1


def test_summary_is_single_line_and_capped():
    fake = FakeJira()
    report, md = _report()
    report.title = "很長的標題\n第二行 " + "x" * 400
    JiraSubmitter(_config(), "out", JiraClient(_config(), fake)).submit(report, md)
    summary = fake.calls[0]["json"]["fields"]["summary"]
    assert "\n" not in summary and len(summary) == 255


def test_labels_omitted_when_disabled():
    fake = FakeJira()
    report, md = _report()
    JiraSubmitter(_config(labels=()), "out", JiraClient(_config(labels=()), fake)).submit(report, md)
    assert "labels" not in fake.calls[0]["json"]["fields"]


# ---- 再次出現：留言而不是重開 -----------------------------------------------

def test_known_bug_gets_a_comment_instead_of_a_new_issue():
    fake = FakeJira()
    report, md = _report(refs={"jira": "QA-7"})
    result = JiraSubmitter(_config(), "out", JiraClient(_config(), fake)).submit(report, md)

    assert result.ok and result.ref == "QA-7" and result.info["action"] == "commented"
    assert len(fake.calls) == 1
    assert fake.calls[0]["url"] == f"{BASE_URL}/rest/api/3/issue/QA-7/comment"
    text = json.dumps(fake.calls[0]["json"]["body"], ensure_ascii=False)
    assert "第 2 次" in text and report.bug_id in text
    assert "iPhone 15、Pixel 7" in text and "test_scroll[Pixel 7-chromium]" in text


def test_deleted_issue_falls_back_to_creating_a_new_one():
    fake = FakeJira(FakeResponse(404, {"errorMessages": ["Issue does not exist"]}))
    report, md = _report(refs={"jira": "QA-7"})
    result = JiraSubmitter(_config(), "out", JiraClient(_config(), fake)).submit(report, md)

    assert result.ok and result.ref == "QA-101"
    assert "QA-7" in result.detail and result.info["action"] == "created"
    assert [c["url"].rsplit("/", 1)[-1] for c in fake.calls] == ["comment", "issue"]


def test_comment_failure_other_than_404_does_not_create_duplicate():
    fake = FakeJira(FakeResponse(500, {}))
    report, md = _report(refs={"jira": "QA-7"})
    result = JiraSubmitter(_config(), "out", JiraClient(_config(), fake)).submit(report, md)
    assert not result.ok and "HTTP 500" in result.detail
    assert len(fake.calls) == 1


# ---- 錯誤處理 ---------------------------------------------------------------

@pytest.mark.parametrize(
    "response, expected",
    [
        (FakeResponse(401, {"errorMessages": ["Client must be authenticated"]}), "帳號或 API token 不正確"),
        (FakeResponse(403, {}), "沒有權限"),
        (FakeResponse(400, {"errors": {"issuetype": "Specify a valid issue type"}}), "issuetype: Specify a valid issue type"),
        (FakeResponse(502, None, "<html>Bad Gateway</html>"), "HTTP 502"),
        (FakeResponse(201, {"id": "1"}), "沒有 issue 編號"),
        (ConnectionError("Failed to resolve 'example.atlassian.net'"), "連不上 Jira（ConnectionError）"),
        (TimeoutError("timed out"), "連不上 Jira（TimeoutError）"),
    ],
)
def test_errors_become_failed_results_not_exceptions(response, expected):
    report, md = _report()
    result = JiraSubmitter(_config(), "out", JiraClient(_config(), FakeJira(response))).submit(report, md)
    assert result.ok is False and result.ref == ""
    assert expected in result.detail


def test_error_text_from_jira_or_network_is_redacted():
    """就算 Jira 的回應或例外訊息裡出現 token，也不會被帶出去。"""
    leaky = [
        FakeResponse(400, {"errorMessages": [f"bad header Basic {BASIC}"], "errors": {"auth": TOKEN}}),
        ConnectionError(f"proxy rejected Authorization: Basic {BASIC} token {TOKEN}"),
        RuntimeError(f"boom {TOKEN}"),
    ]
    for item in leaky:
        report, md = _report()
        result = JiraSubmitter(_config(), "out", JiraClient(_config(), FakeJira(item))).submit(report, md)
        assert result.ok is False
        _assert_no_secret(result.detail, result.info)
        assert "***" in result.detail


def test_client_raises_jira_error_with_status():
    client = JiraClient(_config(), FakeJira(FakeResponse(404, {})))
    with pytest.raises(JiraError) as excinfo:
        client.add_comment("QA-1", {})
    assert excinfo.value.status == 404
    _assert_no_secret(str(excinfo.value))


# ---- dry-run ----------------------------------------------------------------

def test_dry_run_sends_nothing_and_writes_preview(tmp_path):
    fake = FakeJira()
    config = _config(dry_run=True)
    report, md = _report()
    result = JiraSubmitter(config, tmp_path, JiraClient(config, fake)).submit(report, md)

    assert fake.calls == []
    assert result.ok and result.ref == ""               # 不能記成已開單
    assert "dry-run" in result.detail and "沒有真的送出" in result.detail
    assert result.info["dry_run"] is True and result.info["action"] == "create_issue"
    assert result.info["url"] == f"{BASE_URL}/rest/api/3/issue"
    assert result.info["summary"] == report.title
    assert "do***@example.com" in result.info["auth"]

    preview_path = tmp_path / "jira-dry-run" / f"{report.bug_id}.json"
    assert result.info["preview_file"] == str(preview_path)
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    assert preview["payload"]["fields"]["project"] == {"key": "QA"}
    _assert_no_secret(result.info, result.detail, preview_path.read_text(encoding="utf-8"))
    assert EMAIL not in preview_path.read_text(encoding="utf-8")


def test_dry_run_for_known_bug_previews_a_comment(tmp_path):
    config = _config(dry_run=True)
    report, md = _report(refs={"jira": "QA-7"})
    result = JiraSubmitter(config, tmp_path, JiraClient(config, FakeJira())).submit(report, md)
    assert result.info["action"] == "add_comment"
    assert result.info["url"].endswith("/issue/QA-7/comment")
    assert "QA-7" in result.detail


def test_dry_run_with_missing_settings_lists_problems(tmp_path):
    config = JiraConfig(dry_run=True)
    report, md = _report()
    result = JiraSubmitter(config, tmp_path, JiraClient(config, FakeJira())).submit(report, md)
    assert result.ok
    assert len(result.info["problems"]) == 4
    assert "未設定" in result.info["url"]


# ---- Markdown → ADF ---------------------------------------------------------

def _types(nodes):
    return [n["type"] for n in nodes]


def _walk(node):
    yield node
    for child in node.get("content", []) if isinstance(node, dict) else []:
        yield from _walk(child)


def test_adf_structure_of_a_real_report():
    _, md = _report()
    doc = markdown_to_adf(md)
    assert (doc["type"], doc["version"]) == ("doc", 1)
    top = doc["content"]
    assert top[0]["type"] == "bulletList"               # 摘要表 → 條列；大標題已略過
    first_item = top[0]["content"][0]["content"][0]["content"][0]["text"]
    assert first_item.startswith("Bug ID：BUG-")
    headings = [n["content"][0]["text"] for n in top if n["type"] == "heading"]
    assert headings == ["環境", "重現步驟", "預期結果", "實際結果", "錯誤訊息", "截圖／Trace／影片", "受影響的測試"]
    assert all(n["attrs"]["level"] == 2 for n in top if n["type"] == "heading")
    assert "orderedList" in _types(top) and "codeBlock" in _types(top)
    code = next(n for n in top if n["type"] == "codeBlock")
    assert code["attrs"] == {"language": "text"} and "assert 800 <= 393" in code["content"][0]["text"]


def test_adf_never_contains_empty_text_nodes():
    _, md = _report()
    for node in _walk(markdown_to_adf(md + "\n``\n\n- \n\n## \n")):
        if node.get("type") == "text":
            assert node["text"] != ""
        if node.get("type") in ("bulletList", "orderedList"):
            assert node["content"], "清單不能是空的"


def test_adf_inline_code_and_nested_list():
    doc = markdown_to_adf("# 標題\n\n1. 第一步 `pytest x`\n   - 子項目\n2. 第二步\n\n一般文字\n")
    ordered = doc["content"][0]
    assert ordered["type"] == "orderedList" and len(ordered["content"]) == 2
    first = ordered["content"][0]["content"]
    assert first[0]["content"][1] == {"type": "text", "text": "pytest x", "marks": [{"type": "code"}]}
    assert first[1]["type"] == "bulletList"
    assert first[1]["content"][0]["content"][0]["content"][0]["text"] == "子項目"
    assert doc["content"][1] == {"type": "paragraph", "content": [{"type": "text", "text": "一般文字"}]}


def test_adf_keeps_first_heading_when_asked():
    doc = markdown_to_adf("# 標題\n", skip_first_heading=False)
    assert doc["content"][0] == {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "標題"}]}
    assert markdown_to_adf("")["content"][0]["type"] == "paragraph"


# ---- 整條流程（hook） -------------------------------------------------------

DETAILS = [
    {"nodeid": "t.py::test_scroll[iPhone 15-chromium]", "outcome": "failed",
     "message": "E   AssertionError: 太寬\nE   assert 800 <= 393\n"},
    {"nodeid": "t.py::test_scroll[Pixel 7-chromium]", "outcome": "failed",
     "message": "E   AssertionError: 太寬\nE   assert 801 <= 412\n"},
    {"nodeid": "t.py::test_login[chromium]", "outcome": "failed", "message": "E   Error: 找不到登入按鈕\n"},
]


def test_hook_creates_then_comments(tmp_path, jira_env, fake_jira):
    runner = FakeRunner(details=DETAILS)
    first = process(_event(tmp_path), runner=runner, now="2026-01-01T10:00:00")

    assert first["reports"] == 2 and "submit_failures" not in first
    keys = [item["submitted"]["jira"]["ref"] for item in first["items"]]
    assert keys == ["QA-101", "QA-102"]
    assert all(item["submitted"]["jira"]["action"] == "created" for item in first["items"])
    assert all(item["submitted"]["file"]["ok"] for item in first["items"])
    assert len(fake_jira.calls) == 2

    index = json.loads((tmp_path / "bug-reports" / INDEX_FILENAME).read_text(encoding="utf-8"))
    assert sorted(b["refs"]["jira"] for b in index["bugs"].values()) == ["QA-101", "QA-102"]
    assert all(b["last_submit"]["jira"] == {"ok": True, "at": "2026-01-01T10:00:00"} for b in index["bugs"].values())

    second = process(_event(tmp_path), runner=runner, now="2026-01-02T10:00:00")
    assert second["new"] == 0 and second["updated"] == 2
    assert [item["submitted"]["jira"]["action"] for item in second["items"]] == ["commented", "commented"]
    assert [item["submitted"]["jira"]["ref"] for item in second["items"]] == keys
    urls = [c["url"] for c in fake_jira.calls[2:]]
    assert urls == [f"{BASE_URL}/rest/api/3/issue/QA-101/comment", f"{BASE_URL}/rest/api/3/issue/QA-102/comment"]

    _assert_no_secret(first, second, _everything_written(tmp_path))


def test_hook_survives_jira_outage_and_records_what_failed(tmp_path, jira_env, fake_jira):
    fake_jira.responses = [ConnectionError(f"cannot connect {TOKEN}"), FakeResponse(401, {})]
    out = process(_event(tmp_path), runner=FakeRunner(details=DETAILS), now="2026-01-01T10:00:00")

    # 檔案報告照常產生
    assert out["reports"] == 2
    assert len(list((tmp_path / "bug-reports").glob("*.md"))) == 2
    assert all(item["submitted"]["file"]["ok"] for item in out["items"])
    # 哪一份沒送成功，寫得清清楚楚
    assert [f["submitter"] for f in out["submit_failures"]] == ["jira", "jira"]
    assert [f["bug_id"] for f in out["submit_failures"]] == [item["bug_id"] for item in out["items"]]
    assert "連不上 Jira" in out["submit_failures"][0]["error"]
    assert "HTTP 401" in out["submit_failures"][1]["error"]
    index = json.loads((tmp_path / "bug-reports" / INDEX_FILENAME).read_text(encoding="utf-8"))
    for bug in index["bugs"].values():
        assert bug["last_submit"]["jira"]["ok"] is False and bug["last_submit"]["jira"]["error"]
        assert "jira" not in bug["refs"]
    _assert_no_secret(out, _everything_written(tmp_path))

    # Jira 恢復後，下一次會補開單（而不是留言到不存在的 issue）
    retry = process(_event(tmp_path), runner=FakeRunner(details=DETAILS), now="2026-01-02T10:00:00")
    assert [item["submitted"]["jira"]["action"] for item in retry["items"]] == ["created", "created"]
    assert "submit_failures" not in retry


def test_hook_with_incomplete_jira_config_still_writes_files(tmp_path, jira_env, monkeypatch):
    monkeypatch.delenv("QA_BUG_REPORT_JIRA_API_TOKEN")
    out = process(_event(tmp_path), runner=FakeRunner(details=DETAILS), now="t1")

    assert out["reports"] == 2
    assert len(list((tmp_path / "bug-reports").glob("*.md"))) == 2
    assert all("QA_BUG_REPORT_JIRA_API_TOKEN" in f["error"] for f in out["submit_failures"])
    ready, errors = build_submitters(Settings.from_env(tmp_path))
    assert [s.name for s in ready] == ["file"] and list(errors) == ["jira"]


def test_hook_dry_run_does_not_remember_an_issue(tmp_path, jira_env, fake_jira, monkeypatch):
    monkeypatch.setenv("QA_BUG_REPORT_JIRA_DRY_RUN", "1")
    out = process(_event(tmp_path), runner=FakeRunner(details=DETAILS), now="t1")

    assert fake_jira.calls == []
    assert all(item["submitted"]["jira"]["dry_run"] is True for item in out["items"])
    assert len(list((tmp_path / "bug-reports" / "jira-dry-run").glob("*.json"))) == 2
    index = json.loads((tmp_path / "bug-reports" / INDEX_FILENAME).read_text(encoding="utf-8"))
    assert all("jira" not in b["refs"] for b in index["bugs"].values())
    assert all(b["last_submit"]["jira"] == {"ok": True, "at": "t1", "dry_run": True} for b in index["bugs"].values())
    _assert_no_secret(out, _everything_written(tmp_path))

    # 關掉 dry-run 後的第一次執行，會真的建立 issue
    monkeypatch.delenv("QA_BUG_REPORT_JIRA_DRY_RUN")
    real = process(_event(tmp_path), runner=FakeRunner(details=DETAILS), now="t2")
    assert [item["submitted"]["jira"]["action"] for item in real["items"]] == ["created", "created"]


def test_store_keeps_jira_key_across_runs(tmp_path):
    report, _ = _report()
    store = IndexStore(tmp_path)
    store.merge(report, "t1")
    store.set_ref(report, "jira", "QA-55")
    store.record_submit(report, "jira", True, "t1")
    store.save()
    again, _ = _report()
    again.refs = {}
    IndexStore(tmp_path).merge(again, "t2")
    assert again.refs == {"jira": "QA-55"}


# ---- 用本機的假伺服器走一次真正的 HTTP 連線 ---------------------------------

def test_real_http_request_against_local_fake_server():
    """不使用 FakeJira：讓 JiraClient 透過真正的 requests 連到本機的假伺服器。

    用來確認實際送出的請求格式（路徑、Basic 驗證標頭、JSON 內容）。
    伺服器只綁在 127.0.0.1，測試不會連到任何外部服務。
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 — http.server 規定的方法名稱
            length = int(self.headers.get("Content-Length", "0"))
            received.append({
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type"),
                "body": json.loads(self.rfile.read(length).decode("utf-8")),
            })
            if self.path.endswith("/comment"):
                status, payload = 201, {"id": "9001"}
            elif self.headers.get("Authorization") != f"Basic {BASIC}":
                status, payload = 401, {"errorMessages": ["Client must be authenticated"]}
            else:
                status, payload = 201, {"id": "1", "key": "QA-321"}
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):   # 測試時不要印出存取紀錄
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = _config(base_url=f"http://127.0.0.1:{server.server_port}", timeout=5)
        submitter = JiraSubmitter(config, "out")          # 沒有傳入假的 client → 使用 requests
        report, md = _report()
        created = submitter.submit(report, md)
        report.refs = {"jira": created.ref}
        commented = submitter.submit(report, md)

        wrong = _config(base_url=config.base_url, token="wrong-token", timeout=5)
        rejected = JiraSubmitter(wrong, "out").submit(*_report())
    finally:
        server.shutdown()
        server.server_close()

    assert created.ok and created.ref == "QA-321"
    assert commented.ok and commented.info["action"] == "commented"
    assert [r["path"] for r in received[:2]] == ["/rest/api/3/issue", "/rest/api/3/issue/QA-321/comment"]
    assert received[0]["authorization"] == f"Basic {BASIC}"
    assert received[0]["content_type"] == "application/json"
    assert received[0]["body"]["fields"]["project"] == {"key": "QA"}
    assert received[1]["body"]["body"]["type"] == "doc"
    assert rejected.ok is False and "HTTP 401" in rejected.detail
    assert "wrong-token" not in rejected.detail

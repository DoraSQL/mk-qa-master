"""插件測試共用的 fixture。"""
import pytest

from bugreporter_helpers import PYTEST_TIMEOUT_MESSAGE, PYTEST_TITLE_MESSAGE, FakeRunner


@pytest.fixture
def sample_details():
    return [
        {
            "nodeid": "tests/test_login.py::test_login_with_password",
            "title": "輸入帳密後按「登入」應進入首頁",
            "outcome": "failed",
            "duration": 1.2,
            "message": PYTEST_TIMEOUT_MESSAGE.format(line=12),
            "steps": [
                {"api": "Page.set_content", "title": "Set content"},
                {"api": "Locator.click", "title": 'Click get_by_role("button", name="登入")'},
            ],
            "screenshot": "/proj/test-results/a/test-failed-1.png",
            "trace": "/proj/test-results/a/trace.zip",
            "video": "/proj/test-results/a/video.webm",
        },
        {
            "nodeid": "tests/test_login.py::test_login_remember_me",
            "title": None,
            "outcome": "failed",
            "duration": 1.1,
            "message": PYTEST_TIMEOUT_MESSAGE.format(line=48),
            "steps": [],
            "screenshot": None,
            "trace": None,
            "video": None,
        },
        {
            "nodeid": "tests/test_login.py::test_page_title",
            "title": "登入頁標題應為「會員登入」",
            "outcome": "failed",
            "duration": 1.0,
            "message": PYTEST_TITLE_MESSAGE.format(retries=9),
            "steps": [],
            "screenshot": "/proj/test-results/c/test-failed-1.png",
            "trace": None,
            "video": None,
        },
        {
            "nodeid": "tests/test_login.py::test_ok",
            "title": None,
            "outcome": "passed",
            "duration": 0.2,
            "message": "",
            "steps": [],
        },
    ]


@pytest.fixture
def fake_runner(sample_details):
    return FakeRunner(details=sample_details)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (
        "QA_BUG_REPORT_ENABLED",
        "QA_BUG_REPORT_SEVERITY",
        "QA_BUG_REPORT_DIR",
        "QA_BUG_REPORT_SUBMITTERS",
    ):
        monkeypatch.delenv(key, raising=False)

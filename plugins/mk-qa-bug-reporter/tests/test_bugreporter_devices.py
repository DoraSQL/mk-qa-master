"""裝置辨識，以及「同一個測試在不同裝置上失敗」的合併。"""
import hashlib

import pytest

from bugreporter_helpers import PYTEST_TIMEOUT_MESSAGE, FakeRunner
from mk_qa_bug_reporter.devices import split_device
from mk_qa_bug_reporter.grouping import fingerprint_of, group_failures, normalize_error
from mk_qa_bug_reporter.hook import process
from mk_qa_bug_reporter.models import Failure
from mk_qa_bug_reporter.render import render_markdown, render_title

SCROLL_MESSAGE = """\
    def test_no_horizontal_scroll(page: Page):
>       assert page_width <= screen_width, "頁面內容比螢幕寬，手機上會出現左右捲軸"
E       AssertionError: 頁面內容比螢幕寬，手機上會出現左右捲軸
E       assert {page} <= {screen}

test_shop_page.py:54: AssertionError
"""

IPHONE = "test_shop_page.py::test_no_horizontal_scroll[iPhone 15-chromium]"
PIXEL = "test_shop_page.py::test_no_horizontal_scroll[Pixel 7-chromium]"


def _scroll_failures():
    return [
        Failure(IPHONE, SCROLL_MESSAGE.format(page=800, screen=393), title="頁面內容不應該比螢幕寬"),
        Failure(PIXEL, SCROLL_MESSAGE.format(page=801, screen=412), title="頁面內容不應該比螢幕寬"),
    ]


# ---- 裝置辨識 ---------------------------------------------------------------

@pytest.mark.parametrize(
    "nodeid, device, base",
    [
        ("t.py::test_a[iPhone 15-chromium]", "iPhone 15", "t.py::test_a[chromium]"),
        ("t.py::test_a[Pixel 7-webkit]", "Pixel 7", "t.py::test_a[webkit]"),
        ("t.py::test_a[Desktop Chrome-chromium]", "Desktop Chrome", "t.py::test_a[chromium]"),
        ("t.py::test_a[iPad (gen 7) landscape-chromium]", "iPad (gen 7) landscape", "t.py::test_a[chromium]"),
        ("t.py::test_a[Galaxy S24]", "Galaxy S24", "t.py::test_a"),
        ("t.py::test_a[admin-iPhone 15-chromium]", "iPhone 15", "t.py::test_a[admin-chromium]"),
        # 以下都不是裝置
        ("t.py::test_a[chromium]", None, "t.py::test_a[chromium]"),
        ("t.py::test_a[admin-chromium]", None, "t.py::test_a[admin-chromium]"),
        ("t.py::test_a[Pixel]", None, "t.py::test_a[Pixel]"),
        ("t.py::test_a", None, "t.py::test_a"),
        ("a.test.js::adds numbers", None, "a.test.js::adds numbers"),
    ],
)
def test_split_device(nodeid, device, base):
    assert split_device(nodeid) == (device, base)


def test_failure_derives_device_from_nodeid():
    failure = Failure(IPHONE)
    assert failure.device == "iPhone 15"
    assert failure.base_nodeid == "test_shop_page.py::test_no_horizontal_scroll[chromium]"
    assert failure.base_short_name == "test_no_horizontal_scroll[chromium]"
    assert failure.short_name == "test_no_horizontal_scroll[iPhone 15-chromium]"


# ---- 合併規則 ---------------------------------------------------------------

def test_same_test_on_two_devices_with_different_numbers_is_one_report():
    reports = group_failures(_scroll_failures())
    assert len(reports) == 1
    assert reports[0].devices == ["iPhone 15", "Pixel 7"]
    assert reports[0].base_tests == ["test_shop_page.py::test_no_horizontal_scroll[chromium]"]


def test_device_name_inside_message_is_ignored():
    msg = "E   AssertionError: layout broken on {d}\nE   see test-results/x-{slug}-chromium/shot.png\n"
    a = Failure(IPHONE, msg.format(d="iPhone 15", slug="iphone-15"))
    b = Failure(PIXEL, msg.format(d="Pixel 7", slug="pixel-7"))
    assert fingerprint_of(a)[0] == fingerprint_of(b)[0]


def test_different_tests_are_not_merged_just_because_numbers_are_ignored():
    """忽略數字只適用於「同一個測試」。不同測試即使錯誤只差在數字，也要分開。"""
    a = Failure("t.py::test_width[iPhone 15-chromium]", "E   assert 800 <= 393\n")
    b = Failure("t.py::test_height[iPhone 15-chromium]", "E   assert 900 <= 659\n")
    assert fingerprint_of(a)[0] != fingerprint_of(b)[0]


def test_different_error_kinds_on_devices_stay_separate():
    a = Failure(IPHONE, SCROLL_MESSAGE.format(page=800, screen=393))
    b = Failure(PIXEL, "E   AssertionError: 按鈕被遮住\nE   assert 1 == 2\n")
    assert len(group_failures([a, b])) == 2


def test_identical_message_still_merges_across_tests_and_devices():
    """錯誤訊息完全相同（不含數字）時，沿用原本的規則：不分測試、不分裝置都合併。"""
    msg = "E   playwright._impl._errors.Error: 找不到登入按鈕\n"
    failures = [
        Failure("t.py::test_login[iPhone 15-chromium]", msg),
        Failure("t.py::test_login[Pixel 7-chromium]", msg),
        Failure("t.py::test_logout[Pixel 7-chromium]", msg),
    ]
    reports = group_failures(failures)
    assert len(reports) == 1
    assert len(reports[0].base_tests) == 2


def test_fingerprint_without_device_is_unchanged():
    """沒有裝置的測試，指紋算法和加入裝置功能之前相同，既有的 Bug ID 不會變。"""
    message = PYTEST_TIMEOUT_MESSAGE.format(line=12)
    failure = Failure("t.py::test_a[chromium]", message)
    expected = hashlib.sha1(normalize_error(message).encode("utf-8")).hexdigest()[:8]
    assert fingerprint_of(failure) == (expected, normalize_error(message))


def test_fingerprint_is_stable_when_only_one_device_fails():
    """這次只有 iPhone 失敗、下次兩支都失敗，仍然是同一個 Bug ID。"""
    both = group_failures(_scroll_failures())[0]
    only_iphone = group_failures(_scroll_failures()[:1])[0]
    only_pixel = group_failures(_scroll_failures()[1:])[0]
    assert both.bug_id == only_iphone.bug_id == only_pixel.bug_id


def test_empty_message_merges_same_test_across_devices_only():
    a, b = Failure(IPHONE, ""), Failure(PIXEL, "")
    c = Failure("t.py::test_other[Pixel 7-chromium]", "")
    assert fingerprint_of(a)[0] == fingerprint_of(b)[0] != fingerprint_of(c)[0]


# ---- 報告內容 ---------------------------------------------------------------

@pytest.fixture
def cross_device_markdown():
    report = group_failures(_scroll_failures(), environment={"runner": "pytest-playwright", "os": "TestOS"})[0]
    report.title = render_title(report)
    return report, render_markdown(report)


def test_cross_device_title(cross_device_markdown):
    report, _ = cross_device_markdown
    assert report.title == (
        "[test_no_horizontal_scroll[chromium]] AssertionError: 頁面內容比螢幕寬，手機上會出現左右捲軸（2 個裝置）"
    )


def test_environment_lists_devices(cross_device_markdown):
    _, md = cross_device_markdown
    environment = md.split("## 環境")[1].split("##")[0]
    assert "- 裝置：iPhone 15、Pixel 7" in environment
    assert "| 受影響裝置 | iPhone 15、Pixel 7 |" in md


def test_cross_device_body(cross_device_markdown):
    _, md = cross_device_markdown
    assert "同一個測試在 2 個裝置上（iPhone 15、Pixel 7）以同一種錯誤失敗" in md
    assert "測試 `test_no_horizontal_scroll[chromium]` 在 iPhone 15、Pixel 7 上都應通過" in md
    assert f'執行失敗的測試：`pytest "{IPHONE}"`' in md
    assert f'   - Pixel 7：`pytest "{PIXEL}"`' in md
    # 第一支手機的完整訊息 + 另一支手機不同的那幾行
    assert "assert 800 <= 393" in md
    assert "其他失敗的錯誤內容略有不同" in md and "assert 801 <= 412" in md
    assert f"- `{IPHONE}`" in md and f"- `{PIXEL}`" in md


def test_single_device_report_shows_that_device():
    report = group_failures(_scroll_failures()[:1], environment={"runner": "pytest-playwright"})[0]
    md = render_markdown(report)
    assert "- 裝置：iPhone 15" in md
    assert render_title(report).startswith("[test_no_horizontal_scroll[iPhone 15-chromium]]")
    assert "個裝置" not in render_title(report)
    assert "其他失敗的錯誤內容" not in md


def test_no_device_means_no_device_line():
    report = group_failures([Failure("t.py::test_a[chromium]", "E   boom\n")], environment={"runner": "pytest"})[0]
    md = render_markdown(report)
    assert "裝置" not in md


# ---- 整條流程 ---------------------------------------------------------------

def test_process_writes_single_report_for_two_devices(tmp_path):
    runner = FakeRunner(
        details=[
            {"nodeid": IPHONE, "outcome": "failed", "message": SCROLL_MESSAGE.format(page=800, screen=393)},
            {"nodeid": PIXEL, "outcome": "failed", "message": SCROLL_MESSAGE.format(page=801, screen=412)},
            {"nodeid": "test_shop_page.py::test_buy_button_visible[Pixel 7-chromium]", "outcome": "passed"},
        ]
    )
    event = {"tool": "run_tests", "runner": "pytest-playwright", "result": {},
             "report_path": str(tmp_path / "report.json"), "project_root": str(tmp_path)}
    out = process(event, runner=runner, now="2026-01-01T10:00:00")

    assert out["reports"] == 1 and out["failed_tests"] == 2
    assert out["items"][0]["devices"] == ["iPhone 15", "Pixel 7"]
    assert len(list((tmp_path / "bug-reports").glob("*.md"))) == 1

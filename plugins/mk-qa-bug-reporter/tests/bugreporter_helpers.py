"""插件測試共用的假資料與假 runner。"""

PYTEST_TIMEOUT_MESSAGE = """\
page = <Page url='about:blank'>

    def click_login(page):
>       page.get_by_role("button", name="登入").click(timeout=1000)

tests/test_login.py:{line}:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
E       playwright._impl._errors.TimeoutError: Locator.click: Timeout 1000ms exceeded.
E       Call log:
E         - waiting for get_by_role("button", name="登入")

.venv/lib/site-packages/playwright/_impl/_connection.py:{line}: TimeoutError
"""

PYTEST_TITLE_MESSAGE = """\
>       expect(page).to_have_title("會員登入", timeout=1000)
E       AssertionError: Page title expected to be '會員登入'
E       Actual value: 登入
E       Call log:
E         - Expect "to_have_title" with timeout 1000ms
E           {retries} × unexpected value "登入"

tests/test_login.py:30: AssertionError
"""


class FakeRunner:
    """模仿 TestRunner 中本插件會用到的兩個方法。"""

    name = "pytest-playwright"

    def __init__(self, details=None, failure_details=None):
        self._details = details or []
        self._failure_details = failure_details or []

    def get_all_test_details(self):
        return self._details

    def get_failure_details(self, test_id=None):
        return self._failure_details

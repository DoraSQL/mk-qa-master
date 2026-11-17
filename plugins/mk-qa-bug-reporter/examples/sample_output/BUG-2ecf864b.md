# [test_login_with_password[chromium]] playwright._impl._errors.TimeoutError: Locator.click: Timeout 1000ms exceeded.（共 2 個測試）

| 欄位 | 內容 |
|---|---|
| Bug ID | BUG-2ecf864b |
| 嚴重度 | Medium |
| 出現次數 | 2 次（首次 2026-11-17T13:32:21，最近 2026-11-17T13:32:29） |
| 受影響測試數 | 2 |

## 環境

- Runner：pytest-playwright
- 觸發工具：run_tests
- 作業系統：Windows-11-10.0.26300-SP0
- Python：3.12.10
- mk-qa-master：1.5.0
- 專案路徑：C:\path\to\your-project
- 報告時間：2026-11-17T13:32:29

## 重現步驟

1. 進入專案目錄：`C:\path\to\your-project`
2. 執行失敗的測試：`pytest "test_login_demo.py::test_login_with_password[chromium]"`
3. 測試會依序執行以下操作，並在最後一步或其後的檢查失敗：
   - `BrowserContext.newPage`
   - `Frame.setContent`
   - `Frame.fill`
   - `Frame.fill`
   - `Frame.click`

## 預期結果

輸入帳號密碼後按「登入」應能送出表單（測試 `test_login_with_password[chromium]` 應通過）

## 實際結果

2 個測試以相同的錯誤失敗：playwright._impl._errors.TimeoutError: Locator.click: Timeout 1000ms exceeded.

## 錯誤訊息

取自 `test_login_demo.py::test_login_with_password[chromium]`

```text
page = <Page url='about:blank'>

    def test_login_with_password(page: Page):
        """輸入帳號密碼後按「登入」應能送出表單"""
        page.set_content(LOGIN_HTML)
        page.get_by_label("帳號").fill("dora")
        page.get_by_label("密碼").fill("secret")
>       click_login(page)

test_login_demo.py:33: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
test_login_demo.py:25: in click_login
    page.get_by_role("button", name="登入").click(timeout=1000)
C:\path\to\.venv\Lib\site-packages\playwright\sync_api\_generated.py:11045: in click
    self._sync(
C:\path\to\.venv\Lib\site-packages\playwright\_impl\locator.py:222: in click
    return await self._frame.click(
C:\path\to\.venv\Lib\site-packages\playwright\_impl\frame.py:587: in click
    return await self._channel.click(
C:\path\to\.venv\Lib\site-packages\playwright\_impl\channel_owner.py:387: in finish
    raise e from None
C:\path\to\.venv\Lib\site-packages\playwright\_impl\channel_owner.py:352: in finish
    result = await zone.run_async(lambda: awaitable)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

self = <playwright._impl.utils.zones.Zone object at 0x000001E046449670>
func = <function ChannelOwner._wrap_api_call.<locals>.finish.<locals>.<lambda> at 0x000001E0464A5080>

    async def run_async(self, func: Callable[[], Awaitable[R]]) -> R:
        # Python: run() of an async function. The coroutine runs when it is awaited,
        # so the zone must be current while it is awaited, not while it is created.
        token = _async_local_storage.set(self)
        try:
>           return await func()
                   ^^^^^^^^^^^^
E           playwright._impl._errors.TimeoutError: Locator.click: Timeout 1000ms exceeded.
E           Call log:
E             - waiting for get_by_role("button", name="登入")

C:\path\to\.venv\Lib\site-packages\playwright\_impl\utils\zones.py:58: TimeoutError
```

## 截圖／Trace／影片

- `test_login_demo.py::test_login_with_password[chromium]`
  - 截圖：`C:\path\to\your-project\test-results\test-login-demo-py-test-login-with-password-chromium\test-failed-1.png`
  - Trace：`C:\path\to\your-project\test-results\test-login-demo-py-test-login-with-password-chromium\trace.zip`
  - 影片：`C:\path\to\your-project\test-results\test-login-demo-py-test-login-with-password-chromium\video.webm`
- `test_login_demo.py::test_login_with_empty_form[chromium]`
  - 截圖：`C:\path\to\your-project\test-results\test-login-demo-py-test-login-with-empty-form-chromium\test-failed-1.png`
  - Trace：`C:\path\to\your-project\test-results\test-login-demo-py-test-login-with-empty-form-chromium\trace.zip`
  - 影片：`C:\path\to\your-project\test-results\test-login-demo-py-test-login-with-empty-form-chromium\video.webm`

## 受影響的測試

本次執行失敗：
- `test_login_demo.py::test_login_with_password[chromium]` — 輸入帳號密碼後按「登入」應能送出表單
- `test_login_demo.py::test_login_with_empty_form[chromium]` — 不填資料直接按「登入」應能觸發驗證

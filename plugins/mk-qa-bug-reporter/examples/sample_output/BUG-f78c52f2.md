# [test_page_title[chromium]] AssertionError: Page title expected to be '會員登入'

| 欄位 | 內容 |
|---|---|
| Bug ID | BUG-f78c52f2 |
| 嚴重度 | Medium |
| 出現次數 | 2 次（首次 2026-11-17T13:32:21，最近 2026-11-17T13:32:29） |
| 受影響測試數 | 1 |

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
2. 執行失敗的測試：`pytest "test_login_demo.py::test_page_title[chromium]"`
3. 測試會依序執行以下操作，並在最後一步或其後的檢查失敗：
   - `BrowserContext.newPage`
   - `Frame.setContent`
   - `Frame.expect` Expect "to_have_title"

## 預期結果

登入頁的瀏覽器標題應為「會員登入」（測試 `test_page_title[chromium]` 應通過）

## 實際結果

測試失敗：AssertionError: Page title expected to be '會員登入'

## 錯誤訊息

```text
page = <Page url='about:blank'>

    def test_page_title(page: Page):
        """登入頁的瀏覽器標題應為「會員登入」"""
        page.set_content(LOGIN_HTML)
>       expect(page).to_have_title("會員登入", timeout=1000)
E       AssertionError: Page title expected to be '會員登入'
E       Actual value: Login 
E       Call log:
E         - Expect "to_have_title" with timeout 1000ms
E           11 × locator resolved to <html>…</html>
E              - unexpected value "Login"
E       
E       Aria snapshot:
E       - heading "會員登入" [level=1]
E       - textbox "帳號"
E       - textbox "密碼"
E       - button "Sign in"

test_login_demo.py:45: AssertionError
```

## 截圖／Trace／影片

- `test_login_demo.py::test_page_title[chromium]`
  - 截圖：`C:\path\to\your-project\test-results\test-login-demo-py-test-page-title-chromium\test-failed-1.png`
  - Trace：`C:\path\to\your-project\test-results\test-login-demo-py-test-page-title-chromium\trace.zip`
  - 影片：`C:\path\to\your-project\test-results\test-login-demo-py-test-page-title-chromium\video.webm`

## 受影響的測試

本次執行失敗：
- `test_login_demo.py::test_page_title[chromium]` — 登入頁的瀏覽器標題應為「會員登入」

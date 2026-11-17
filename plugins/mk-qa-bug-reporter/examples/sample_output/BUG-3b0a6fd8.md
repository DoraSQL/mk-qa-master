# [test_no_horizontal_scroll[chromium]] AssertionError: 頁面內容比螢幕寬，手機上會出現左右捲軸（2 個裝置）

| 欄位 | 內容 |
|---|---|
| Bug ID | BUG-3b0a6fd8 |
| 嚴重度 | Medium |
| 出現次數 | 1 次（首次 2026-11-17T14:08:42，最近 2026-11-17T14:08:42） |
| 受影響測試數 | 2 |
| 受影響裝置 | iPhone 15、Pixel 7 |

## 環境

- Runner：pytest-playwright
- 裝置：iPhone 15、Pixel 7
- 觸發工具：run_tests
- 作業系統：Windows-11-10.0.26300-SP0
- Python：3.12.10
- mk-qa-master：1.5.0
- 專案路徑：C:\path\to\mk-qa-master\examples\mobile-h5
- 報告時間：2026-11-17T14:08:42

## 重現步驟

1. 進入專案目錄：`C:\path\to\mk-qa-master\examples\mobile-h5`
2. 執行失敗的測試：`pytest "test_shop_page.py::test_no_horizontal_scroll[iPhone 15-chromium]"`
   - Pixel 7：`pytest "test_shop_page.py::test_no_horizontal_scroll[Pixel 7-chromium]"`
3. 測試會依序執行以下操作，並在最後一步或其後的檢查失敗：
   - `BrowserContext.newPage`
   - `Frame.setContent`
   - `Frame.evaluateExpression`
   - `Frame.evaluateExpression`

## 預期結果

頁面內容不應該比螢幕寬（不應出現左右捲軸）（測試 `test_no_horizontal_scroll[chromium]` 在 iPhone 15、Pixel 7 上都應通過）

## 實際結果

同一個測試在 2 個裝置上（iPhone 15、Pixel 7）以同一種錯誤失敗：AssertionError: 頁面內容比螢幕寬，手機上會出現左右捲軸

## 錯誤訊息

取自 `test_shop_page.py::test_no_horizontal_scroll[iPhone 15-chromium]`

```text
page = <Page url='about:blank'>

    def test_no_horizontal_scroll(page: Page):
        """頁面內容不應該比螢幕寬（不應出現左右捲軸）"""
        page.set_content(SHOP_HTML)
        # 螢幕可用寬度要用 clientWidth 來量。不能用 window.innerWidth：手機瀏覽器遇到
        # 過寬的內容時，innerWidth 會跟著被撐大，兩個數字永遠相等，就抓不到問題了。
        screen_width = page.evaluate("() => document.documentElement.clientWidth")
        page_width = page.evaluate("() => document.documentElement.scrollWidth")
>       assert page_width <= screen_width, "頁面內容比螢幕寬，手機上會出現左右捲軸"
E       AssertionError: 頁面內容比螢幕寬，手機上會出現左右捲軸
E       assert 800 <= 393

test_shop_page.py:54: AssertionError
```

其他失敗的錯誤內容略有不同（只列出錯誤本身）：

`test_shop_page.py::test_no_horizontal_scroll[Pixel 7-chromium]`：

```text
AssertionError: 頁面內容比螢幕寬，手機上會出現左右捲軸
assert 801 <= 412
```

## 截圖／Trace／影片

- `test_shop_page.py::test_no_horizontal_scroll[iPhone 15-chromium]`
  - 截圖：`C:\path\to\mk-qa-master\examples\mobile-h5\test-results\test-shop-page-py-test-no-horizontal-scroll-iphone-15-chromium\test-failed-1.png`
  - Trace：`C:\path\to\mk-qa-master\examples\mobile-h5\test-results\test-shop-page-py-test-no-horizontal-scroll-iphone-15-chromium\trace.zip`
  - 影片：`C:\path\to\mk-qa-master\examples\mobile-h5\test-results\test-shop-page-py-test-no-horizontal-scroll-iphone-15-chromium\video.webm`
- `test_shop_page.py::test_no_horizontal_scroll[Pixel 7-chromium]`
  - 截圖：`C:\path\to\mk-qa-master\examples\mobile-h5\test-results\test-shop-page-py-test-no-horizontal-scroll-pixel-7-chromium\test-failed-1.png`
  - Trace：`C:\path\to\mk-qa-master\examples\mobile-h5\test-results\test-shop-page-py-test-no-horizontal-scroll-pixel-7-chromium\trace.zip`
  - 影片：`C:\path\to\mk-qa-master\examples\mobile-h5\test-results\test-shop-page-py-test-no-horizontal-scroll-pixel-7-chromium\video.webm`

## 受影響的測試

本次執行失敗：
- `test_shop_page.py::test_no_horizontal_scroll[iPhone 15-chromium]` — 頁面內容不應該比螢幕寬（不應出現左右捲軸）
- `test_shop_page.py::test_no_horizontal_scroll[Pixel 7-chromium]` — 頁面內容不應該比螢幕寬（不應出現左右捲軸）

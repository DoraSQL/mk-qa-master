# 手機 H5 測試範例

這個資料夾是一個可以直接執行的範例：用「手機瀏覽器的樣子」測試網頁，一次涵蓋一支 iPhone 和一支 Android 手機。

這份說明寫給完全不懂程式的人。

- [手機 H5 是什麼？](#手機-h5-是什麼)
- [這個資料夾裡有什麼](#這個資料夾裡有什麼)
- [怎麼執行](#怎麼執行)
- [怎麼換手機型號](#怎麼換手機型號)
- [這種模擬測不到什麼](#這種模擬測不到什麼)
- [Windows 使用者必讀](#windows-使用者必讀)

---

## 手機 H5 是什麼？

「H5」是業界對**手機版網頁**的慣用說法：使用者不是下載 App，而是用手機上的瀏覽器（Safari、Chrome）或 App 內嵌的瀏覽器打開的網頁。活動頁、購物頁、會員中心常常是這種形式。

手機版網頁最常出的問題，是在電腦上看起來正常、到了手機上才壞掉。例如：

- 內容比螢幕寬，出現左右捲軸
- 按鈕被擠到看不見或按不到
- 文字重疊、圖片破版

這個範例做的事，就是讓測試程式**假裝自己是一支手機**去開網頁，把這類問題抓出來。

假裝的方式是把瀏覽器調成和某支手機一樣的條件：螢幕寬高、螢幕解析倍率、支援觸控、對網站自我介紹時說「我是 iPhone 的 Safari」。這叫做**裝置模擬**。

---

## 這個資料夾裡有什麼

| 檔案 | 用途 | 你需要改它嗎？ |
|---|---|---|
| `conftest.py` | **手機清單。** 決定要用哪幾支手機來測 | 想換手機時改這個 |
| `test_shop_page.py` | **範例測試。** 一個假的商品頁，加上兩個檢查 | 測自己的網站時改這個 |
| `start_server_windows.py` | Windows 專用的啟動檔（原因見最下方） | 不用改 |
| `pytest.ini` | 讓測試工具把這個資料夾當成起點 | 不用改 |
| `.gitignore` | 讓執行後產生的報告不會被放進版本控制 | 不用改 |

範例測試裡有兩個檢查：

| 檢查 | 內容 | 預期結果 |
|---|---|---|
| `test_buy_button_visible` | 看得到「加入購物車」按鈕 | 通過 |
| `test_no_horizontal_scroll` | 頁面內容不比螢幕寬 | **故意失敗**（手機上） |

第二個檢查會失敗，是因為範例網頁裡有一張寬度寫死成 800 的比價表格，而 iPhone 15 的螢幕只有 393 寬、Pixel 7 只有 412 寬。這是刻意留的，讓你看到「抓到問題」長什麼樣子。同一個檢查在桌面版（1280 寬）會通過。

因為清單裡有兩支手機，每個檢查會各跑兩次，所以總共是 **4 個結果：2 個通過、2 個失敗**。

---

## 怎麼執行

### 事前準備（只要做一次）

在 mk-qa-master 的資料夾裡執行：

```bash
pip install -e .
playwright install chromium
```

第二行會下載測試用的瀏覽器。

### 方法一：直接執行（最簡單，先用這個確認環境沒問題）

```bash
cd examples/mobile-h5
pytest
```

最後應該看到：

```
FAILED test_shop_page.py::test_no_horizontal_scroll[iPhone 15-chromium]
FAILED test_shop_page.py::test_no_horizontal_scroll[Pixel 7-chromium]
2 failed, 2 passed
```

每個名稱後面的中括號標明了是哪支手機。看到這個畫面就代表成功了（那 2 個失敗是故意的）。

只想跑其中一支手機：

```bash
pytest -k "Pixel"
```

這個方法不會經過 mk-qa-master，所以**不會**產生 HTML 報告或 bug 報告。

### 方法二：請 AI 執行（透過 mk-qa-master）

把 AI 客戶端裡 mk-qa-master 的設定指向這個資料夾：

```json
"env": {
  "QA_RUNNER": "pytest",
  "QA_PROJECT_ROOT": "/你的路徑/mk-qa-master/examples/mobile-h5"
}
```

然後直接用講的：

- 「跑測試」→ 兩支手機都跑
- 「只跑 iPhone 的測試」→ AI 會自己用關鍵字篩選
- 「哪些測試失敗了？給我看截圖」

**Windows 使用者請先看[最下方的說明](#windows-使用者必讀)，否則 AI 會一直等不到結果。**

### 方法三：用示範腳本模擬 AI 的呼叫（可產生 bug 報告）

如果裝了 `mk-qa-bug-reporter` 插件（`pip install -e plugins/mk-qa-bug-reporter`），可以用它附的腳本，以和 AI 相同的方式執行一次：

```bash
python plugins/mk-qa-bug-reporter/examples/demo_via_mcp.py examples/mobile-h5 --isolate-stdin
```

跑完後，這個資料夾底下會多出 `bug-reports/`，裡面每個失敗各有一份報告。報告的標題、重現指令、截圖路徑都帶有手機名稱，例如：

```
# [test_no_horizontal_scroll[Pixel 7-chromium]] AssertionError: 頁面內容比螢幕寬，手機上會出現左右捲軸
```

目前有兩點要知道：

- 報告的「環境」段落**沒有**獨立列出手機型號，要從標題或測試名稱看。
- 同一個問題在兩支手機上會開成**兩份**報告而不是合併成一份，因為兩支手機量到的寬度數字不同（`800 <= 393` 與 `801 <= 412`），插件把它們當成不同的錯誤。

---

## 怎麼換手機型號

打開 `conftest.py`，找到最上面的清單：

```python
DEVICES = [
    "iPhone 15",
    "Pixel 7",
]
```

改引號裡的名稱就好。檔案裡已經用註解寫了三個範例：換別支手機、多加一支桌面版、暫時只測一支。

### 常用的裝置名稱

名稱要**一字不差**（大小寫、空格都要一樣）：

| 類型 | 名稱 | 螢幕寬度 |
|---|---|---|
| iPhone | `iPhone SE` | 320 |
| iPhone | `iPhone SE (3rd gen)` | 375 |
| iPhone | `iPhone 15` | 393 |
| iPhone | `iPhone 15 Pro Max` | 430 |
| iPhone | `iPhone 17` | 402 |
| Android | `Pixel 7` | 412 |
| Android | `Pixel 10` | 360 |
| Android | `Galaxy S24` | 360 |
| 平板 | `iPad Mini` | 768 |
| 桌面 | `Desktop Chrome` | 1280 |

以上是在 Playwright 1.65 確認過存在的名稱。Playwright 內建兩百多種裝置，完整清單可以用這行指令列出：

```bash
python -c "from playwright.sync_api import sync_playwright as s; p=s().start(); print('\n'.join(p.devices)); p.stop()"
```

名稱打錯時，執行會停下來並顯示：

```
conftest.py 的 DEVICES 裡有 Playwright 不認得的裝置名稱：'iphone15'。
```

### 要注意的事

- **清單有幾支，時間就乘以幾倍。** 兩支手機是兩倍，再加桌面版就是三倍。
- **清單會套用到這個資料夾裡所有的網頁測試。** 沒辦法在這裡指定「這個測試只跑 iPhone」。
- 如果把這個 `conftest.py` 複製到自己的專案，而那個專案原本就有 `conftest.py`，要把內容**合併**進去，不要直接覆蓋。

---

## 這種模擬測不到什麼

裝置模擬很方便，但它不是真的手機。下面這些它測不到，要靠真機或其他方式補。

### 1. 這是模擬，不是真機

模擬的只有四件事：螢幕大小、解析倍率、觸控、瀏覽器的自我介紹（User-Agent）。真機才有的狀況都測不到，例如：

- 手機效能不足造成的卡頓、載入太慢
- 螢幕鍵盤彈出來把輸入框或按鈕遮住
- 瀏覽器上下工具列伸縮造成的版面跳動
- 瀏海、圓角、底部橫條擋到內容
- 在 LINE、Facebook、微信等 App 內嵌瀏覽器裡的特殊行為
- 網路不穩、切到背景再回來

### 2. 「iPhone」其實是 Chrome 假扮的

真正的 iPhone 用的是 Safari 的引擎（WebKit）。這個範例預設用 Chromium（Chrome 的引擎）來跑所有裝置，所以這裡的「iPhone 15」比較精確的說法是「**iPhone 15 尺寸的 Chrome**」。測試名稱後面的 `chromium` 就是在標示這件事。

這代表：**只有 Safari 才會出現的問題抓不到。** 例如某些 CSS 寫法只在 Safari 上壞掉、日期格式解析不同、影片自動播放的限制不同。

想更接近真的 Safari，可以另外安裝 WebKit 引擎（`playwright install webkit`），並請 AI 執行時指定瀏覽器為 `webkit`。**這個組合在這個範例裡沒有測試過**，而且 Playwright 的 WebKit 也不等於 iPhone 上的 Safari，只是比較接近。

### 3. 適合拿來測什麼

版面類的問題：內容超出螢幕、元素被擠掉、斷點（RWD）切換是否正確、手機版選單能不能用、觸控目標是否存在。這些用模擬來抓又快又便宜，適合每次改版都跑。

上線前的最後確認，仍然建議拿真的手機實際操作一次。

---

## Windows 使用者必讀

### 問題

在 Windows 上，透過 AI（MCP）請 mk-qa-master 跑測試時，**測試會卡住不動**，AI 要等 10 分鐘才收到一個「逾時」的結果，而且沒有任何測試結果。

這是 mk-qa-master 1.5.0 本身的問題，和這個範例、和手機模擬都無關。完整的調查在 [`docs/bug-reports/windows-run-tests-stdin-hang.md`](../../docs/bug-reports/windows-run-tests-stdin-hang.md)。

「方法一」（直接打 `pytest`）不受影響。

### 繞過方式

這個資料夾附了一個 `start_server_windows.py`。它在啟動 mk-qa-master 之前先做一個小調整來避開這個問題，不會修改 mk-qa-master 的任何檔案。

用法是把 AI 客戶端設定裡的啟動指令，從原本的：

```json
"command": "C:/你的路徑/.venv/Scripts/python.exe",
"args": ["-m", "mk_qa_master.server"]
```

改成指向這個檔案：

```json
"command": "C:/你的路徑/.venv/Scripts/python.exe",
"args": ["C:/你的路徑/mk-qa-master/examples/mobile-h5/start_server_windows.py"]
```

`env` 的部分不用動。改完後重新啟動 AI 客戶端。

「方法三」的示範腳本則是加上 `--isolate-stdin` 參數，效果相同。

### 驗證到什麼程度

- **已確認：** 用 Python 寫的 MCP 測試用戶端，透過 `start_server_windows.py` 啟動後，這個範例在 2 秒內跑完並回傳正確結果（2 通過、2 失敗），插件也正常產出報告。
- **尚未確認：** Claude Desktop、Cursor 等實際的 AI 客戶端沒有測過。它們啟動 mk-qa-master 的方式相同，推測會遇到一樣的問題、也能用一樣的方式繞過，但這只是推測。

macOS 和 Linux 不需要這個檔案。

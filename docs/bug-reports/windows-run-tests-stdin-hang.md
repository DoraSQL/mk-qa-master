# Windows 上透過 MCP 呼叫 `run_tests` 會卡住直到逾時（子行程繼承 server 的 stdin）

- **回報日期**：2026-11-17
- **影響版本**：v1.5.0（commit `b8e881e`）
- **影響範圍**：以 stdio 啟動的 MCP server，`QA_RUNNER=pytest` 的 `run_tests`；推測所有經由 `safe_run()` 啟動子行程的工具都受影響（見「尚未驗證」）
- **嚴重度**：高 — 在 Windows 上核心功能「跑測試」無法使用；每次呼叫要等到 `QA_TIMEOUT_SECONDS`（預設 600 秒）才回應，而且沒有任何測試結果
- **狀態**：未修復（本文件僅為報告）

## 環境

| 項目 | 值 |
|---|---|
| OS | Windows 11 Pro 10.0.26300 |
| Python | 3.12.10（Microsoft Store 版，`.venv`） |
| mk-qa-master | 1.5.0，`pip install -e .` |
| mcp（Python SDK） | 1.30.0 |
| pytest / pytest-playwright / playwright | 9.2.0 / 0.10.0 / 1.65.2 |
| MCP client | mcp Python SDK 的 `stdio_client` + `ClientSession` |

CI（`.github/workflows/ci.yml`）全部跑在 `ubuntu-latest`，而且測試是直接呼叫函式、不經過 stdio server，所以這個問題不會在 CI 上出現。

## 重現步驟

1. 準備一個只有一個測試的專案（不需要瀏覽器）：

   ```python
   # plain/test_plain.py
   def test_ok():
       assert True
   ```

2. 用 MCP client 以 stdio 啟動 server 並呼叫 `run_tests`。為了不必等 10 分鐘，把逾時設成 30 秒：

   ```python
   import asyncio, os, sys
   from pathlib import Path
   from mcp import ClientSession, StdioServerParameters
   from mcp.client.stdio import stdio_client

   async def main(project_root: str) -> None:
       env = dict(os.environ, QA_RUNNER="pytest", QA_PROJECT_ROOT=project_root,
                  MK_QA_PLUGINS="0", QA_TIMEOUT_SECONDS="30")
       env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
       server = StdioServerParameters(command=sys.executable,
                                      args=["-m", "mk_qa_master.server"], env=env)
       async with stdio_client(server) as (read, write):
           async with ClientSession(read, write) as session:
               await session.initialize()
               result = await session.call_tool("run_tests", {})
               print(result.content[0].text)

   asyncio.run(main(str(Path("plain").resolve())))
   ```

`plugins/mk-qa-bug-reporter/examples/demo_via_mcp.py` 也能重現（不加 `--isolate-stdin` 時會卡住）。

## 預期結果

`run_tests` 在 1 秒左右回應，`exit_code` 為 0，`stdout_tail` 含 `1 passed`，專案目錄下產生 `report.json`。

## 實際結果

`run_tests` 在 30.1 秒（也就是 `QA_TIMEOUT_SECONDS`）後才回應：

- `exit_code` 為 `124`
- `stderr_tail` 帶有 `[TIMEOUT after 30s — increase QA_TIMEOUT_SECONDS to allow longer runs]`
- `stdout_tail` 沒有任何 pytest 輸出
- 沒有產生 `report.json`

使用預設值時，等待時間是 600 秒。第一次遇到時我等了超過 5 分鐘仍無回應，當時的行程樹是：

```
python -m mk_qa_master.server
└─ pytest.exe --browser=chromium --screenshot=on ...
   └─ python.exe  pytest.exe ...
      └─ python3.12.exe  pytest.exe ...      ← 停在這裡，沒有再產生任何子行程
```

沒有 Playwright driver（node）或瀏覽器行程，表示 pytest 還沒開始執行測試就停住了。`test-results/telemetry/tool-usage.jsonl` 只有先前 `get_runner_info` 的紀錄。

逾時訊息建議使用者「調高 `QA_TIMEOUT_SECONDS`」，在這個情況下是誤導：調高只會等更久。

## 根本原因分析

### 對照實驗

同一台機器、同一個 `.venv`、插件關閉（`MK_QA_PLUGINS=0`）、`QA_TIMEOUT_SECONDS=30`，只改變兩個變因：

| 受測專案 | 子行程的 stdin | `run_tests` 回應時間 | `exit_code` | pytest 結果 |
|---|---|---|---|---|
| 空測試（1 個 `assert True`） | 繼承 server 的 stdin（現況） | 30.1 秒 | 124（逾時） | 無輸出 |
| Playwright 測試（4 個） | 繼承 server 的 stdin（現況） | 30.1 秒 | 124（逾時） | 無輸出 |
| 空測試 | `DEVNULL` | 0.7 秒 | 0 | 1 passed |
| Playwright 測試 | `DEVNULL` | 6.6 秒 | 1 | 3 failed, 1 passed（預期的結果） |

另外，在終端機直接執行同一組 Playwright 測試（`pytest ... < /dev/null`）耗時 5.76 秒，結果同為 3 failed, 1 passed。

「stdin 為 `DEVNULL`」那兩列的做法是：不改 `src/`，改用下面這段包裝程式啟動 server，唯一的差別是替 `subprocess.run` 補上 `stdin` 的預設值：

```python
import subprocess
_run = subprocess.run
def run(*args, **kwargs):
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    return _run(*args, **kwargs)
subprocess.run = run
from mk_qa_master.server import run as serve
serve()
```

結論：

- **卡住與否完全取決於子行程是否繼承 stdin。**
- 和 Playwright、瀏覽器、測試內容無關（空測試一樣卡）。
- 和插件無關（實驗中插件是關閉的）。

### 程式位置

`src/mk_qa_master/security.py` 的 `safe_run()`（第 98–131 行）：

```python
107    kwargs.setdefault("capture_output", True)
108    kwargs.setdefault("text", True)
109    effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT_SECONDS
110    try:
111        return subprocess.run(cmd, timeout=effective_timeout, **kwargs)
```

`capture_output=True` 只接管 stdout 與 stderr，**沒有指定 `stdin`**，所以子行程繼承父行程的 stdin。以 stdio 方式執行 MCP server 時，父行程的 stdin 正是 client 用來傳送 JSON-RPC 訊息的管線，而且 server 此時正在等著從這條管線讀下一則訊息。

pytest runner 的呼叫點都沒有另外傳 `stdin`：

- `src/mk_qa_master/runners/pytest_playwright.py:92` — `list_tests`
- `src/mk_qa_master/runners/pytest_playwright.py:122` — `run_tests`
- `src/mk_qa_master/runners/pytest_playwright.py:133` — `run_failed`

### 尚未確定的部分

**pytest 具體卡在哪一個系統呼叫，我沒有查證。** 合理的推測是：Windows 上對同一條同步管線，當一方正阻塞在讀取時，另一方對該 handle 的某些操作（例如 pytest 啟動時為了擷取輸出而對 fd 0 做的複製或查詢）會一起被阻塞。這只是推測；上面的對照實驗能確認的是「繼承 stdin 是必要條件」，不能確認機制。

### 尚未驗證

- **實際的 AI 客戶端**（Claude Desktop、Cursor、Claude Code 等）在 Windows 上是否同樣卡住。它們也是以 stdio 管線啟動 server，推測會，但我只用 mcp Python SDK 的 client 測過。
- **macOS / Linux** 沒有測。專案的使用說明與 walkthrough 都以這些平台為主，推測沒有這個問題。
- **`list_tests` 與 `run_failed`**：走同一個 `safe_run()`，推測同樣卡住，沒有實測。
- **其他 runner**：jest、cypress、go、maestro、newman、schemathesis、edge 都透過 `safe_run()` 啟動子行程（各 `runners/*.py`），推測受相同影響；是否卡住取決於被啟動的程式會不會碰 stdin，沒有實測。
- **不經過 `safe_run()` 的子行程**：`config.py:174`（`adb connect`）、`runners/pytest_playwright.py:501`（codegen）、`tools/analyzer.py:469,487`、`edge/rtsp_source.py:98,103`、`edge/resilience.py:73,90,149` 直接呼叫 `subprocess.run` / `Popen`。我沒有逐一確認它們是否指定了 `stdin`。

## 建議修法

（僅為建議，本次未修改任何程式碼。）

1. **在 `safe_run()` 補上 stdin 的預設值。** 一行即可，而且所有經由 `safe_run()` 的 runner 一次修好：

   ```python
   kwargs.setdefault("stdin", subprocess.DEVNULL)
   ```

   用 `setdefault` 而不是直接指定，呼叫端若真的需要傳入 stdin（例如 `input=`）仍可覆寫。注意 `subprocess.run` 不允許同時傳 `input` 和 `stdin`，所以要寫成「呼叫端沒有傳 `input` 時才補預設值」。

   這也符合 stdio MCP server 的一般原則：server 的 stdin/stdout 是協定通道，子行程不應該碰到它們。stdout 已經因為 `capture_output=True` 而隔離，stdin 是漏掉的那一半。

2. **檢查不經過 `safe_run()` 的呼叫點**（見上方清單），逐一確認是否需要同樣的處理，或改為統一走 `safe_run()`。

3. **補測試。** 目前的測試都直接呼叫函式，沒有一個測試是「以 stdio 啟動 server 再呼叫工具」。建議：
   - 單元測試：mock `subprocess.run`，斷言 `safe_run()` 傳出的 `stdin` 是 `DEVNULL`。這個可以在 Linux CI 上跑。
   - 整合測試：用 mcp SDK 的 `stdio_client` 啟動 server，對一個空測試專案呼叫 `run_tests`，斷言在數秒內回應且 `exit_code == 0`。
   - 在 `ci.yml` 加一個 `windows-latest` 的 job 跑上述整合測試。`docs/bug-reports/windows-file-url.md` 也是同一類「只有 Windows 才出現、CI 看不到」的問題。

4. **調整逾時訊息。** `[TIMEOUT ... increase QA_TIMEOUT_SECONDS ...]` 在子行程完全沒有輸出時是誤導。可以在 stdout 為空時改提示「子行程沒有任何輸出，可能卡在啟動階段」。

修這個 bug 不會改動任何 tool 的 `inputSchema`，不涉及 v1.0 schema 快照與 `BREAKING_CHANGE_ACK`。

## Workaround

在修復之前，Windows 使用者可以把 MCP 設定中的啟動指令改成用上面那段包裝程式啟動 server（存成一個 `.py` 檔，`command` 指向 Python、`args` 指向該檔）。這個做法我只用 mcp Python SDK 的 client 驗證過。

`plugins/mk-qa-bug-reporter/examples/demo_via_mcp.py --isolate-stdin` 就是用這個方式。

# Windows 上 `run_api_security_scan` 無法載入本機 OpenAPI spec（裸路徑與 `file://C:\...` 皆失敗）

- **回報日期**：2026-11-17
- **影響版本**：v1.5.0（commit `b8e881e`）
- **影響範圍**：`run_api_security_scan` MCP tool、`mk_qa_master.runners.api_security.load_spec()`
- **嚴重度**：中 — Windows 使用者以本機檔案作為 spec 時，功能幾乎不可用；有 workaround（見文末）
- **狀態**：未修復（本文件僅為報告）

## 環境

| 項目 | 值 |
|---|---|
| OS | Windows 11 Pro 10.0.26300 |
| Python | 3.12.10（`.venv`） |
| mk-qa-master | 1.5.0，`pip install -e .` |
| 系統預設編碼 | cp950（重現時已設 `PYTHONUTF8=1`，排除編碼因素） |

CI（`.github/workflows/ci.yml`）所有 job 都跑在 `ubuntu-latest`，因此這個問題不會在 CI 上出現。

## 重現步驟

### A. 最小重現（直接呼叫 `load_spec`）

```python
import tempfile
from pathlib import Path
from mk_qa_master.runners.api_security import load_spec

p = Path(tempfile.mkdtemp()) / "spec.yaml"
p.write_text("openapi: 3.0.0\n", encoding="utf-8")

load_spec(str(p))            # 寫法 1：裸路徑  C:\Users\...\spec.yaml
load_spec(f"file://{p}")     # 寫法 2：file://C:\Users\...\spec.yaml
load_spec(p.as_uri())        # 寫法 3：file:///C:/Users/.../spec.yaml
```

### B. 透過測試套件

```bash
PYTHONUTF8=1 python -m pytest tests/test_runner_api_security.py tests/test_runner_api_security_plan.py -q
```

## 預期結果

- 寫法 1、2、3 都回傳解析後的 spec dict（`{'openapi': '3.0.0'}`）。`load_spec` 的 docstring 與程式分支都表明裸路徑與 `file://` 是支援的輸入。
- 測試套件 39 個測試全數通過（與 Linux 相同）。

## 實際結果

| 寫法 | 輸入 | 結果 |
|---|---|---|
| 1 裸路徑 | `C:\Users\...\spec.yaml` | `ValueError: Unsupported spec_url scheme: 'c'` |
| 2 `file://` + Windows 路徑 | `file://C:\Users\...\spec.yaml` | `FileNotFoundError: [Errno 2] No such file or directory: ''` |
| 3 標準 file URI | `file:///C:/Users/.../spec.yaml` | 成功 |

透過 MCP tool 呼叫時，例外被 `run_scan` 接住，使用者看到的是：

```json
{"error": "spec_load_failed", "retryable": false,
 "hint": "ValueError: Unsupported spec_url scheme: 'c'"}
```

測試套件：**21 failed, 18 passed**。

- `tests/test_runner_api_security.py`：15 個失敗
- `tests/test_runner_api_security_plan.py`：6 個失敗

其中 20 個屬於寫法 1（測試以 `str(tmp_path / "spec.yaml")` 傳入裸路徑），1 個屬於寫法 2（`test_load_spec_file_uri`）。多數失敗的斷言訊息是 `assert 'spec_load_failed' == 'unauthorized_domain'` 這類形式 — 測試原本要驗證後段邏輯（網域授權、categories、severity、plan 驗證），但在 spec 載入階段就提前返回了。

## 根本原因分析

問題在 `src/mk_qa_master/runners/api_security.py` 的 `load_spec()`（第 108–133 行），它用 `urllib.parse.urlparse()` 的 `scheme` 來判斷輸入種類：

```python
114    parsed = urllib.parse.urlparse(spec_url)
115    if parsed.scheme in ("http", "https"):
...
118    elif parsed.scheme == "file":
119        with open(urllib.request.url2pathname(parsed.path), "r",
120                  encoding="utf-8") as fh:
...
122    elif parsed.scheme == "":  # bare path
123        with open(spec_url, "r", encoding="utf-8") as fh:
...
125    else:
126        raise ValueError(f"Unsupported spec_url scheme: {parsed.scheme!r}")
```

### 原因 1：磁碟代號被當成 URL scheme（第 114、122、126 行）

`urlparse(r"C:\Users\x\spec.yaml")` 的結果是 `scheme='c'`、`path='\\Users\\x\\spec.yaml'`。Windows 的磁碟代號加冒號符合 URL scheme 的語法，所以第 122 行的 `scheme == ""` 裸路徑分支永遠進不去，直接落到第 126 行丟出 `ValueError`。

在 POSIX 上路徑以 `/` 開頭，`scheme` 為空字串，所以這個分支運作正常。

### 原因 2：`file://C:\...` 的路徑落在 netloc（第 118–119 行）

`urlparse(r"file://C:\Users\x\spec.yaml")` 的結果是：

```
scheme = 'file'
netloc = 'C:\\Users\\x\\spec.yaml'
path   = ''
```

`//` 之後到下一個 `/` 之前都算 authority（netloc），而 Windows 路徑用反斜線，整段都被吃進 netloc。第 119 行只讀 `parsed.path`，得到空字串，`open('')` 丟出 `FileNotFoundError`。

在 POSIX 上 `f"file://{path}"` 會自然變成 `file:///tmp/...`（三條斜線），netloc 為空，所以同樣的寫法沒有問題。

### 例外如何變成 `spec_load_failed`

`run_scan()` 在第 273–280 行以 `except Exception` 包住 `load_spec`，一律轉成 `{"error": "spec_load_failed", ...}`。這個行為本身是正確的，只是讓上述兩種錯誤在 tool 層看起來一樣。

### 相關測試位置

- `tests/test_runner_api_security.py:53-56` — `spec_file` fixture 回傳 `str(p)`（裸路徑），多數測試經由它或同樣寫法觸發原因 1
- `tests/test_runner_api_security.py:130` — `load_spec(f"file://{spec_file}")` 觸發原因 2

### 可能相關、但未實際驗證

`src/mk_qa_master/runners/schemathesis.py:66-73` 的 `_to_cli_target()` 同樣以 `urlparse(url).path` 把 `file://` 轉成路徑。依 `urlparse` 的行為推斷：

- `file://C:\...` → `path` 為空字串
- `file:///C:/...` → `path` 為 `/C:/...`（多了前導斜線，且未經 `url2pathname`）

我沒有在 Windows 上實際跑 schemathesis runner 確認結果，修這個 bug 時建議一併檢查。

## 建議修法

（僅為建議，本次未修改任何程式碼。）

1. **在 `load_spec()` 先辨識本機路徑，再做 URL 解析。** 只有明確的 `http://`、`https://`、`file://` 前綴才當 URL，其餘一律當檔案路徑，不再依賴 `urlparse().scheme == ""`：

   ```python
   lowered = spec_url.lower()
   if lowered.startswith(("http://", "https://")):
       ...  # urlopen
   elif lowered.startswith("file://"):
       path = _file_url_to_path(spec_url)
       ...  # open(path)
   else:
       ...  # open(spec_url) — 裸路徑，含 C:\... 與相對路徑
   ```

   代價是 `ftp://...` 這類不支援的 scheme 會變成「找不到檔案」而非「Unsupported scheme」。如要保留原訊息，可加一條判斷：含 `://` 但不是上述三種前綴時才丟 `ValueError`。

2. **`file://` 轉路徑時把 netloc 一併考慮。** 寬鬆處理使用者常見的 `file://C:\...` 寫法：

   ```python
   def _file_url_to_path(url: str) -> str:
       parsed = urllib.parse.urlparse(url)
       raw = parsed.netloc + parsed.path   # file://C:\x → netloc 才有內容
       return urllib.request.url2pathname(raw)
   ```

   需確認三種輸入都正確：`file:///C:/x`、`file://C:\x`、POSIX 的 `file:///tmp/x`；另外要決定 `file://server/share/x`（UNC）是否支援。

3. **把轉換邏輯抽成共用 helper**（例如放在 `security.py` 或新的小模組），讓 `runners/schemathesis.py::_to_cli_target` 共用，避免兩處各自解析。

4. **補測試與 CI。**
   - 以參數化測試直接驗證路徑轉換函式對 Windows 風格字串的結果（純字串運算，可在 Linux CI 上跑）。
   - 測試中的 `f"file://{spec_file}"` 改用 `Path.as_uri()`，並另加一個案例專門涵蓋 `file://C:\...`。
   - 考慮在 `ci.yml` 的 `smoke` matrix 加一個 `windows-latest`，否則這類平台差異仍無法被自動發現。

修這個 bug 不會改動任何 tool 的 `inputSchema`（`spec_url` 仍是字串），所以不涉及 v1.0 schema 快照與 `BREAKING_CHANGE_ACK`。

## Workaround

在修復之前，Windows 上請用標準 file URI 傳入 `spec_url`：

```
file:///C:/path/to/openapi.yaml
```

Python 中可用 `pathlib.Path(...).as_uri()` 產生。

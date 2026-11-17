# Windows 上 `mk-qa-master doctor` 的輸出被轉接或存檔時會當掉（`UnicodeEncodeError`）

- **回報日期**：2026-11-17
- **影響版本**：v1.5.0（commit `b8e881e`）
- **影響範圍**：`mk-qa-master doctor` 與 `mk-qa-master doctor --json`，在系統編碼不是 UTF-8 的 Windows 上，且輸出不是直接顯示在終端機時
- **嚴重度**：中 — `doctor` 是用來診斷安裝問題的工具，`--json` 更是設計給 CI 與 AI 讀取的；在這個情境下它完全無法使用，而且當掉的訊息和使用者想查的問題無關。有簡單的 workaround
- **狀態**：未修復（本文件僅為報告）

## 環境

| 項目 | 值 |
|---|---|
| OS | Windows 11 Pro 10.0.26300 |
| 系統預設編碼 | cp950（繁體中文 Big5） |
| Python | 3.12.10（Microsoft Store 版，`.venv`） |
| mk-qa-master | 1.5.0，`pip install -e .` |
| Shell | Git Bash |

CI（`.github/workflows/ci.yml`）全部跑在 `ubuntu-latest`，系統編碼是 UTF-8，所以這個問題不會在 CI 上出現。

## 重現步驟

在系統編碼為 cp950 的 Windows 上，把 `doctor` 的輸出導到檔案（或用管線接給其他程式）：

```bash
mk-qa-master doctor > doctor.txt 2>&1
echo "exit=$?"

mk-qa-master doctor --json > doctor.json 2>&1
echo "exit=$?"
```

## 預期結果

- 第一個指令：`doctor.txt` 內含分組的檢查結果，結束代碼為 0（沒有嚴重問題時）。
- 第二個指令：`doctor.json` 內含合法的 JSON，可被其他程式解析。

README 對這兩個指令的說明是（`README.md:131-132`）：

```
mk-qa-master doctor          # human-readable check report
mk-qa-master doctor --json   # for CI gates / host-LLM consumption
```

`--json` 的用途就是給其他程式讀取，也就是輸出一定會被轉接。

## 實際結果

兩個指令都以結束代碼 1 當掉，沒有任何檢查結果，只有 Python 的錯誤訊息。

純文字模式：

```
  File "...\src\mk_qa_master\doctor.py", line 325, in main
    print(render_json(results) if args.json else render_plain(results))
UnicodeEncodeError: 'cp950' codec can't encode character '✓' in position 54: illegal multibyte sequence
```

`--json` 模式：

```
  File "...\src\mk_qa_master\doctor.py", line 325, in main
    print(render_json(results) if args.json else render_plain(results))
UnicodeEncodeError: 'cp950' codec can't encode character '≥' in position 167: illegal multibyte sequence
```

`✓` 是 `✓`，`≥` 是 `≥`。

結束代碼 1 還有一個副作用：`doctor` 的設計是「有嚴重問題才回傳 1」（`doctor.py` 的 `_exit_code()`）。用結束代碼當 CI 關卡的人會把這次當掉誤判成「環境有嚴重問題」。

### 對照

加上 `PYTHONUTF8=1` 後，同樣的指令正常完成：

```bash
PYTHONUTF8=1 mk-qa-master doctor > doctor.txt 2>&1    # 結束代碼 0，輸出 38 行檢查結果
```

| 指令 | 輸出去向 | `PYTHONUTF8` | 結果 |
|---|---|---|---|
| `doctor` | 導到檔案 | 未設定 | 當掉（`✓`） |
| `doctor --json` | 導到檔案 | 未設定 | 當掉（`≥`） |
| `doctor` | 導到檔案 | `1` | 正常，結束代碼 0 |

## 根本原因分析

`src/mk_qa_master/doctor.py:325` 用 `print()` 把整份結果寫到標準輸出：

```python
325    print(render_json(results) if args.json else render_plain(results))
```

輸出內容包含 cp950 沒有的字元：

- `doctor.py:243` — 狀態符號：

  ```python
  243  _GLYPH = {"ok": "✓", "warn": "!", "fail": "✗"}
  ```

  每一列檢查結果都以其中一個開頭（`render_plain()`，第 253 行起）。只要有任何一項檢查通過，就會印出 `✓`。

- `doctor.py:76`、`:81` — 檢查項目的名稱本身：

  ```python
  76              section="System", name="Python ≥ 3.10",
  ```

  這個名稱會出現在純文字與 JSON 兩種輸出裡。

- `doctor.py:302` — JSON 模式刻意保留非 ASCII 字元：

  ```python
  302      return json.dumps(payload, indent=2, ensure_ascii=False)
  ```

  所以 `≥` 會原樣輸出，而不是變成 `≥` 這種純 ASCII 的寫法。

Windows 上，當 Python 的標準輸出**不是**終端機（被導到檔案或管線）時，`print()` 會用系統的預設編碼來轉換文字。在繁體中文 Windows 上是 cp950，它沒有 `✓`、`✗`、`≥` 這幾個字，於是丟出 `UnicodeEncodeError`。程式沒有處理這個例外，整個指令就結束了。

我另外直接測了這五個字元能不能轉成 cp950：

| 字元 | 出現位置 | 能轉成 cp950 嗎 |
|---|---|---|
| `—`（破折號） | 第 260、269 行 | 可以 |
| `─`（分隔線） | 第 275 行 | 可以 |
| `✓` | 第 243 行 | **不行** |
| `✗` | 第 243 行 | **不行** |
| `≥` | 第 76、78、81 行 | **不行** |

所以問題出在後三個。純文字模式的錯誤訊息指出的位置，對應到輸出中的第一個 `✓`（在標題那行的 `—` 之後），和這張表一致。

### 為什麼現有的測試沒抓到

`tests/test_doctor.py` 的測試是直接呼叫 `doctor.render_plain(results)` 並檢查回傳的字串（例如第 152–177 行的三個測試）。這條路徑不經過 `print()`，也不經過標準輸出的編碼轉換，所以在 Windows 上同樣會通過。

### 尚未驗證

- **直接在終端機視窗裡執行（輸出沒有被轉接）會不會當掉。** Python 在 Windows 的終端機上是用另一種方式輸出文字，通常不受系統編碼限制，所以推測不會當掉。我沒有實際在互動式的終端機視窗裡試過，因此不能確定。
- **其他非 UTF-8 的 Windows 語系**（例如簡體中文 cp936、日文 cp932、西歐 cp1252）。它們各自缺的字元不同，推測多數也會當掉，但沒有測過。
- **macOS / Linux** 沒有測。它們的預設編碼通常是 UTF-8，推測沒有這個問題。
- **由 AI 客戶端代為執行 `doctor`** 時的實際行為（`README.md:643` 的疑難排解建議用它檢查安裝）。那種情況下輸出一定會被轉接，推測會遇到同樣的問題，沒有實測。

## 建議修法

（僅為建議，本次未修改任何程式碼。）

1. **在 `doctor.main()` 輸出之前，把標準輸出設成 UTF-8。** 改動最小，兩種模式一次解決：

   ```python
   if hasattr(sys.stdout, "reconfigure"):
       sys.stdout.reconfigure(encoding="utf-8", errors="replace")
   ```

   `errors="replace"` 是保險：就算之後又有無法轉換的字元，也只會變成 `?`，不會讓指令當掉。

   需要留意：輸出被導到檔案後，檔案內容會是 UTF-8。在 Windows 上用舊版記事本或某些工具開啟可能顯示成亂碼。對 `--json` 來說這是正確的（JSON 的標準編碼就是 UTF-8）；對純文字模式則是取捨。

2. **`--json` 模式改用 `ensure_ascii=True`。** 這樣輸出只含 ASCII，不論系統編碼為何都不會出錯，而且仍然是合法的 JSON（`≥` 會寫成 `≥`，解析後還原成同一個字）。這和第 1 點可以同時做：給機器讀的輸出本來就不需要好讀。

3. **純文字模式提供 ASCII 的替代符號。** 例如在無法輸出時把 `✓` / `✗` 換成 `[OK]` / `[FAIL]`、`≥` 換成 `>=`。做了第 1 點就不一定需要，但對使用舊終端機字型的人比較友善。

4. **補測試。** 目前沒有任何測試涵蓋「真的把結果印出去」這一段。建議加一個測試：以子行程執行 `python -m mk_qa_master.server doctor --json`，設定 `PYTHONIOENCODING=cp950`（或 `ascii`）模擬非 UTF-8 的輸出環境，斷言結束代碼不是因為編碼錯誤而失敗、且輸出可被 `json.loads` 解析。這個測試可以在 Linux CI 上跑，不需要 Windows 機器。

5. **檢查同類問題。** 主測試套件在這台電腦上有 1 個測試因為「讀檔時沒有指定編碼」而失敗（`UnicodeDecodeError: 'cp950'`，記在 `CLAUDE.md` 的 Windows 注意事項），和這個問題是同一類：程式假設系統編碼是 UTF-8。建議把「Windows 非 UTF-8 環境」當成一個整體來檢查，並考慮在 `ci.yml` 加一個 `windows-latest` 的 job。

修這個 bug 不會改動任何 MCP tool 的 `inputSchema`，不涉及 v1.0 schema 快照與 `BREAKING_CHANGE_ACK`。

## Workaround

在修復之前，Windows 使用者執行 `doctor` 時加上 `PYTHONUTF8=1`：

```bash
# Git Bash
PYTHONUTF8=1 mk-qa-master doctor
```

```powershell
# PowerShell
$env:PYTHONUTF8 = "1"
mk-qa-master doctor
```

Git Bash 的寫法實測可用。PowerShell 的寫法是同一個環境變數的另一種設定方式，沒有另外實測。

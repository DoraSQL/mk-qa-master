# 文件與程式碼不一致之處（8 項）

- **回報日期**：2026-11-17
- **影響版本**：v1.5.0（commit `b8e881e`）
- **來源**：整理自 `ARCHITECTURE_INSIGHTS.md` 第 4 節，並補上行號與實際查證結果
- **狀態**：未修復（本文件僅為報告，沒有修改任何文件或程式）

## 怎麼讀這份清單

- 每一列是一項不一致。「文件怎麼寫」與「程式實際如何」都附了檔案路徑與行號。
- **我只列出兩邊不同的事實，沒有判斷哪一邊才是作者的本意。** 多數情況看起來是文件沒跟上程式，但也可能反過來（文件寫的才是想要的行為）。
- 「查證方式」欄說明我是讀程式碼比對，還是實際執行過。

這些文件主要是給 AI 客戶端讀的操作手冊（`skills/mk-qa-master/`）。AI 會照文件寫的參數名稱與路徑去做，所以這類不一致會直接變成錯誤的工具呼叫或找不到檔案。

## 清單

| # | 類別 | 文件怎麼寫 | 程式實際如何 | 查證方式 |
|---|---|---|---|---|
| 1 | 引用不存在的檔案 | `skills/mk-qa-master/SKILL.md:161` 要讀 `reference/captcha-solver.md`；`SKILL.md:202`、`commands/api-security.md:8`、`reference/workflow.md:153` 要讀 `reference/api-security-deep.md` | `skills/mk-qa-master/reference/` 只有 `tool-surface.md`、`wire-mcp.md`、`workflow.md` 三個檔案 | 列出目錄內容 |
| 2 | 參數名稱 | `get_failure_details` 的參數寫成 `test_name`：`SKILL.md:116`、`SKILL.md:140`、`reference/tool-surface.md:28`、`reference/workflow.md:80` | 參數是 `test_id`：`src/mk_qa_master/server.py:1194` 讀 `args.get("test_id")`，`tests/snapshots/v1/tool_surface.json:64` 的凍結 schema 也只有 `test_id`。依程式碼推斷，傳 `test_name` 會被忽略，回傳全部失敗而不是指定的那一個 | 讀程式碼與 schema 快照；沒有實際用 `test_name` 呼叫過 |
| 3 | 報告檔路徑 | `reference/tool-surface.md:27` 與 `reference/workflow.md:191`：`test-results/report.json`；`reference/tool-surface.md:46`：HTML 寫到 `test-results/report.html` | `src/mk_qa_master/config.py:10`：`PROJECT_ROOT / "report.json"`（專案根目錄，不在 `test-results/` 下）；`src/mk_qa_master/reporters/html.py:338`：`PROJECT_ROOT / output`，預設 `report.html` 也在專案根目錄 | 讀程式碼；實測時 `report.json` 確實出現在專案根目錄 |
| 4 | 預設值 | `reference/tool-surface.md:76`：`QA_PROJECT_ROOT` 預設為 CWD | `src/mk_qa_master/config.py:6`：預設為 `./tests_project` | 讀程式碼 |
| 5 | CLI 備援指令無法使用 | `reference/wire-mcp.md:95-96`：`from mk_qa_master.tools.reporter import generate_html`；`reference/tool-surface.md:106`：`python -m mk_qa_master.tools.runner list_tests` | `src/mk_qa_master/tools/reporter.py` 沒有 `generate_html`（只有 `get_report_summary`、`get_failure_details`、`get_history`）；`src/mk_qa_master/tools/runner.py` 沒有 `__main__` 區塊 | **實際執行**：第一個得到 `ImportError: cannot import name 'generate_html'`；第二個結束代碼為 0 但沒有任何輸出，也沒有列出測試 |
| 6 | 版本號過時 | `SKILL.md:41` 與 `reference/wire-mcp.md:88`：`pip install mk-qa-master==0.9.0` | `pyproject.toml:3`：目前版本 `1.5.0`。照文件安裝會得到沒有 `analyze_stream`、插件機制、`doctor` 的舊版 | 讀檔案 |
| 7 | 中文 README 落後英文版 | `README.zh-TW.md` 沒有下列章節 | `README.md` 有：OWASP API Security scanning（`:326`）、Use as a … skill（`:446`）、Stability promise（`:504`）、License Evolution Plan（`:533`）、Edge AI Runner（`:562`）、Universal plan + verify bookend（`:658`）。中文版的「Tool 清單」（`README.zh-TW.md:378`）也因此少了這些功能對應的工具 | 比對兩份檔案的標題；中文版內文只讀了部分段落 |
| 8 | `report://json` 的內容描述 | `README.zh-TW.md:409` 與 `README.md:862`：「原始 pytest-json-report JSON」 | `src/mk_qa_master/server.py:1111` 的資源描述：「原始 report.json（各 runner 的原生格式）」 | 讀程式碼。哪一個說法準確要逐一讀各 runner 才知道，我只確認過 pytest runner 寫出的是 pytest-json-report 格式 |

## 補充說明

### 第 5 項：還有一個沒查的指令

`reference/tool-surface.md:105` 另外寫了 `python -m mk_qa_master.tools.visual_challenge --help`。我沒有執行它，也沒有讀 `tools/visual_challenge.py` 是否有命令列入口，所以不列入上表。

### 第 7 項：相關的過時連結

`README.zh-TW.md:35` 與 `README.md:44` 都把 `docs/framework.md` 稱為「完整設計文件／Full design notes」。該文件描述的是 v0.1 的設計（7 個工具、沒有 runner 抽象層），和目前的架構不符。這一點兩份 README 是一致的，所以不算「中英文不一致」，但同屬文件過時。

`README.md` 的「Project layout」（`:885`）與 `README.zh-TW.md` 的「專案結構」（`:426`）也只列了 4 個 runner，沒有 `maestro.py`、`schemathesis.py`、`newman.py`、`edge_inference.py`、`api_security.py`，也沒有 `plugins.py`、`security.py`、`doctor.py`、`security_rules/`、`edge/`。

### 為什麼現有的測試沒抓到

`tests/test_v1_doc_sync.py` 會掃描 `README.md`、`SKILL.md`、`reference/*.md`，但只檢查兩件事：文件裡宣稱的工具數量，以及是否列出每個工具的名稱。參數名稱、檔案路徑、文件之間的連結、版本號都不在檢查範圍內。`README.zh-TW.md` 也不在掃描清單裡。

## 建議

（僅為建議，本次未修改任何檔案。）

1. **先確認每一項以哪邊為準**，再決定改文件還是改程式。第 3、4 項尤其需要作者判斷：文件寫的 `test-results/report.json` 和 CWD 預設值也可能是原本想要的設計。
2. **第 1、2、5、6 項可以直接修文件**，風險低：補上或移除兩個不存在的 reference 連結、把 `test_name` 改成 `test_id`、移除或修正跑不動的 CLI 指令、把版本號改成不寫死（例如 `pip install mk-qa-master`）。
3. **擴充 `tests/test_v1_doc_sync.py`**，把這幾類檢查自動化：
   - 文件裡以反引號標示的 `reference/*.md` 路徑必須存在
   - 文件裡出現的 `工具名(參數=...)` 寫法，參數名稱必須在該工具的 `inputSchema` 裡
   - 文件裡的 `mk-qa-master==X.Y.Z` 不得低於 `pyproject.toml` 的版本
4. **決定 `README.zh-TW.md` 的定位**：要持續與英文版同步，還是標明「精簡版，完整內容見英文 README」。

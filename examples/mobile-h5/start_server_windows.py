"""Windows 專用：用「繞過方式」啟動 mk-qa-master 的 MCP server。

為什麼需要：mk-qa-master 1.5.0 在 Windows 上透過 MCP 呼叫 run_tests 時會卡住
（詳見 docs/bug-reports/windows-run-tests-stdin-hang.md）。這個檔案在啟動 server
之前，先把「子行程的 stdin」預設成不繼承，其餘行為完全相同。
它不會修改 mk-qa-master 的任何檔案。

用法：在 AI 客戶端的 MCP 設定裡，把啟動指令指向這個檔案，例如：

    "command": "C:/path/to/.venv/Scripts/python.exe",
    "args": ["C:/path/to/mk-qa-master/examples/mobile-h5/start_server_windows.py"],
    "env": { "QA_RUNNER": "pytest", "QA_PROJECT_ROOT": "C:/path/to/你的測試專案" }

macOS / Linux 不需要這個檔案，照 mk-qa-master 的 README 設定即可。
"""
import subprocess

_original_run = subprocess.run


def _run_without_inherited_stdin(*args, **kwargs):
    # 呼叫端有自己給 stdin 或 input 時不干涉。
    if "input" not in kwargs:
        kwargs.setdefault("stdin", subprocess.DEVNULL)
    return _original_run(*args, **kwargs)


subprocess.run = _run_without_inherited_stdin

from mk_qa_master.server import run  # noqa: E402 — 必須在上面的設定之後才載入

if __name__ == "__main__":
    run()

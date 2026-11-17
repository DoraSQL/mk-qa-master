"""示範：像 AI 客戶端一樣，透過 MCP 呼叫 run_tests，觸發 bug report 產生。

用法（先 pip install -e 本插件）：

    python examples/demo_via_mcp.py <受測專案資料夾> [--isolate-stdin]

它會啟動一個真正的 mk-qa-master MCP server（stdio），呼叫 get_runner_info
與 run_tests，印出回應，最後列出 bug-reports/ 裡的檔案。

--isolate-stdin（Windows 上若 run_tests 卡住不回應時使用）：
    mk-qa-master 1.5.0 啟動 pytest 時沒有指定 stdin，子行程會繼承 MCP server
    的 stdin 管線。在 Windows 上這會讓 pytest 卡住。加上這個參數後，示範腳本
    會改用一小段包裝程式啟動 server：只把 subprocess.run 的 stdin 預設成
    DEVNULL，其餘完全相同。這只影響這支示範腳本，不會修改 mk-qa-master。
"""
import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RUN_TESTS_TIMEOUT_S = 180

# 以 `python -c` 執行：先讓子行程不繼承 stdin，再照常啟動 server。
ISOLATED_SERVER = """
import subprocess

_run = subprocess.run


def run(*args, **kwargs):
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    return _run(*args, **kwargs)


subprocess.run = run

from mk_qa_master.server import run as serve

serve()
"""


async def main(project_root: Path, isolate_stdin: bool = False) -> None:
    env = dict(os.environ)
    env.update(
        QA_RUNNER="pytest",
        QA_PROJECT_ROOT=str(project_root),
        MK_QA_PLUGINS="1",
    )
    # runner 是用 "pytest" 這個指令名稱啟動測試，所以要讓它在 PATH 上找得到。
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")

    args = ["-c", ISOLATED_SERVER] if isolate_stdin else ["-m", "mk_qa_master.server"]
    server = StdioServerParameters(command=sys.executable, args=args, env=env)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            info = await session.call_tool("get_runner_info", {})
            print("=== get_runner_info ===")
            print(info.content[0].text)

            try:
                result = await asyncio.wait_for(session.call_tool("run_tests", {}), RUN_TESTS_TIMEOUT_S)
            except asyncio.TimeoutError:
                print(
                    f"run_tests 超過 {RUN_TESTS_TIMEOUT_S} 秒沒有回應。"
                    "在 Windows 上請加 --isolate-stdin 再試一次（說明見檔案開頭）。"
                )
                os._exit(1)  # server 還卡在子行程上，正常關閉會一起卡住
            print("=== run_tests ===")
            print(result.content[0].text)

    out_dir = project_root / "bug-reports"
    print("=== bug-reports/ ===")
    if out_dir.is_dir():
        for path in sorted(out_dir.iterdir()):
            print(path.name)
    else:
        print("(資料夾不存在)")


if __name__ == "__main__":
    # Windows 終端機預設不是 UTF-8，直接印中文可能變亂碼或出錯。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cli = [a for a in sys.argv[1:] if a != "--isolate-stdin"]
    if len(cli) != 1:
        sys.exit(__doc__)
    asyncio.run(main(Path(cli[0]).resolve(), isolate_stdin="--isolate-stdin" in sys.argv[1:]))

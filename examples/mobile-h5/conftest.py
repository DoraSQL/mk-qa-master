"""手機 H5 測試的設定檔。

pytest 會自動讀取這個檔案（檔名一定要叫 conftest.py）。它做的事只有一件：
讓這個資料夾裡的每一個網頁測試，都用下面清單裡的每一支「手機」各跑一次。
"""
import pytest

# ============================================================================
# 手機清單：想改裝置，只要改這裡。
#
# 名稱必須和 Playwright 內建的裝置名稱一模一樣（大小寫、空格都要對）。
# 常用的名稱列在 README.md 的「怎麼換手機型號」。
# ============================================================================
DEVICES = [
    "iPhone 15",
    "Pixel 7",
]

# ---- 範例一：想換別支手機 --------------------------------------------------
# 把名稱換掉就好。例如改測比較新的機型：
#
# DEVICES = [
#     "iPhone 17",
#     "Pixel 10",
# ]

# ---- 範例二：想多加一支桌面版 ----------------------------------------------
# 在清單裡多加一行 "Desktop Chrome"。每個測試會變成跑三次，時間也變三倍：
#
# DEVICES = [
#     "iPhone 15",
#     "Pixel 7",
#     "Desktop Chrome",
# ]

# ---- 範例三：暫時只測一支 --------------------------------------------------
# 在不想跑的那一行最前面加上 # 就會被略過：
#
# DEVICES = [
#     "iPhone 15",
#     # "Pixel 7",
# ]


# ============================================================================
# 以下是讓清單生效的程式，平常不需要改。
# ============================================================================
@pytest.fixture(scope="session", params=DEVICES)
def browser_context_args(browser_context_args, playwright, request):
    """把瀏覽器設定成指定裝置的樣子：螢幕大小、觸控、手機版的瀏覽器識別字串。

    params=DEVICES 會讓 pytest 對清單裡的每個名稱各跑一輪，
    測試名稱後面也會自動標上裝置，例如 test_xxx[iPhone 15-chromium]。
    """
    name = request.param
    if name not in playwright.devices:
        raise pytest.UsageError(
            f"conftest.py 的 DEVICES 裡有 Playwright 不認得的裝置名稱：{name!r}。"
            "請確認大小寫與空格，可用名稱見 README.md 的「怎麼換手機型號」。"
        )
    return {**browser_context_args, **playwright.devices[name]}

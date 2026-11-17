"""從測試名稱辨識「模擬的裝置」。

用裝置模擬跑測試時（見 examples/mobile-h5），pytest 會把裝置名稱放在測試名稱
後面的中括號裡，例如：

    test_shop_page.py::test_buy_button_visible[iPhone 15-chromium]

這裡把它拆成兩部分：
    裝置       → "iPhone 15"
    去掉裝置後 → "test_shop_page.py::test_buy_button_visible[chromium]"

去掉裝置後的名稱用來判斷「是不是同一個測試在不同裝置上失敗」。
"""
from __future__ import annotations

import re

# Playwright 內建裝置名稱的開頭。中括號裡的某一段以這些字開頭，才會被當成裝置；
# 其他參數（例如 [admin-chromium] 的 admin）不會被誤認。
# 如果你用了自訂的裝置名稱，把它的開頭加進來即可（記得保留結尾的空格）。
DEVICE_PREFIXES = (
    "iPhone ",
    "iPad ",
    "Pixel ",
    "Galaxy ",
    "Nexus ",
    "Moto ",
    "Desktop ",
    "Kindle ",
    "LG ",
    "Nokia ",
    "Microsoft Lumia ",
    "BlackBerry ",
    "Blackberry ",
)

_PARAMS_RE = re.compile(r"^(?P<head>.*)\[(?P<params>[^\[\]]*)\]$", re.DOTALL)


def split_device(nodeid: str) -> tuple[str | None, str]:
    """回傳 (裝置名稱或 None, 去掉裝置後的測試名稱)。"""
    match = _PARAMS_RE.match(nodeid or "")
    if not match:
        return None, nodeid
    # pytest 用 "-" 串接多個參數；Playwright 的裝置名稱本身不含 "-"。
    parts = match.group("params").split("-")
    device = next((p for p in parts if p.startswith(DEVICE_PREFIXES)), None)
    if device is None:
        return None, nodeid
    rest = [p for p in parts if p != device]
    head = match.group("head")
    return device, f"{head}[{'-'.join(rest)}]" if rest else head

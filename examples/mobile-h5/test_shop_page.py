"""範例測試：一個簡單的商品頁，用手機瀏覽器的樣子檢查。

為了不需要網路，網頁內容直接寫在下面的 SHOP_HTML 裡。
實際測自己的網站時，把 page.set_content(SHOP_HTML) 換成
page.goto("https://你的網站") 即可。

這一頁故意留了一個手機版常見的問題：比價表格的寬度寫死成 800px，
比手機螢幕還寬，整個頁面會被撐出左右捲軸。
"""
from playwright.sync_api import Page, expect

SHOP_HTML = """
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>小舖｜商品頁</title>
  <style>
    body { margin: 0; font-family: sans-serif; }
    header { padding: 12px; background: #222; color: #fff; }
    .buy { display: block; width: 90%; margin: 16px auto; padding: 14px; font-size: 18px; }
    /* 問題在這裡：表格寬度寫死，沒有跟著螢幕縮小 */
    table.compare { width: 800px; border-collapse: collapse; }
    table.compare td { border: 1px solid #ccc; padding: 8px; }
  </style>
</head>
<body>
  <header><h1>小舖</h1></header>
  <button class="buy">加入購物車</button>
  <table class="compare">
    <tr><td>方案</td><td>月費</td><td>流量</td><td>合約</td></tr>
    <tr><td>輕量</td><td>199</td><td>5GB</td><td>12 個月</td></tr>
    <tr><td>標準</td><td>399</td><td>20GB</td><td>24 個月</td></tr>
  </table>
</body>
</html>
"""


def test_buy_button_visible(page: Page):
    """打開商品頁後，應該看得到「加入購物車」按鈕"""
    page.set_content(SHOP_HTML)
    expect(page.get_by_role("button", name="加入購物車")).to_be_visible()


def test_no_horizontal_scroll(page: Page):
    """頁面內容不應該比螢幕寬（不應出現左右捲軸）"""
    page.set_content(SHOP_HTML)
    # 螢幕可用寬度要用 clientWidth 來量。不能用 window.innerWidth：手機瀏覽器遇到
    # 過寬的內容時，innerWidth 會跟著被撐大，兩個數字永遠相等，就抓不到問題了。
    screen_width = page.evaluate("() => document.documentElement.clientWidth")
    page_width = page.evaluate("() => document.documentElement.scrollWidth")
    assert page_width <= screen_width, "頁面內容比螢幕寬，手機上會出現左右捲軸"

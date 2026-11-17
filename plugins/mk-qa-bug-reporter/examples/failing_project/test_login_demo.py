"""故意會失敗的範例測試，用來示範 bug report 長什麼樣子。

情境：登入頁的按鈕文字從「登入」被改成「Sign in」，頁面標題也沒照規格寫。
- 兩個測試都卡在「找不到『登入』按鈕」 → 同一個錯誤，應合併成一份報告
- 一個測試發現標題不對              → 另一份報告
- 一個測試通過                      → 不產生報告

頁面內容直接寫在測試裡（page.set_content），不需要網路。
"""
from playwright.sync_api import Page, expect

LOGIN_HTML = """
<html>
  <head><title>Login</title></head>
  <body>
    <h1>會員登入</h1>
    <input aria-label="帳號" /><input aria-label="密碼" type="password" />
    <button>Sign in</button>
  </body>
</html>
"""


def click_login(page: Page) -> None:
    page.get_by_role("button", name="登入").click(timeout=1000)


def test_login_with_password(page: Page):
    """輸入帳號密碼後按「登入」應能送出表單"""
    page.set_content(LOGIN_HTML)
    page.get_by_label("帳號").fill("dora")
    page.get_by_label("密碼").fill("secret")
    click_login(page)


def test_login_with_empty_form(page: Page):
    """不填資料直接按「登入」應能觸發驗證"""
    page.set_content(LOGIN_HTML)
    click_login(page)


def test_page_title(page: Page):
    """登入頁的瀏覽器標題應為「會員登入」"""
    page.set_content(LOGIN_HTML)
    expect(page).to_have_title("會員登入", timeout=1000)


def test_heading_visible(page: Page):
    """登入頁應顯示「會員登入」大標題"""
    page.set_content(LOGIN_HTML)
    expect(page.get_by_role("heading", name="會員登入")).to_be_visible()

"""구글 메시지 웹 - Playwright"""

from playwright.sync_api import sync_playwright
from pathlib import Path

PROFILE = Path(__file__).parent / "gmsg_profile"
PROFILE.mkdir(exist_ok=True)

pw = sync_playwright().start()
ctx = pw.chromium.launch_persistent_context(
    str(PROFILE),
    headless=False,
    viewport=None,
    args=["--app=https://messages.google.com/web"]
)

page = ctx.pages[0] if ctx.pages else ctx.new_page()
print("구글 메시지 실행됨. 창 닫으면 종료.")

try:
    while True:
        page.wait_for_timeout(1000)
        page.evaluate("1")
except:
    pass

ctx.close()
pw.stop()

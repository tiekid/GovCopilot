from pathlib import Path

from playwright.sync_api import sync_playwright
from config import VB_URL

PROFILE_DIR = Path("profile")


def open_browser():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            slow_mo=200,
        )

        # Dùng tab đã có sẵn nếu có, không tạo thêm tab mới
        page = context.pages[0] if context.pages else context.new_page()

        page.goto(VB_URL, wait_until="networkidle")

        print("=" * 50)
        print("Nếu đây là lần đầu:")
        print("- Đăng nhập thủ công")
        print("- Sau khi vào được hệ thống, quay lại Terminal")
        print("- Nhấn Enter để lưu phiên đăng nhập")
        print("=" * 50)

        input()

        context.close()


if __name__ == "__main__":
    open_browser()
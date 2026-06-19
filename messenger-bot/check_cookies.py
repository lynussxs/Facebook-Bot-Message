"""
Kiểm tra nhanh file fb_cookies.json có hợp lệ không.
Chạy: python3 messenger-bot/check_cookies.py
"""

import asyncio
import json
import os
import sys

COOKIES_FILE = os.path.join(os.path.dirname(__file__), "fb_cookies.json")


def check_file() -> None:
    if not os.path.isfile(COOKIES_FILE):
        print(f"❌  File không tồn tại: {COOKIES_FILE}")
        print("    Làm theo README để export cookies từ trình duyệt.")
        sys.exit(1)

    try:
        with open(COOKIES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌  File JSON không hợp lệ: {e}")
        sys.exit(1)

    if not isinstance(data, list) or len(data) == 0:
        print("❌  Cookies phải là một mảng JSON không rỗng.")
        sys.exit(1)

    # Check for essential FB cookies
    names = {c.get("name", "") for c in data}
    required = {"c_user", "xs"}
    missing = required - names
    if missing:
        print(f"⚠️   Thiếu cookies quan trọng: {', '.join(missing)}")
        print("    Hãy export cookies khi đang đăng nhập Facebook, không phải khi đã logout.")
    else:
        print(f"✅  Tìm thấy {len(data)} cookies — có đủ c_user và xs.")

    # Try to extract user ID
    c_user = next((c for c in data if c.get("name") == "c_user"), None)
    if c_user:
        print(f"✅  Facebook UID từ cookie: {c_user.get('value', '???')}")


async def try_login() -> None:
    try:
        import fbchat_muqit as fbchat
    except ImportError:
        print("❌  fbchat_muqit chưa được cài. Chạy: pip install fbchat-muqit")
        return

    print("\n🔑  Thử đăng nhập với cookies…")
    try:
        async with fbchat.Client(cookies_file_path=COOKIES_FILE) as client:
            print(f"✅  Đăng nhập thành công!")
            print(f"    UID : {client.uid}")
            print(f"    Tên : {client.name}")
    except fbchat.exception.errors.AuthenticationError as e:
        print(f"❌  Lỗi xác thực: {e}")
        print("    Cookies đã hết hạn hoặc không hợp lệ. Export cookies mới.")
    except Exception as e:
        print(f"❌  Lỗi khi đăng nhập: {e}")


if __name__ == "__main__":
    check_file()
    asyncio.run(try_login())

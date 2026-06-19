# Messenger → Discord Forwarder Bot

Bot tự động forward tin nhắn từ một nhóm Messenger sang kênh Discord qua Webhook.

## Cách hoạt động

1. Bot đọc Facebook session từ file cookies (`fb_cookies.json`).
2. Kết nối MQTT real-time của Facebook để nhận tin nhắn.
3. Chỉ xử lý tin nhắn từ `FB_THREAD_ID` chỉ định.
4. Bỏ qua tin nhắn của chính bot.
5. Forward sang Discord dưới dạng embed đẹp (tên người gửi + thời gian + nội dung).
6. Tự động reconnect nếu mất kết nối.

---

## BƯỚC 1 — Export cookies Facebook (BẮT BUỘC)

Bot dùng cookies thay vì email/password để tránh bị checkpoint.

### Cách lấy cookies:

1. Cài extension **"EditThisCookie"** hoặc **"Cookie-Editor"** trên Chrome/Firefox.
2. Mở `https://www.facebook.com` → đăng nhập bằng tài khoản bot.
3. Mở extension → **Export** → chọn format **JSON**.
4. Copy toàn bộ nội dung JSON.
5. Tạo file `messenger-bot/fb_cookies.json` trong Replit Shell:
   ```bash
   nano messenger-bot/fb_cookies.json
   ```
   Paste nội dung JSON vào → Ctrl+X → Y → Enter.

> **Lưu ý:** File `fb_cookies.json` phải ở trong thư mục `messenger-bot/`.  
> Cookies thường hết hạn sau 30–90 ngày, cần export lại khi bot bị lỗi đăng nhập.

---

## BƯỚC 2 — Điền Secrets trong Replit

| Secret           | Giá trị                                              |
|------------------|------------------------------------------------------|
| `DISCORD_WEBHOOK`| URL Webhook Discord (Channel Settings → Integrations → Webhooks) |
| `FB_THREAD_ID`   | ID nhóm chat Messenger (xem hướng dẫn bên dưới)      |

### Cách lấy `FB_THREAD_ID`:
1. Mở Facebook trên trình duyệt → vào nhóm chat lớp.
2. URL dạng: `https://www.facebook.com/messages/t/123456789`
3. Số `123456789` chính là `FB_THREAD_ID`.

### Cách lấy Discord Webhook URL:
1. Vào kênh Discord muốn nhận tin → **Edit Channel** → **Integrations** → **Webhooks**.
2. Tạo webhook mới → **Copy Webhook URL**.

---

## BƯỚC 3 — Chạy bot

Sau khi có `fb_cookies.json` và điền Secrets xong:

```bash
# Kiểm tra cookies hợp lệ trước
python3 messenger-bot/check_cookies.py

# Chạy bot (hoặc dùng workflow "Messenger Bot" trong Replit)
python3 messenger-bot/bot.py
```

---

## Logs

Bot log rõ ràng ra console:
```
✅  Logged in — UID: xxx | Name: Tên Bot
🎯  Watching thread: 24410875481904121
📡  Listening for messages… (Ctrl+C to stop)
📩  [Nguyen Van A]: Ơi mọi người ơi…
✅  Forwarded [Nguyen Van A]: Ơi mọi người ơi…
```

---

## Xử lý sự cố

| Lỗi                              | Nguyên nhân                        | Cách fix                              |
|----------------------------------|------------------------------------|---------------------------------------|
| `Cookie file not found`          | Chưa tạo `fb_cookies.json`         | Làm BƯỚC 1                            |
| `AuthenticationError`            | Cookies hết hạn hoặc sai           | Export cookies mới                    |
| `SessionExpiredError`            | Session bị Facebook thu hồi       | Export cookies mới, đổi IP nếu cần   |
| Bot không nhận được tin nhắn     | Sai `FB_THREAD_ID`                 | Kiểm tra lại ID trong URL             |
| Bot forward tin của chính mình   | Không xảy ra — đã lọc             | —                                     |

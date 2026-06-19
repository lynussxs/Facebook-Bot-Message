# Messenger → Discord Forwarder Bot

Bot tự động forward tin nhắn từ một nhóm Messenger sang kênh Discord qua Webhook.

## Cách hoạt động

1. Bot đăng nhập vào tài khoản Facebook bằng email + password.
2. Lắng nghe (long-polling) toàn bộ tin nhắn đến.
3. Chỉ xử lý tin nhắn từ `FB_THREAD_ID` được chỉ định.
4. Bỏ qua tin nhắn của chính bot.
5. Forward sang Discord dưới dạng embed đẹp (tên người gửi + thời gian + nội dung).
6. Tự động reconnect nếu mất kết nối (exponential backoff, tối đa 5 phút).

## Cài đặt biến môi trường

Điền vào **Replit Secrets** (hoặc file `.env` nếu chạy local):

| Biến             | Mô tả                                                  |
|------------------|--------------------------------------------------------|
| `FB_EMAIL`       | Email tài khoản Facebook bot                           |
| `FB_PASSWORD`    | Mật khẩu tài khoản Facebook bot                        |
| `DISCORD_WEBHOOK`| URL Webhook của kênh Discord nhận tin                  |
| `FB_THREAD_ID`   | ID nhóm chat Messenger (xem hướng dẫn bên dưới)        |

### Cách lấy `FB_THREAD_ID`

1. Mở Facebook trên trình duyệt → vào nhóm chat lớp.
2. Nhìn URL dạng: `https://www.facebook.com/messages/t/123456789`
3. Số `123456789` chính là `FB_THREAD_ID`.

### Cách lấy Discord Webhook URL

1. Vào kênh Discord muốn nhận tin → **Edit Channel** → **Integrations** → **Webhooks**.
2. Tạo webhook mới → **Copy Webhook URL**.

## Chạy bot

```bash
cd messenger-bot
pip install -r requirements.txt
python bot.py
```

Trên Replit: workflow **"Messenger Bot"** tự động cài deps và chạy bot.

## Lưu ý quan trọng

- Tài khoản Facebook bot **dễ bị checkpoint** (yêu cầu xác minh) nếu đăng nhập từ IP mới.  
  → Nên đăng nhập thủ công một lần trên Replit Shell trước: `python -c "import fbchat; fbchat.Client('email', 'pass')"`.
- Nếu bị checkpoint, Facebook sẽ yêu cầu xác minh qua email/SMS — cần xử lý thủ công.
- `fbchat-muqit` sử dụng cookie session; sau lần đăng nhập đầu, bot hoạt động ổn định hơn.
- Chỉ nên dùng **tài khoản phụ** (bot account), không dùng tài khoản chính.

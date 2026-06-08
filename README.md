# 🍀 Lô Đề Telegram Bot — DEMO (Sandbox)

Bot Telegram mô phỏng game lô đề **MIỀN BẮC**, dùng kết quả XSMB thật để đối chiếu, nhưng **mọi giao dịch chỉ là DEMO** — không có tiền thật, không có thanh toán thật.

Triển khai trên **Render Background Worker** (Python).

---

## 1. Tính năng

- `/start` – Hiện ID Telegram, link Room TX, menu chính (Inline Keyboard).
- `/xsmb` – Lấy kết quả XSMB hôm nay từ web, hiển thị dạng bảng.
- `🎮 Đánh Lô Đề` – Hướng dẫn thể lệ & tỉ lệ.
- Lệnh chơi DEMO:
  - `/lo <số> <điểm>` – Đánh lô (x80)
  - `/de <số> <điểm>` – Đánh đề (x90)
  - `/xienhai <s1> <s2> <điểm>` – Lô xiên 2 (x15)
  - `/xienba <s1> <s2> <s3> <điểm>` – Lô xiên 3 (x40)
  - `/xienbon <s1> <s2> <s3> <s4> <điểm>` – Lô xiên 4 (x100)
- Tỉ lệ điểm: Lô = 23.000₫ / điểm, Đề & Xiên = 1.000₫ / điểm.
- Ví DEMO khởi tạo **50.000₫** cho user mới.
- Bot **tự động đối chiếu KQXS** sau mỗi 5 phút và gửi thông báo thắng/thua.
- Menu Tài khoản: ID, số dư demo, thống kê, lịch sử chơi / nạp / rút.
- Nạp/Rút: chỉ thông báo "chế độ DEMO".

---

## 2. Cấu trúc dự án

```
.
├── bot.py            # Logic bot (handlers + scheduler)
├── database.py       # SQLite helpers
├── requirements.txt
├── render.yaml       # Cấu hình Render Background Worker
├── .env.example
├── lode.db           # (tự sinh khi chạy lần đầu)
└── README.md
```

---

## 3. Chạy local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Sửa BOT_TOKEN trong .env
python -u bot.py
```

---

## 4. Deploy lên Render

### Cách A — Dùng `render.yaml` (Blueprint)

1. Push code lên GitHub.
2. Vào Render → **New → Blueprint** → chọn repo.
3. Render đọc `render.yaml` và tạo dịch vụ **Background Worker**.
4. Tại tab **Environment**, set `BOT_TOKEN` (lấy từ [@BotFather](https://t.me/BotFather)).
5. Deploy. Log sẽ hiện `Bot khởi động (long polling)...`.

### Cách B — Tạo thủ công

- New → **Background Worker**
- Runtime: **Python 3**
- Build command: `pip install -r requirements.txt`
- Start command: `python -u bot.py`
- Env vars:
  - `BOT_TOKEN` = token bot
  - `ROOM_TX_URL` = `https://t.me/xombaoref`
  - `DB_PATH` = `lode.db`

> ⚠️ Render free tier: filesystem **ephemeral** — DB SQLite sẽ mất khi deploy lại. Để giữ dữ liệu, gắn **Render Disk** (paid) hoặc đổi sang Postgres.

---

## 5. Disclaimer

Dự án mang tính **giáo dục / demo / sandbox**.
- Không có tiền thật.
- Không khuyến khích đánh bạc.
- Đánh bạc trái phép có thể vi phạm pháp luật tại quốc gia của bạn.

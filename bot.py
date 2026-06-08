"""
Telegram bot lô đề DEMO (sandbox / không tiền thật).
Chạy trên Render Background Worker:  python bot.py
"""
import os
import re
import logging
import asyncio
import sys
from datetime import datetime, date, timedelta

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

import database as db

# ------------------------------------------------------------------ setup
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ROOM_TX_URL = os.getenv("ROOM_TX_URL", "https://t.me/xombaoref")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger("lode-bot")

# ---------------- Tỉ lệ ăn ----------------
RATE = {
    "lo": 80,
    "de": 90,
    "xienhai": 15,
    "xienba": 40,
    "xienbon": 100,
}
# Tiền cho 1 điểm
POINT_VALUE = {
    "lo": 23_000,
    "de": 1_000,
    "xienhai": 1_000,
    "xienba": 1_000,
    "xienbon": 1_000,
}


# ------------------------------------------------------------------ XSMB
def _today_str() -> str:
    return date.today().isoformat()


def fetch_xsmb(d: date | None = None) -> dict | None:
    """Scrape kết quả XSMB từ xskt.com.vn. Trả về dict hoặc None."""
    d = d or date.today()
    log.info("Đang lấy KQXS ngày %s", d.isoformat())
    cached = db.get_xsmb(d.isoformat())
    if cached and cached["all_numbers"]:
        return {
            "date": d.isoformat(),
            "special": cached["special"],
            "all_numbers": cached["all_numbers"].split(","),
            "cached": True,
        }

    url = "https://xskt.com.vn/xsmb"
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 lode-demo-bot"},
            timeout=20,
        )
        r.raise_for_status()
    except Exception as e:
        log.warning("XSMB fetch lỗi: %s", e)
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", class_="table-result") or soup.find("table")
    if not table:
        return None

    # lấy tất cả số trong bảng
    numbers = []
    special = ""
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        label = cells[0].get_text(strip=True).lower()
        for cell in cells[1:]:
            txt = cell.get_text(" ", strip=True)
            for n in re.findall(r"\d+", txt):
                numbers.append(n)
                if "đặc biệt" in label and not special:
                    special = n

    if not numbers:
        return None

    # 2 số cuối
    last2 = [n[-2:].zfill(2) for n in numbers if len(n) >= 2]
    db.save_xsmb(d.isoformat(), special, last2)
    return {
        "date": d.isoformat(),
        "special": special,
        "all_numbers": last2,
        "cached": False,
    }


def format_xsmb(data: dict) -> str:
    nums = data["all_numbers"]
    lines = [
        f"🎯 *KẾT QUẢ XSMB - {data['date']}*",
        "━━━━━━━━━━━━━━━━━━━",
        f"🏆 *ĐB:* `{data.get('special','--')}`",
        "━━━━━━━━━━━━━━━━━━━",
        "📋 *2 số cuối (27 giải):*",
    ]
    # chia 5 cột
    row = []
    for i, n in enumerate(nums, 1):
        row.append(f"`{n}`")
        if i % 5 == 0:
            lines.append("  ".join(row))
            row = []
    if row:
        lines.append("  ".join(row))
    return "\n".join(lines)


# ------------------------------------------------------------------ Menus
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Đánh Lô Đề", callback_data="menu_play")],
        [InlineKeyboardButton("👤 Tài Khoản", callback_data="menu_account")],
        [InlineKeyboardButton("💳 Nạp (Demo)", callback_data="menu_deposit"),
         InlineKeyboardButton("💸 Rút (Demo)", callback_data="menu_withdraw")],
        [InlineKeyboardButton("🆘 Hỗ Trợ", callback_data="menu_support")],
    ])


def account_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Lịch sử chơi", callback_data="hist_bet")],
        [InlineKeyboardButton("💳 Lịch sử nạp demo", callback_data="hist_dep"),
         InlineKeyboardButton("💸 Lịch sử rút demo", callback_data="hist_wd")],
        [InlineKeyboardButton("⬅️ Về menu", callback_data="back_main")],
    ])


# ------------------------------------------------------------------ handlers
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    log.info("Nhận /start từ user_id=%s", update.effective_user.id if update.effective_user else "unknown")
    u = update.effective_user
    db.get_or_create_user(u.id, u.username)
    txt = (
        f"🎫 *ID của bạn là* `{u.id}`\n\n"
        f"👉 Tham gia *Room TX* để nhận thông báo:\n{ROOM_TX_URL}\n\n"
        "Chọn chức năng bên dưới:"
    )
    await update.message.reply_text(
        txt, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_kb()
    )


async def cmd_xsmb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    log.info("Nhận /xsmb từ user_id=%s", update.effective_user.id if update.effective_user else "unknown")
    await update.message.chat.send_action("typing")
    data = fetch_xsmb()
    if not data:
        await update.message.reply_text("⚠️ Chưa lấy được KQXS hôm nay, thử lại sau.")
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎮 Đánh đề", callback_data="menu_play")]])
    await update.message.reply_text(
        format_xsmb(data), parse_mode=ParseMode.MARKDOWN, reply_markup=kb
    )


HELP_PLAY = (
    "🍀 *LÔ ĐỀ TELEGRAM* 🍀\n\n"
    "🔖 *Thể lệ:*\n"
    "👉 Kết quả được xác định thông qua *KẾT QUẢ XỔ SỐ MIỀN BẮC* ngày hôm đó.\n\n"
    "Lô ➤ x80\n"
    "Đề ➤ x90\n"
    "Lô Xiên 2 ➤ x15\n"
    "Lô Xiên 3 ➤ x40\n"
    "Lô Xiên 4 ➤ x100\n\n"
    "👉 *Tỉ lệ điểm:*\n"
    "Lô ➤ 1 điểm ➤ 23.000₫\n"
    "Đề ➤ 1 điểm ➤ 1.000₫\n"
    "Lô Xiên ➤ 1 điểm ➤ 1.000₫\n\n"
    "🎮 *Cách chơi:*\n"
    "`/lo 27 5`       → đánh lô 27, 5 điểm\n"
    "`/de 32 5`       → đánh đề 32, 5 điểm\n"
    "`/xienhai 12 34 3`     → xiên 2: 12-34, 3 điểm\n"
    "`/xienba 12 34 56 2`   → xiên 3, 2 điểm\n"
    "`/xienbon 12 34 56 78 1` → xiên 4, 1 điểm\n\n"
    "_Mọi giao dịch chỉ là DEMO, không phải tiền thật._"
)


async def cb_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    u = q.from_user
    db.get_or_create_user(u.id, u.username)

    if data == "menu_play":
        await q.message.reply_text(HELP_PLAY, parse_mode=ParseMode.MARKDOWN)

    elif data == "menu_account":
        await send_account(q.message, u.id)

    elif data in ("menu_deposit", "menu_withdraw"):
        await q.message.reply_text(
            "💎 *Đây là chế độ DEMO*\nChưa hỗ trợ nạp/rút thật.",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "menu_support":
        await q.message.reply_text(
            f"🆘 Hỗ trợ: tham gia room {ROOM_TX_URL}"
        )

    elif data == "back_main":
        await q.message.reply_text("Menu chính:", reply_markup=main_menu_kb())

    elif data == "hist_bet":
        rows = db.user_bet_history(u.id, 10)
        if not rows:
            await q.message.reply_text("Chưa có lịch sử chơi.")
        else:
            lines = ["📜 *Lịch sử chơi gần nhất:*"]
            for r in rows:
                lines.append(
                    f"#{r['id']} {r['bet_type'].upper()} {r['numbers']} "
                    f"| {r['points']}đ | {r['amount']:,}₫ | {r['status']}"
                )
            await q.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    elif data in ("hist_dep", "hist_wd"):
        kind = "deposit" if data == "hist_dep" else "withdraw"
        rows = db.demo_txn_history(u.id, kind, 10)
        if not rows:
            await q.message.reply_text("Chưa có giao dịch (DEMO).")
        else:
            lines = [f"*Lịch sử {kind} (demo):*"]
            for r in rows:
                lines.append(f"#{r['id']} {r['amount']:,}₫ — {r['created_at'][:19]}")
            await q.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def send_account(message, user_id: int):
    user = db.get_user(user_id)
    stats = db.user_bet_stats(user_id)
    txt = (
        f"🎩 *ID:* `{user_id}`\n"
        f"💎 *Số dư demo:* `{user['balance']:,}₫`\n"
        f"👑 *Cấp Vip:* demo\n\n"
        f"– Tổng lượt chơi: *{stats['total']}*\n"
        f"– Chơi hôm nay: *{stats['today']}*\n"
        f"– Tổng nạp demo: *{user['total_deposit']:,}₫*\n"
        f"– Tổng rút demo: *{user['total_withdraw']:,}₫*\n"
        f"– Ngày tham gia: *{user['joined_at'][:10]}*"
    )
    await message.reply_text(
        txt, parse_mode=ParseMode.MARKDOWN, reply_markup=account_menu_kb()
    )


# ----------------- bet commands -----------------
def _parse_int(s: str) -> int | None:
    try:
        return int(s)
    except Exception:
        return None


async def _place_bet(update: Update, ctx, bet_type: str, required_nums: int | None):
    """required_nums=None nghĩa là cần đúng 1 số (lo/de). =2/3/4 cho xiên."""
    u = update.effective_user
    user = db.get_or_create_user(u.id, u.username)
    args = ctx.args or []

    if required_nums is None:
        if len(args) != 2:
            await update.message.reply_text(
                f"Cú pháp: /{bet_type} <số> <điểm>\nVí dụ: /{bet_type} 32 5"
            )
            return
        nums_raw = [args[0]]
        points = _parse_int(args[1])
    else:
        if len(args) != required_nums + 1:
            await update.message.reply_text(
                f"Cú pháp: /{bet_type} " +
                " ".join([f"<số{i+1}>" for i in range(required_nums)]) +
                " <điểm>"
            )
            return
        nums_raw = args[:required_nums]
        points = _parse_int(args[-1])

    # validate
    if points is None or points <= 0:
        await update.message.reply_text("Số điểm phải là số nguyên dương.")
        return
    nums = []
    for n in nums_raw:
        if not re.fullmatch(r"\d{1,2}", n):
            await update.message.reply_text(f"Số không hợp lệ: {n}")
            return
        nums.append(n.zfill(2))
    if len(set(nums)) != len(nums):
        await update.message.reply_text("Các số xiên phải khác nhau.")
        return

    amount = points * POINT_VALUE[bet_type]
    if user["balance"] < amount:
        await update.message.reply_text(
            f"❌ Số dư demo không đủ. Cần {amount:,}₫, hiện có {user['balance']:,}₫."
        )
        return

    db.update_balance(u.id, -amount)
    bet_id = db.add_bet(
        u.id, bet_type, ",".join(nums), points, amount, _today_str()
    )
    new_bal = db.get_user(u.id)["balance"]

    pretty_type = {
        "lo": "Lô", "de": "Đề",
        "xienhai": "Xiên 2", "xienba": "Xiên 3", "xienbon": "Xiên 4",
    }[bet_type]
    await update.message.reply_text(
        f"✅ *Đặt cược mô phỏng thành công!*\n"
        f"{pretty_type} — `{'-'.join(nums)}`\n"
        f"Điểm: *{points}* | Tiền: *{amount:,}₫*\n"
        f"Số dư demo: *{new_bal:,}₫*\n"
        f"_Mã cược #{bet_id} — sẽ đối chiếu sau khi có KQXS._",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_lo(update, ctx):       await _place_bet(update, ctx, "lo",       None)
async def cmd_de(update, ctx):       await _place_bet(update, ctx, "de",       None)
async def cmd_xienhai(update, ctx):  await _place_bet(update, ctx, "xienhai",  2)
async def cmd_xienba(update, ctx):   await _place_bet(update, ctx, "xienba",   3)
async def cmd_xienbon(update, ctx):  await _place_bet(update, ctx, "xienbon",  4)


# ----------------- settle -----------------
async def settle_for_date(app: Application, d: date):
    data = fetch_xsmb(d)
    if not data:
        log.info("Chưa có KQXS %s để đối chiếu", d)
        return
    last2 = set(data["all_numbers"])
    special_last2 = (data["special"] or "")[-2:].zfill(2) if data["special"] else ""

    pending = db.pending_bets_for_date(d.isoformat())
    log.info("Đối chiếu %d cược ngày %s", len(pending), d)

    for b in pending:
        nums = b["numbers"].split(",")
        bt = b["bet_type"]
        win = False
        win_amount = 0

        if bt == "lo":
            n = nums[0]
            hits = sum(1 for x in data["all_numbers"] if x == n)
            if hits:
                win = True
                win_amount = b["points"] * RATE["lo"] * 1000 * hits
        elif bt == "de":
            if nums[0] == special_last2:
                win = True
                win_amount = b["points"] * RATE["de"] * 1000
        elif bt in ("xienhai", "xienba", "xienbon"):
            if all(n in last2 for n in nums):
                win = True
                win_amount = b["points"] * RATE[bt] * 1000

        status = "won" if win else "lost"
        db.settle_bet(b["id"], status, win_amount)
        if win:
            db.update_balance(b["user_id"], win_amount)

        new_bal = db.get_user(b["user_id"])["balance"]
        pretty = bt.upper()
        emoji = "🎉" if win else "❌"
        head = "THẮNG" if win else "THUA"
        text = (
            f"{emoji} *{head} (DEMO)*\n"
            f"{pretty} — `{'-'.join(nums)}`\n"
            f"Tiền cược: *{b['amount']:,}₫*\n"
            f"Tiền thắng: *{win_amount:,}₫*\n"
            f"Số dư mới: *{new_bal:,}₫*"
        )
        try:
            await app.bot.send_message(
                b["user_id"], text, parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            log.warning("Không gửi được thông báo cho %s: %s", b["user_id"], e)


async def settle_job(ctx: ContextTypes.DEFAULT_TYPE):
    await settle_for_date(ctx.application, date.today())
    # cả hôm qua phòng khi chậm
    await settle_for_date(ctx.application, date.today() - timedelta(days=1))


async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.exception("Lỗi khi xử lý update: %s", update, exc_info=ctx.error)


async def post_init(app: Application):
    me = await app.bot.get_me()
    log.info("Đã kết nối Telegram: @%s (id=%s)", me.username, me.id)
    # Xóa webhook cũ nếu trước đó từng deploy kiểu webhook; long polling cần bước này.
    await app.bot.delete_webhook(drop_pending_updates=True)
    log.info("Đã bật long polling. Hãy nhắn /start hoặc /xsmb cho @%s", me.username)


# ------------------------------------------------------------------ main
def _ensure_event_loop():
    """Python 3.12+ không tự tạo event loop cho MainThread.
    PTB <22 gọi asyncio.get_event_loop() và sẽ raise RuntimeError.
    Hàm này đảm bảo luôn có 1 loop khả dụng."""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)


def main():
    if not BOT_TOKEN:
        raise SystemExit("Thiếu BOT_TOKEN trong biến môi trường.")
    db.init_db()
    _ensure_event_loop()

    log.info("Khởi động bot với Python %s", sys.version.split()[0])
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("xsmb", cmd_xsmb))
    app.add_handler(CommandHandler("lo", cmd_lo))
    app.add_handler(CommandHandler("de", cmd_de))
    app.add_handler(CommandHandler("xienhai", cmd_xienhai))
    app.add_handler(CommandHandler("xienba", cmd_xienba))
    app.add_handler(CommandHandler("xienbon", cmd_xienbon))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_error_handler(error_handler)

    # job đối chiếu mỗi 5 phút
    if app.job_queue:
        app.job_queue.run_repeating(settle_job, interval=300, first=30)

    log.info("Bot khởi động (long polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()

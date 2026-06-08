"""
Telegram bot lô đề DEMO (sandbox / không tiền thật).
Chạy trên Render Background Worker:  python bot.py
"""
import os
import re
import logging
import asyncio
import sys
from datetime import datetime, date, time as dtime, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
# Giờ công bố KQXS miền Bắc (18:35 VN). Trước giờ này hiển thị KQ hôm qua.
RESULT_TIME_VN = dtime(18, 35, tzinfo=VN_TZ)

def vn_now() -> datetime:
    return datetime.now(VN_TZ)

def vn_today() -> date:
    return vn_now().date()

def latest_result_date() -> date:
    """Trả về ngày kết quả mới nhất hiện có. Sau 18:35 VN -> hôm nay, trước -> hôm qua."""
    now = vn_now()
    cutoff = now.replace(hour=18, minute=35, second=0, microsecond=0)
    return now.date() if now >= cutoff else (now.date() - timedelta(days=1))

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
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
    return vn_today().isoformat()


# Thứ tự + nhãn các giải XSMB (chuẩn 27 giải)
PRIZE_ORDER = [
    ("special", "🏆 Đặc Biệt", 1),
    ("g1",      "🥇 Giải nhất", 1),
    ("g2",      "🥈 Giải nhì", 2),
    ("g3",      "🥉 Giải ba", 6),
    ("g4",      "🎖 Giải tư", 4),
    ("g5",      "🎯 Giải năm", 6),
    ("g6",      "🎲 Giải sáu", 3),
    ("g7",      "🍀 Giải bảy", 4),
]
# Map nhãn HTML tiếng Việt -> key
LABEL_MAP = {
    "đặc biệt": "special", "giải đặc biệt": "special", "đb": "special", "db": "special",
    "giải nhất": "g1", "nhất": "g1", "g1": "g1",
    "giải nhì": "g2", "nhì": "g2", "g2": "g2",
    "giải ba": "g3", "ba": "g3", "g3": "g3",
    "giải tư": "g4", "tư": "g4", "g4": "g4",
    "giải năm": "g5", "năm": "g5", "g5": "g5",
    "giải sáu": "g6", "sáu": "g6", "g6": "g6",
    "giải bảy": "g7", "bảy": "g7", "g7": "g7",
}


def _empty_prizes() -> dict:
    return {key: [] for key, _, _ in PRIZE_ORDER}


def fetch_xsmb(d: date | None = None, force: bool = False) -> dict | None:
    """Scrape kết quả XSMB từ xskt.com.vn theo từng giải, cho ngày `d`."""
    d = d or latest_result_date()
    log.info("Đang lấy KQXS ngày %s (force=%s)", d.isoformat(), force)

    # Có cache thì dùng (trừ khi force refresh)
    if not force:
        cached = db.get_xsmb(d.isoformat())
        if cached and cached.get("all_numbers"):
            import json
            prizes_raw = cached.get("raw_json")
            prizes = None
            if prizes_raw:
                try:
                    prizes = json.loads(prizes_raw)
                except Exception:
                    prizes = None
            # Chỉ dùng cache nếu có đủ prizes (đã lưu kiểu mới)
            if prizes and prizes.get("special"):
                return {
                    "date": d.isoformat(),
                    "special": cached["special"],
                    "all_numbers": cached["all_numbers"].split(",") if isinstance(cached["all_numbers"], str) else cached["all_numbers"],
                    "prizes": prizes,
                    "cached": True,
                }

    # URL theo ngày: /xsmb/dd-mm-yyyy ; nếu là hôm nay dùng URL gốc cho chắc
    if d == vn_today():
        url = "https://xskt.com.vn/xsmb"
    else:
        url = f"https://xskt.com.vn/xsmb/{d.strftime('%d-%m-%Y')}"

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

    prizes = _empty_prizes()
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label = re.sub(r"\s+", " ", cells[0].get_text(" ", strip=True)).lower().strip(": ")
        key = LABEL_MAP.get(label)
        if not key:
            # đôi khi label kèm "DB" / "ĐB"
            if "đặc biệt" in label or label in ("db", "đb"):
                key = "special"
            else:
                continue
        # Chỉ lấy cột giải (cell[1]). Bỏ qua các cột đầu/đuôi.
        txt = cells[1].get_text(" ", strip=True)
        for n in re.findall(r"\d{2,6}", txt):
            prizes[key].append(n)

    if not prizes["special"]:
        log.warning("Không parse được giải đặc biệt cho ngày %s", d)
        return None

    # 2 số cuối tất cả các giải -> phục vụ đối chiếu lô/xiên
    all_numbers = [n for key, _, _ in PRIZE_ORDER for n in prizes[key]]
    last2 = [n[-2:].zfill(2) for n in all_numbers if len(n) >= 2]

    import json as _json
    db.save_xsmb(d.isoformat(), prizes["special"][0], last2, raw_json=_json.dumps(prizes))

    return {
        "date": d.isoformat(),
        "special": prizes["special"][0],
        "all_numbers": last2,
        "prizes": prizes,
        "cached": False,
    }


def _fmt_date_vn(iso: str) -> str:
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return iso


def format_xsmb(data: dict) -> str:
    """Định dạng HTML (in đậm) đẹp như khách yêu cầu."""
    prizes = data.get("prizes") or {}
    lines = [
        "🎯 <b>KẾT QUẢ XỔ SỐ MIỀN BẮC</b>",
        "",
        f"📅 <b>Ngày:</b> {_fmt_date_vn(data['date'])}",
        "",
        "-------------------------",
        "",
    ]

    # Số cột mỗi giải khi xuống dòng
    cols = {"special": 1, "g1": 1, "g2": 2, "g3": 3, "g4": 4, "g5": 3, "g6": 3, "g7": 4}

    for key, label, _expected in PRIZE_ORDER:
        nums = prizes.get(key) or []
        if not nums:
            continue
        if key == "special":
            lines.append(f"{label}:  <b>{nums[0]}</b>")
            lines.append("")
            continue
        lines.append(f"{label}:")
        per = cols.get(key, 3)
        for i in range(0, len(nums), per):
            chunk = nums[i:i + per]
            lines.append(" - ".join(f"<b>{n}</b>" for n in chunk))
        lines.append("")

    lines.append("-------------------------")
    lines.append("")
    lines.append("🤖 <i>Cập nhật tự động XSMB hôm nay</i>")
    return "\n".join(lines)


# ------------------------------------------------------------------ Menus
# Nhãn bàn phím chính (reply keyboard - hiện ngay dưới ô gõ tin)
BTN_PLAY     = "🎮 Đánh Lô Đề"
BTN_XSMB     = "🎯 Xem KQXS"
BTN_ACCOUNT  = "👤 Tài Khoản"
BTN_DEPOSIT  = "💳 Nạp Tiền"
BTN_WITHDRAW = "💸 Rút Tiền"
BTN_SUPPORT  = "🆘 Hỗ Trợ"

def main_menu_kb() -> ReplyKeyboardMarkup:
    """Bàn phím chính - hiện cố định dưới ô chat."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_XSMB), KeyboardButton(BTN_PLAY)],
            [KeyboardButton(BTN_ACCOUNT)],
            [KeyboardButton(BTN_DEPOSIT), KeyboardButton(BTN_WITHDRAW)],
            [KeyboardButton(BTN_SUPPORT)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Chọn chức năng…",
    )


def account_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📜 Lịch sử chơi", callback_data="hist_bet")],
        [InlineKeyboardButton("💳 Lịch sử nạp ", callback_data="hist_dep"),
         InlineKeyboardButton("💸 Lịch sử rút ", callback_data="hist_wd")],
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
    data = fetch_xsmb()  # tự chọn ngày hợp lệ theo giờ VN
    if not data:
        await update.message.reply_text(
            "⚠️ Chưa lấy được KQXS, thử lại sau nhé.",
            reply_markup=main_menu_kb(),
        )
        return
    await update.message.reply_text(
        format_xsmb(data),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=main_menu_kb(),
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


# ----- Bàn phím chính: bắt text từ reply keyboard -----
async def menu_text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    u = update.effective_user
    db.get_or_create_user(u.id, u.username)

    if text == BTN_XSMB:
        await cmd_xsmb(update, ctx)
    elif text == BTN_PLAY:
        await update.message.reply_text(
            HELP_PLAY, parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_kb()
        )
    elif text == BTN_ACCOUNT:
        await send_account(update.message, u.id)
    elif text in (BTN_DEPOSIT, BTN_WITHDRAW):
        await update.message.reply_text(
            "💎 *Đây là chế độ DEMO*\nChưa hỗ trợ nạp/rút thật.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=main_menu_kb(),
        )
    elif text == BTN_SUPPORT:
        await update.message.reply_text(
            f"🆘 Hỗ trợ: tham gia room {ROOM_TX_URL}",
            reply_markup=main_menu_kb(),
        )
    # text khác: bỏ qua, không spam người dùng


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
    today = vn_today()
    await settle_for_date(ctx.application, today)
    # cả hôm qua phòng khi chậm
    await settle_for_date(ctx.application, today - timedelta(days=1))


async def refresh_xsmb_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Job chạy 18:35 (giờ VN) mỗi ngày để refresh KQXS mới nhất.
    Cũng được lặp lại mỗi 5 phút sau đó cho tới khi có kết quả mới."""
    d = vn_today()
    log.info("[refresh_xsmb_job] tải KQXS %s (force)", d)
    data = fetch_xsmb(d, force=True)
    if data:
        log.info("[refresh_xsmb_job] OK - ĐB %s", data["special"])
    else:
        log.info("[refresh_xsmb_job] chưa có KQ, sẽ thử lại lần sau.")


async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    err = ctx.error
    # Nhận diện lỗi Conflict: 2 instance cùng long-polling 1 bot token
    msg = str(err) if err else ""
    if "Conflict" in msg and "getUpdates" in msg:
        log.error(
            "❌ XUNG ĐỘT INSTANCE: Có bot khác đang chạy cùng BOT_TOKEN này.\n"
            "👉 Vào Render kiểm tra: CHỈ giữ duy nhất 1 service (Background Worker) "
            "đang chạy. Tắt mọi service/worker khác đang dùng cùng token, "
            "hoặc tạo bot mới qua @BotFather và thay BOT_TOKEN."
        )
        return
    log.exception("Lỗi khi xử lý update: %s", update, exc_info=err)


async def post_init(app: Application):
    me = await app.bot.get_me()
    log.info("Đã kết nối Telegram: @%s (id=%s)", me.username, me.id)
    # Xóa webhook + drop update cũ để tránh xung đột với instance trước.
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        log.warning("delete_webhook lỗi (bỏ qua): %s", e)
    # Chờ 3 giây cho instance cũ (nếu có) nhả getUpdates trước khi mình poll.
    await asyncio.sleep(3)
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
    # Bàn phím chính: text từ reply keyboard
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_text_handler))
    app.add_error_handler(error_handler)

    # job đối chiếu mỗi 5 phút
    if app.job_queue:
        app.job_queue.run_repeating(settle_job, interval=300, first=30)
        # Refresh KQXS đúng 18:35 (giờ VN) mỗi ngày
        app.job_queue.run_daily(
            refresh_xsmb_job,
            time=dtime(18, 35, tzinfo=VN_TZ),
            name="refresh_xsmb_1835",
        )
        # Thử lại mỗi 5 phút từ 18:35 -> 19:30 phòng khi server XSMB chậm
        for mm in (40, 45, 50, 55):
            app.job_queue.run_daily(
                refresh_xsmb_job,
                time=dtime(18, mm, tzinfo=VN_TZ),
                name=f"refresh_xsmb_18{mm}",
            )
        for mm in (0, 10, 20, 30):
            app.job_queue.run_daily(
                refresh_xsmb_job,
                time=dtime(19, mm, tzinfo=VN_TZ),
                name=f"refresh_xsmb_19{mm:02d}",
            )

    log.info("Bot khởi động (long polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()

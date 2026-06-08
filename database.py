"""SQLite helpers cho bot lô đề demo."""
import sqlite3
import os
from datetime import datetime, date
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "lode.db")
DEFAULT_BALANCE = 50_000  # số dư demo khởi tạo


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER NOT NULL DEFAULT 0,
            total_deposit INTEGER NOT NULL DEFAULT 0,
            total_withdraw INTEGER NOT NULL DEFAULT 0,
            joined_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            bet_type TEXT NOT NULL,   -- lo|de|xienhai|xienba|xienbon
            numbers TEXT NOT NULL,    -- "32" hoặc "12,34,56"
            points INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            bet_date TEXT NOT NULL,   -- YYYY-MM-DD (ngày đối chiếu XSMB)
            status TEXT NOT NULL DEFAULT 'pending', -- pending|won|lost
            win_amount INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS xsmb_results (
            result_date TEXT PRIMARY KEY,    -- YYYY-MM-DD
            special TEXT NOT NULL,           -- giải đặc biệt
            all_numbers TEXT NOT NULL,       -- chuỗi tất cả 2 số cuối, cách bằng dấu phẩy
            raw_json TEXT,
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS demo_txn (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,   -- deposit|withdraw
            amount INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        """)


# -------- users --------
def get_or_create_user(user_id: int, username: str | None = None):
    with get_conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row:
            return dict(row)
        c.execute(
            "INSERT INTO users(user_id, username, balance, joined_at) VALUES (?,?,?,?)",
            (user_id, username or "", DEFAULT_BALANCE, datetime.utcnow().isoformat()),
        )
        return {
            "user_id": user_id,
            "username": username or "",
            "balance": DEFAULT_BALANCE,
            "total_deposit": 0,
            "total_withdraw": 0,
            "joined_at": datetime.utcnow().isoformat(),
        }


def get_user(user_id: int):
    with get_conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def update_balance(user_id: int, delta: int):
    with get_conn() as c:
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (delta, user_id))


def set_balance(user_id: int, new_balance: int):
    with get_conn() as c:
        c.execute("UPDATE users SET balance=? WHERE user_id=?", (new_balance, user_id))


# -------- bets --------
def add_bet(user_id: int, bet_type: str, numbers: str, points: int,
            amount: int, bet_date: str) -> int:
    with get_conn() as c:
        cur = c.execute(
            """INSERT INTO bets(user_id, bet_type, numbers, points, amount,
                                created_at, bet_date)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, bet_type, numbers, points, amount,
             datetime.utcnow().isoformat(), bet_date),
        )
        return cur.lastrowid


def pending_bets_for_date(bet_date: str):
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM bets WHERE status='pending' AND bet_date=?",
            (bet_date,),
        ).fetchall()
        return [dict(r) for r in rows]


def settle_bet(bet_id: int, status: str, win_amount: int):
    with get_conn() as c:
        c.execute(
            "UPDATE bets SET status=?, win_amount=? WHERE id=?",
            (status, win_amount, bet_id),
        )


def user_bet_stats(user_id: int):
    today = date.today().isoformat()
    with get_conn() as c:
        total = c.execute(
            "SELECT COUNT(*) AS c FROM bets WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
        today_c = c.execute(
            "SELECT COUNT(*) AS c FROM bets WHERE user_id=? AND bet_date=?",
            (user_id, today),
        ).fetchone()["c"]
        return {"total": total, "today": today_c}


def user_bet_history(user_id: int, limit: int = 10):
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM bets WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# -------- xsmb --------
def save_xsmb(result_date: str, special: str, all_numbers: list[str], raw_json: str = ""):
    with get_conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO xsmb_results
               (result_date, special, all_numbers, raw_json, fetched_at)
               VALUES (?,?,?,?,?)""",
            (result_date, special, ",".join(all_numbers), raw_json,
             datetime.utcnow().isoformat()),
        )


def get_xsmb(result_date: str):
    with get_conn() as c:
        row = c.execute(
            "SELECT * FROM xsmb_results WHERE result_date=?", (result_date,)
        ).fetchone()
        return dict(row) if row else None


# -------- demo txn --------
def add_demo_txn(user_id: int, kind: str, amount: int):
    with get_conn() as c:
        c.execute(
            "INSERT INTO demo_txn(user_id, kind, amount, created_at) VALUES (?,?,?,?)",
            (user_id, kind, amount, datetime.utcnow().isoformat()),
        )
        if kind == "deposit":
            c.execute("UPDATE users SET total_deposit = total_deposit + ?, "
                      "balance = balance + ? WHERE user_id=?",
                      (amount, amount, user_id))
        else:
            c.execute("UPDATE users SET total_withdraw = total_withdraw + ?, "
                      "balance = balance - ? WHERE user_id=?",
                      (amount, amount, user_id))


def demo_txn_history(user_id: int, kind: str, limit: int = 10):
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM demo_txn WHERE user_id=? AND kind=? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, kind, limit),
        ).fetchall()
        return [dict(r) for r in rows]

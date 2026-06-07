"""
core/db.py
══════════════════════════════════════════════════════════════════
All SQLite interactions for FinanceOS.
Provides raw CRUD for users, transactions, and budgets.
No business logic lives here — only data access.
"""
import hashlib
import os
import sqlite3

import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "finance.db")


# ── Connection ────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ── Schema & seed ─────────────────────────────────────────────────

def init_db() -> None:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT    UNIQUE NOT NULL,
        password TEXT    NOT NULL,
        created  TEXT    DEFAULT (datetime('now'))
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        username         TEXT NOT NULL,
        date             TEXT NOT NULL,
        transaction_type TEXT NOT NULL,
        category         TEXT NOT NULL,
        amount           REAL NOT NULL,
        account_name     TEXT NOT NULL,
        note             TEXT DEFAULT '',
        created          TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (username) REFERENCES users(username)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS budgets (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        username  TEXT NOT NULL,
        month     TEXT NOT NULL,
        category  TEXT NOT NULL,
        budget    REAL NOT NULL,
        UNIQUE(username, month, category),
        FOREIGN KEY (username) REFERENCES users(username)
    )""")
    # Seed demo accounts
    for uname, pwd in [("admin", "admin123"), ("demo", "demo"), ("user1", "pass1")]:
        c.execute(
            "INSERT OR IGNORE INTO users (username,password) VALUES (?,?)",
            (uname, _hash(pwd)),
        )
    conn.commit()
    conn.close()


# ── Auth helpers ──────────────────────────────────────────────────

def _hash(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()


def db_check_login(username: str, password: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT password FROM users WHERE username=?", (username,)
    ).fetchone()
    conn.close()
    return bool(row and row["password"] == _hash(password))


def db_register(username: str, password: str) -> tuple[bool, str]:
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO users (username,password) VALUES (?,?)",
            (username, _hash(password)),
        )
        conn.commit()
        conn.close()
        return True, "Account created!"
    except sqlite3.IntegrityError:
        return False, "Username already taken."


# ── Transaction queries ───────────────────────────────────────────

def db_has_transactions(username: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM transactions WHERE username=?", (username,)
    ).fetchone()
    conn.close()
    return row["cnt"] > 0


def db_get_txns(username: str) -> pd.DataFrame:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM transactions WHERE username=? ORDER BY date DESC", (username,)
    ).fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df.rename(
        columns={
            "transaction_type": "Transaction Type",
            "account_name": "Account Name",
            "date": "Date",
            "category": "Category",
            "amount": "Amount",
            "note": "Note",
        },
        inplace=True,
    )
    return df


def db_add_txn(
    username: str,
    txn_date,
    txn_type: str,
    category: str,
    amount: float,
    account_name: str,
    note: str = "",
) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO transactions
        (username,date,transaction_type,category,amount,account_name,note)
        VALUES (?,?,?,?,?,?,?)""",
        (username, str(txn_date), txn_type, category, amount, account_name, note),
    )
    conn.commit()
    conn.close()


def db_update_txn(
    txn_id: int,
    txn_date,
    txn_type: str,
    category: str,
    amount: float,
    account_name: str,
    note: str,
) -> None:
    conn = get_conn()
    conn.execute(
        """UPDATE transactions SET
        date=?, transaction_type=?, category=?, amount=?, account_name=?, note=?
        WHERE id=?""",
        (str(txn_date), txn_type, category, amount, account_name, note, txn_id),
    )
    conn.commit()
    conn.close()


def db_delete_txn(txn_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
    conn.commit()
    conn.close()


def db_clear_txns(username: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM transactions WHERE username=?", (username,))
    conn.commit()
    conn.close()


def db_import_txns(username: str, df: pd.DataFrame) -> int:
    conn = get_conn()
    count = 0
    for _, row in df.iterrows():
        try:
            conn.execute(
                """INSERT INTO transactions
                (username,date,transaction_type,category,amount,account_name,note)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    username,
                    str(row.get("Date", ""))[:10],
                    str(row.get("Transaction Type", "debit")).strip().lower(),
                    str(row.get("Category", "Other")),
                    float(row.get("Amount", 0)),
                    str(row.get("Account Name", "Imported")),
                    str(row.get("Note", "")),
                ),
            )
            count += 1
        except Exception:
            pass
    conn.commit()
    conn.close()
    return count


# ── Budget queries ────────────────────────────────────────────────

def db_set_budget(username: str, month: str, category: str, budget: float) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO budgets (username,month,category,budget) VALUES (?,?,?,?)
        ON CONFLICT(username,month,category) DO UPDATE SET budget=excluded.budget""",
        (username, month, category, budget),
    )
    conn.commit()
    conn.close()


def db_get_budgets(username: str, month: str) -> pd.DataFrame:
    conn = get_conn()
    rows = conn.execute(
        "SELECT category,budget FROM budgets WHERE username=? AND month=?",
        (username, month),
    ).fetchall()
    conn.close()
    return (
        pd.DataFrame([dict(r) for r in rows])
        if rows
        else pd.DataFrame(columns=["category", "budget"])
    )


def db_delete_budget(username: str, month: str, category: str) -> None:
    conn = get_conn()
    conn.execute(
        "DELETE FROM budgets WHERE username=? AND month=? AND category=?",
        (username, month, category),
    )
    conn.commit()
    conn.close()

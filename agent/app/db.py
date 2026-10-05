"""SQLite persistence for bots, trades and events."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from .i18n import dump

SCHEMA = """
CREATE TABLE IF NOT EXISTS bots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    strategy    TEXT    NOT NULL,
    symbol      TEXT    NOT NULL,
    params      TEXT    NOT NULL DEFAULT '{}',
    enabled     INTEGER NOT NULL DEFAULT 0,
    paper       INTEGER NOT NULL DEFAULT 1,
    state       TEXT    NOT NULL DEFAULT '{}',
    status      TEXT    NOT NULL DEFAULT '',
    last_check  INTEGER,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id       INTEGER NOT NULL,
    bot_name     TEXT    NOT NULL,
    symbol       TEXT    NOT NULL,
    side         TEXT    NOT NULL,
    price        TEXT    NOT NULL,
    base_qty     TEXT    NOT NULL,
    quote_amount TEXT    NOT NULL,
    fee          TEXT    NOT NULL,
    pnl          TEXT,
    order_id     TEXT,
    paper        INTEGER NOT NULL,
    reason       TEXT    NOT NULL DEFAULT '',
    created_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS trades_bot ON trades(bot_id, created_at);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id      INTEGER,
    level       TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS events_bot ON events(bot_id, created_at);
-- an exchange order can only ever be booked once
CREATE UNIQUE INDEX IF NOT EXISTS trades_order ON trades(order_id) WHERE order_id IS NOT NULL;
-- every answer of the "AI decides" strategy, so the app can show how Claude judged the market over time
CREATE TABLE IF NOT EXISTS ai_decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id      INTEGER NOT NULL,
    action      TEXT    NOT NULL,
    confidence  INTEGER NOT NULL,
    reason_en   TEXT    NOT NULL,
    reason_de   TEXT    NOT NULL,
    price       TEXT    NOT NULL,
    profit_pct  REAL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_decisions_bot ON ai_decisions(bot_id, id);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Schema changes after the initial release, applied once each (tracked in ``PRAGMA user_version``).
MIGRATIONS: list[str] = [
    # 1: the P&L summary filters trades by time – give it an index
    "CREATE INDEX IF NOT EXISTS trades_created ON trades(created_at);",
    # 2: the trade (position) a buy opened or added to and a sale closed – links each sale to its buys
    "ALTER TABLE trades ADD COLUMN position_id TEXT;",
    # 3: a second broker (Trade Republic) – every bot and trade belongs to one; what existed is Revolut X.
    # Instruments remembers what Trade Republic's ISINs stand for (name, ticker, trading venue), also offline.
    """ALTER TABLE bots ADD COLUMN exchange TEXT NOT NULL DEFAULT 'revolutx';
    ALTER TABLE trades ADD COLUMN exchange TEXT NOT NULL DEFAULT 'revolutx';
    CREATE INDEX IF NOT EXISTS trades_exchange ON trades(exchange, created_at);
    CREATE TABLE IF NOT EXISTS instruments (
        exchange    TEXT    NOT NULL,
        symbol      TEXT    NOT NULL,
        data        TEXT    NOT NULL,
        updated_at  INTEGER NOT NULL,
        PRIMARY KEY (exchange, symbol)
    );""",
]

DEFAULT_LIMITS: dict[str, Any] = {
    "max_open_positions": 3,        # how many bots may hold a position at the same time (0 = unlimited)
    "max_total_invested": 0.0,      # sum of all open positions in quote currency (0 = unlimited)
    "one_position_per_symbol": True,  # only one bot at a time may hold a given pair
}


# Revolut X: 0 % maker, 0.09 % taker. The simulation (paper mode) buys with a fee-free order and sells at the taker
# rate. Trade Republic charges a flat 1 € per order ("Fremdkostenpauschale"). The user can change all of them.
DEFAULT_PAPER_FEES: dict[str, dict[str, float]] = {
    "revolutx": {"buy": 0.0, "sell": 0.0009, "fixed": 0.0},
    "traderepublic": {"buy": 0.0, "sell": 0.0, "fixed": 1.0},
}


def now_ms() -> int:
    return int(time.time() * 1000)


def scoped(key: str, broker: str) -> str:
    """Settings of one broker. Revolut X keeps the keys it had before there was a second broker."""
    return key if broker == "revolutx" else f"{key}.{broker}"


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._open()

    def _open(self) -> None:
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        # WAL + NORMAL: no fsync per statement (every tick writes bot states) – still safe against crashes
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            self._conn.executescript(sql)
            self._conn.execute(f"PRAGMA user_version={number}")

    def close(self) -> None:
        self._conn.close()

    # --- Backup -----------------------------------------------------------

    def snapshot(self) -> bytes:
        """A consistent copy of the whole database (including what is still in the WAL) as a single file."""
        with self._lock:
            copy = sqlite3.connect(":memory:")
            try:
                self._conn.backup(copy)
                return copy.serialize()
            finally:
                copy.close()

    def replace_with(self, source: Path) -> None:
        """Swap in a restored database file (same file system) and reopen; the caller pauses the engine."""
        with self._lock:
            self._conn.close()
            for suffix in ("-wal", "-shm"):
                Path(str(self.path) + suffix).unlink(missing_ok=True)
            os.replace(source, self.path)
            self._open()

    def _all(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def _one(self, sql: str, args: tuple = ()) -> dict[str, Any] | None:
        rows = self._all(sql, args)
        return rows[0] if rows else None

    def _exec(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, args)
            return cur.lastrowid or cur.rowcount

    # --- Bots -------------------------------------------------------------

    @staticmethod
    def _bot(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        row["params"] = json.loads(row["params"])
        row["state"] = json.loads(row["state"])
        row["enabled"] = bool(row["enabled"])
        row["paper"] = bool(row["paper"])
        return row

    def list_bots(self) -> list[dict[str, Any]]:
        return [self._bot(r) for r in self._all("SELECT * FROM bots ORDER BY id")]

    def get_bot(self, bot_id: int) -> dict[str, Any] | None:
        return self._bot(self._one("SELECT * FROM bots WHERE id = ?", (bot_id,)))

    def create_bot(self, name: str, strategy: str, symbol: str, params: dict, enabled: bool, paper: bool,
                   exchange: str = "revolutx") -> int:
        return self._exec(
            "INSERT INTO bots (name, strategy, symbol, params, enabled, paper, created_at, exchange) VALUES (?,?,?,?,?,?,?,?)",
            (name, strategy, symbol, json.dumps(params), int(enabled), int(paper), now_ms(), exchange),
        )

    def update_bot(self, bot_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols, args = [], []
        for key, value in fields.items():
            if key in {"params", "state"}:
                value = json.dumps(value)
            elif key == "status":
                value = dump(value)  # i18n message -> JSON
            elif key in {"enabled", "paper"}:
                value = int(value)
            cols.append(f"{key} = ?")
            args.append(value)
        self._exec(f"UPDATE bots SET {', '.join(cols)} WHERE id = ?", (*args, bot_id))

    def delete_bot(self, bot_id: int) -> None:
        self._exec("DELETE FROM bots WHERE id = ?", (bot_id,))
        self._exec("DELETE FROM events WHERE bot_id = ?", (bot_id,))

    # --- Settings ---------------------------------------------------------

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self._exec(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def get_limits(self, broker: str = "revolutx") -> dict[str, Any]:
        stored = {r["key"]: json.loads(r["value"]) for r in self._all("SELECT key, value FROM settings")}
        return {k: stored.get(scoped(k, broker), v) for k, v in DEFAULT_LIMITS.items()}

    def set_limits(self, limits: dict[str, Any], broker: str = "revolutx") -> None:
        for key, value in limits.items():
            if key in DEFAULT_LIMITS:
                self.set_setting(scoped(key, broker), value)

    # --- Paper-mode fees --------------------------------------------------

    def get_paper_fees(self, broker: str = "revolutx", default_sell: float | None = None) -> dict[str, float]:
        """Fees the simulation charges: rates for buys and sells (0.0009 = 0.09 %) and a fixed amount per order."""
        defaults = dict(DEFAULT_PAPER_FEES.get(broker, DEFAULT_PAPER_FEES["revolutx"]))
        if default_sell is not None:
            defaults["sell"] = default_sell
        stored = self.get_setting(scoped("paper_fees", broker)) or {}
        return {side: float(stored.get(side, rate)) for side, rate in defaults.items()}

    def set_paper_fees(self, fees: dict[str, float], broker: str = "revolutx") -> None:
        self.set_setting(scoped("paper_fees", broker),
                         {"buy": float(fees["buy"]), "sell": float(fees["sell"]), "fixed": float(fees.get("fixed") or 0)})

    def reprice_paper(self, old: dict[str, float], new: dict[str, float], broker: str = "revolutx") -> int:
        """Rebook the broker's simulated trades as if ``new`` fees had always applied (``old`` = what they were
        booked with).

        The amount spent on a buy and the price of every trade stay as they are – what changes is how much of the
        money became coins (buys) and what a sale leaves after the fee. Open trades get the new coin quantity,
        sales their new proceeds and profit. Returns the number of rebooked trades.
        """
        d = lambda x: Decimal(str(x or 0))  # noqa: E731
        if all(d(old.get(k)) == d(new.get(k)) for k in ("buy", "sell", "fixed")):
            return 0
        k = (1 - d(new["buy"])) / (1 - d(old["buy"]))  # coins per unit of money, new / old (without a fixed fee)
        proportional = d(old.get("fixed")) == d(new.get("fixed")) == 0
        step = Decimal("0.00000001")
        # per trade (position): coins of its buys before and after – its sales and its open rest change alike
        bought: dict[tuple[int, str], list[Decimal]] = {}

        def ratio(bot_id: int, position_id: str | None) -> Decimal:
            old_qty, new_qty = bought.get((bot_id, position_id or ""), (Decimal(0), Decimal(0)))
            return new_qty / old_qty if old_qty else k

        with self._lock:
            self._conn.execute("BEGIN")
            try:
                rows = self._conn.execute(
                    "SELECT * FROM trades WHERE paper = 1 AND exchange = ? ORDER BY id", (broker,)).fetchall()
                for r in (r for r in rows if r["side"] == "buy"):
                    price, qty_, amount = d(r["price"]), d(r["base_qty"]), d(r["quote_amount"])
                    fee = amount * d(new["buy"]) + d(new.get("fixed"))
                    if proportional:
                        new_qty = (qty_ * k).quantize(step)
                    else:  # a fixed fee doesn't scale with the amount – book every buy again from what it cost
                        new_qty = max((amount - fee) / price, Decimal(0)).quantize(step) if price else qty_
                    self._conn.execute("UPDATE trades SET base_qty = ?, fee = ? WHERE id = ?", (str(new_qty), str(fee), r["id"]))
                    if r["position_id"]:
                        acc = bought.setdefault((r["bot_id"], r["position_id"]), [Decimal(0), Decimal(0)])
                        acc[0] += qty_
                        acc[1] += new_qty
                for r in (r for r in rows if r["side"] != "buy"):
                    price, qty_, amount, pnl = d(r["price"]), d(r["base_qty"]), d(r["quote_amount"]), r["pnl"]
                    cost_part = amount - d(pnl) if pnl is not None else None
                    new_qty = (qty_ * ratio(r["bot_id"], r["position_id"])).quantize(step)
                    gross = new_qty * price
                    fee = gross * d(new["sell"]) + d(new.get("fixed"))
                    proceeds = gross - fee
                    self._conn.execute(
                        "UPDATE trades SET base_qty = ?, quote_amount = ?, fee = ?, pnl = ? WHERE id = ?",
                        (str(new_qty), str(proceeds), str(fee),
                         str(proceeds - cost_part) if cost_part is not None else None, r["id"]),
                    )
                for bot in self._conn.execute("SELECT id, state FROM bots WHERE exchange = ?", (broker,)).fetchall():
                    state = json.loads(bot["state"])
                    changed = False
                    for key in ("positions", "position"):
                        raw = state.get(key)
                        for pos in ([raw] if isinstance(raw, dict) else raw or []):
                            if pos.get("paper", True):
                                pos["qty"] = str((d(pos["qty"]) * ratio(bot["id"], pos.get("id"))).quantize(step))
                                changed = True
                    if changed:
                        self._conn.execute("UPDATE bots SET state = ? WHERE id = ?", (json.dumps(state), bot["id"]))
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        return len(rows)

    # --- Trades -----------------------------------------------------------

    def trade_exists(self, order_id: str) -> bool:
        return self._one("SELECT 1 AS x FROM trades WHERE order_id = ?", (order_id,)) is not None

    def booked_for_order(self, order_id: str) -> dict[str, Any]:
        """Quantity, amount and fee already booked for an exchange order (late fills are booked as ``id#2`` …)."""
        row = self._one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(CAST(base_qty AS REAL)), 0) AS qty, "
            "COALESCE(SUM(CAST(quote_amount AS REAL)), 0) AS amount, COALESCE(SUM(CAST(fee AS REAL)), 0) AS fee "
            "FROM trades WHERE order_id = ? OR order_id LIKE ?",
            (order_id, f"{order_id}#%"),
        )
        return row or {"n": 0, "qty": 0.0, "amount": 0.0, "fee": 0.0}

    def add_trade(self, **t: Any) -> int:
        t.setdefault("created_at", now_ms())
        t["reason"] = dump(t.get("reason") or "")
        cols = ", ".join(t)
        marks = ", ".join("?" for _ in t)
        return self._exec(f"INSERT INTO trades ({cols}) VALUES ({marks})", tuple(t.values()))

    def delete_paper_trades_of_broker(self, broker: str) -> int:
        """Removes all simulated trades on one broker (also those of deleted bots). Returns how many were deleted."""
        count = self._one("SELECT COUNT(*) AS n FROM trades WHERE paper = 1 AND exchange = ?", (broker,))["n"]
        self._exec("DELETE FROM trades WHERE paper = 1 AND exchange = ?", (broker,))
        return int(count)

    def delete_paper_trades(self, bot_id: int) -> int:
        """Removes a bot's simulated trades (live trades stay). Returns how many were deleted."""
        count = self._one("SELECT COUNT(*) AS n FROM trades WHERE bot_id = ? AND paper = 1", (bot_id,))["n"]
        self._exec("DELETE FROM trades WHERE bot_id = ? AND paper = 1", (bot_id,))
        return int(count)

    def list_trades(self, bot_id: int | None = None, limit: int = 200, exchange: str | None = None) -> list[dict[str, Any]]:
        where, args = [], []
        if bot_id is not None:
            where.append("bot_id = ?")
            args.append(bot_id)
        if exchange is not None:
            where.append("exchange = ?")
            args.append(exchange)
        clause = f"WHERE {' AND '.join(where)} " if where else ""
        return self._all(f"SELECT * FROM trades {clause}ORDER BY created_at DESC, id DESC LIMIT ?", (*args, limit))

    def trade_stats(self) -> dict[int, dict[str, Any]]:
        rows = self._all(
            """SELECT bot_id,
                      COUNT(*) AS trades,
                      SUM(CASE WHEN pnl IS NOT NULL THEN CAST(pnl AS REAL) ELSE 0 END) AS realized,
                      SUM(CASE WHEN pnl IS NOT NULL AND CAST(pnl AS REAL) > 0 THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN pnl IS NOT NULL AND CAST(pnl AS REAL) <= 0 THEN 1 ELSE 0 END) AS losses
               FROM trades GROUP BY bot_id"""
        )
        return {r["bot_id"]: r for r in rows}

    def realized_since(self, since_ms: int, paper: bool | None = None, exchange: str | None = None) -> list[dict[str, Any]]:
        return self._all(
            "SELECT symbol, SUM(CAST(pnl AS REAL)) AS pnl FROM trades "
            f"WHERE pnl IS NOT NULL AND created_at >= ? {self._mode(paper, exchange)} GROUP BY symbol",
            (since_ms,),
        )

    def realized_by_symbol(self, paper: bool | None = None, exchange: str | None = None) -> list[dict[str, Any]]:
        return self._all(
            "SELECT symbol, SUM(CAST(pnl AS REAL)) AS pnl FROM trades "
            f"WHERE pnl IS NOT NULL {self._mode(paper, exchange)} GROUP BY symbol"
        )

    def fees_by_symbol(self, paper: bool | None = None, exchange: str | None = None) -> list[dict[str, Any]]:
        """Exchange fees paid so far (buys and sells), in the quote currency."""
        return self._all(
            f"SELECT symbol, SUM(CAST(fee AS REAL)) AS fee FROM trades WHERE 1=1 {self._mode(paper, exchange)} GROUP BY symbol"
        )

    def trades_count(self, paper: bool | None = None, exchange: str | None = None) -> int:
        return int(self._one(f"SELECT COUNT(*) AS n FROM trades WHERE 1=1 {self._mode(paper, exchange)}")["n"])

    @staticmethod
    def _mode(paper: bool | None, exchange: str | None = None) -> str:
        """SQL filter for simulated (paper) or real trades – None means both – and for one broker's trades."""
        clause = "" if paper is None else f"AND paper = {1 if paper else 0}"
        if exchange is not None:
            if not exchange.isalnum():
                raise ValueError(f"invalid exchange {exchange!r}")
            clause += f" AND exchange = '{exchange}'"
        return clause

    # --- Instruments (what a broker's symbols stand for) -----------------------

    def instruments(self, exchange: str) -> dict[str, dict[str, Any]]:
        rows = self._all("SELECT symbol, data FROM instruments WHERE exchange = ?", (exchange,))
        return {r["symbol"]: json.loads(r["data"]) for r in rows}

    def save_instrument(self, exchange: str, symbol: str, data: dict[str, Any]) -> None:
        self._exec(
            "INSERT INTO instruments (exchange, symbol, data, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(exchange, symbol) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (exchange, symbol, json.dumps(data), now_ms()),
        )

    # --- Events -----------------------------------------------------------

    def add_event(self, bot_id: int | None, level: str, message: dict | str) -> None:
        self._exec(
            "INSERT INTO events (bot_id, level, message, created_at) VALUES (?,?,?,?)",
            (bot_id, level, dump(message), now_ms()),
        )
        # keep the log bounded
        self._exec("DELETE FROM events WHERE id <= (SELECT MAX(id) - 5000 FROM events)")

    # --- AI decisions -----------------------------------------------------

    def add_ai_decision(self, bot_id: int, action: str, confidence: int, reason_en: str, reason_de: str,
                        price: str, profit_pct: float | None) -> None:
        self._exec(
            "INSERT INTO ai_decisions (bot_id, action, confidence, reason_en, reason_de, price, profit_pct, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (bot_id, action, confidence, reason_en, reason_de, price, profit_pct, now_ms()),
        )
        # keep the journal bounded per bot
        self._exec(
            "DELETE FROM ai_decisions WHERE bot_id = ? AND id <= "
            "(SELECT id FROM ai_decisions WHERE bot_id = ? ORDER BY id DESC LIMIT 1 OFFSET 500)",
            (bot_id, bot_id),
        )

    def list_ai_decisions(self, bot_id: int, limit: int = 100) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM ai_decisions WHERE bot_id = ? ORDER BY id DESC LIMIT ?", (bot_id, limit))

    def list_events(self, bot_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if bot_id is None:
            return self._all("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        return self._all("SELECT * FROM events WHERE bot_id = ? ORDER BY id DESC LIMIT ?", (bot_id, limit))

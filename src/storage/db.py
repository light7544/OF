"""SQLite Database repository for DexT3 Signal Engine."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, Generator, List, Optional

from src.models.schemas import (
    OptionChainSnapshot,
    OrderFlowSnapshot,
    PaperTrade,
    SignalDecision,
)

logger = logging.getLogger("database")


class Database:
    def __init__(self, db_path: str = "data/signals.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Auto-migrate from old repository path if needed
        old_db = Path("data/signals.db")
        if old_db.exists() and not self.db_path.exists() and old_db.resolve() != self.db_path.resolve():
            import shutil
            logger.info("Migrating existing database from %s to %s", old_db, self.db_path)
            shutil.copy2(old_db, self.db_path)
        self._init_db()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")

            # Order Flow snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_flow_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    current_price REAL NOT NULL,
                    candle_interval TEXT NOT NULL,
                    cumulative_delta INTEGER NOT NULL,
                    is_mock INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Option Chain snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS option_chain_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    underlying_price REAL NOT NULL,
                    expiry TEXT,
                    pcr REAL NOT NULL,
                    atm_iv REAL NOT NULL,
                    max_pain REAL NOT NULL,
                    is_mock INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Signal decisions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    symbol TEXT NOT NULL,
                    underlying_price REAL NOT NULL,
                    strike REAL,
                    option_type TEXT,
                    expiry TEXT,
                    entry_price REAL,
                    stop_loss REAL,
                    target_1 REAL,
                    target_2 REAL,
                    risk_reward REAL,
                    reason TEXT,
                    is_mock INTEGER NOT NULL,
                    factors_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Paper trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id INTEGER,
                    symbol TEXT NOT NULL,
                    strike REAL NOT NULL,
                    option_type TEXT NOT NULL,
                    expiry TEXT,
                    entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    target1 REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    pnl_points REAL NOT NULL,
                    pnl_amount REAL NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    exit_price REAL,
                    exit_reason TEXT,
                    is_mock INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Audit / Event logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Angel One Option Chain snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS angel_chain_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    expiry TEXT NOT NULL,
                    spot REAL NOT NULL,
                    pcr_oi REAL NOT NULL,
                    max_pain REAL NOT NULL,
                    resistance REAL NOT NULL,
                    support REAL NOT NULL,
                    bias TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    strikes_json TEXT NOT NULL,
                    is_mock INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def save_angel_chain_snapshot(
        self, timestamp: str, expiry: str, spot: float, summary: Dict[str, Any], strikes: List[Dict[str, Any]], is_mock: bool = False
    ) -> int:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO angel_chain_snapshots (
                    timestamp, expiry, spot, pcr_oi, max_pain,
                    resistance, support, bias, summary_json, strikes_json, is_mock
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp, expiry, spot, summary.get("pcr_oi", 1.0),
                    summary.get("max_pain", spot), summary.get("resistance", spot),
                    summary.get("support", spot), summary.get("bias", "NEUTRAL"),
                    json.dumps(summary), json.dumps(strikes), 1 if is_mock else 0,
                ),
            )
            return cursor.lastrowid or 0

    def save_order_flow(self, snapshot: OrderFlowSnapshot) -> int:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO order_flow_snapshots (
                    symbol, timestamp, current_price, candle_interval,
                    cumulative_delta, is_mock, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.symbol,
                    snapshot.timestamp,
                    snapshot.current_price or 0.0,
                    snapshot.candle_interval or "5m",
                    snapshot.cumulative_delta or 0,
                    1 if snapshot.is_mock else 0,
                    snapshot.model_dump_json(),
                ),
            )
            return cursor.lastrowid or 0

    def save_option_chain(self, snapshot: OptionChainSnapshot) -> int:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO option_chain_snapshots (
                    symbol, timestamp, underlying_price, expiry,
                    pcr, atm_iv, max_pain, is_mock, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.symbol,
                    snapshot.timestamp,
                    snapshot.underlying_price or 0.0,
                    snapshot.expiry or "",
                    snapshot.pcr or 1.0,
                    snapshot.atm_iv or 14.0,
                    snapshot.max_pain or 0.0,
                    1 if snapshot.is_mock else 0,
                    snapshot.model_dump_json(),
                ),
            )
            return cursor.lastrowid or 0

    def save_signal(self, decision: SignalDecision) -> int:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO signals (
                    timestamp, signal, confidence, symbol, underlying_price,
                    strike, option_type, expiry, entry_price, stop_loss,
                    target_1, target_2, risk_reward, reason, is_mock, factors_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.timestamp,
                    decision.signal.value if hasattr(decision.signal, "value") else str(decision.signal),
                    decision.confidence,
                    decision.symbol,
                    decision.underlying_price,
                    decision.strike,
                    decision.option_type,
                    decision.expiry,
                    decision.entry_price,
                    decision.stop_loss,
                    decision.target_1,
                    decision.target_2,
                    decision.risk_reward,
                    decision.reason,
                    1 if decision.is_mock else 0,
                    json.dumps(decision.factors),
                ),
            )
            return cursor.lastrowid or 0

    def save_paper_trade(self, trade: PaperTrade) -> int:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO paper_trades (
                    signal_id, symbol, strike, option_type, expiry,
                    entry_price, current_price, stop_loss, target1, quantity,
                    status, pnl_points, pnl_amount, opened_at, is_mock
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.signal_id,
                    trade.symbol,
                    trade.strike,
                    trade.option_type,
                    trade.expiry,
                    trade.entry_price,
                    trade.current_price,
                    trade.stop_loss,
                    trade.target1,
                    trade.quantity,
                    trade.status,
                    trade.pnl_points,
                    trade.pnl_amount,
                    trade.opened_at,
                    1 if trade.is_mock else 0,
                ),
            )
            trade.id = cursor.lastrowid
            return cursor.lastrowid or 0

    def update_paper_trade(self, trade: PaperTrade) -> None:
        if not trade.id:
            return
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE paper_trades
                SET current_price = ?, stop_loss = ?, status = ?,
                    pnl_points = ?, pnl_amount = ?, closed_at = ?,
                    exit_price = ?, exit_reason = ?
                WHERE id = ?
                """,
                (
                    trade.current_price,
                    trade.stop_loss,
                    trade.status,
                    trade.pnl_points,
                    trade.pnl_amount,
                    trade.closed_at,
                    trade.exit_price,
                    trade.exit_reason,
                    trade.id,
                ),
            )

    def get_recent_signals(self, limit: int = 5) -> List[Dict[str, Any]]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_open_paper_trades(self) -> List[PaperTrade]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_trades WHERE status != 'CLOSED'")
            rows = cursor.fetchall()
            trades: List[PaperTrade] = []
            for r in rows:
                t = PaperTrade(
                    id=r["id"],
                    signal_id=r["signal_id"],
                    symbol=r["symbol"],
                    strike=r["strike"],
                    option_type=r["option_type"],
                    expiry=r["expiry"] or "",
                    entry_price=r["entry_price"],
                    current_price=r["current_price"],
                    stop_loss=r["stop_loss"],
                    target1=r["target1"],
                    quantity=r["quantity"],
                    status=r["status"],
                    pnl_points=r["pnl_points"],
                    pnl_amount=r["pnl_amount"],
                    opened_at=r["opened_at"],
                    is_mock=bool(r["is_mock"]),
                )
                trades.append(t)
            return trades

    def get_latest_order_flow(self) -> Optional[OrderFlowSnapshot]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT payload_json FROM order_flow_snapshots ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return OrderFlowSnapshot.model_validate_json(row["payload_json"])
            return None

    def get_latest_option_chain(self) -> Optional[OptionChainSnapshot]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT payload_json FROM option_chain_snapshots ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                return OptionChainSnapshot.model_validate_json(row["payload_json"])
            return None

    def log_audit(self, event_type: str, message: str, payload: str = "") -> None:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO audit_logs (event_type, message, payload) VALUES (?, ?, ?)",
                (event_type, message, payload),
            )

    def save_angel_chain_snapshot(
        self,
        expiry: str,
        spot: float,
        summary: Dict[str, Any],
        chain_df: Any,
        is_mock: bool = False,
    ) -> None:
        with self._connection() as conn:
            cursor = conn.cursor()
            strikes_payload = (
                chain_df.to_json(orient="records")
                if hasattr(chain_df, "to_json")
                else json.dumps(chain_df)
            )
            cursor.execute(
                """
                INSERT INTO angel_chain_snapshots (
                    timestamp, expiry, spot, pcr_oi, max_pain,
                    resistance, support, bias, summary_json, strikes_json, is_mock
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    expiry,
                    spot,
                    summary.get("pcr_oi", 1.0),
                    summary.get("max_pain", spot),
                    summary.get("resistance", spot),
                    summary.get("support", spot),
                    summary.get("bias", "NEUTRAL"),
                    json.dumps(summary),
                    strikes_payload,
                    1 if is_mock else 0,
                ),
            )

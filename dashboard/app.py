"""FastAPI read-only dashboard server for DexT3 Order Flow + Angel One Option Chain."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

load_dotenv()

DATA_DIR = Path(os.getenv("DATA_DIR", "C:/bot_data")).resolve()
DB_PATH = DATA_DIR / "signals.db"
LOGS_DIR = DATA_DIR / "logs"

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()
FORBIDDEN_PASSWORDS = {"", "changeme", "password", "your_password", "your_dashboard_password_here"}

if len(DASHBOARD_PASSWORD) < 8 or DASHBOARD_PASSWORD.lower() in FORBIDDEN_PASSWORDS:
    raise RuntimeError(
        "DASHBOARD_PASSWORD in .env must be set, at least 8 characters long, "
        "and cannot be a generic placeholder."
    )

app = FastAPI(title="DexT3 Trading Bot Dashboard", docs_url=None, redoc_url=None)
security = HTTPBasic()


def get_db_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database file not found at {DB_PATH}",
        )
    # Open read-only mode using URI
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def authenticate(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    correct_password_bytes = DASHBOARD_PASSWORD.encode("utf-8")
    provided_password_bytes = credentials.password.encode("utf-8")
    is_password_correct = secrets.compare_digest(provided_password_bytes, correct_password_bytes)
    if not is_password_correct:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def parse_db_utc(ts_str: Optional[str]) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        clean = ts_str.strip().replace("Z", "+00:00")
        if "T" in clean:
            dt = datetime.fromisoformat(clean)
        else:
            dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


SECRET_PATTERNS = [
    re.compile(r"(api[-_]?key\s*[:=]\s*)['\"]?([A-Za-z0-9_\-]{6,})['\"]?", re.IGNORECASE),
    re.compile(r"(secret\s*[:=]\s*)['\"]?([A-Za-z0-9_\-]{6,})['\"]?", re.IGNORECASE),
    re.compile(r"(token\s*[:=]\s*)['\"]?([A-Za-z0-9_\.\-]{8,})['\"]?", re.IGNORECASE),
    re.compile(r"(pin\s*[:=]\s*)['\"]?(\d{4,8})['\"]?", re.IGNORECASE),
    re.compile(r"(client[-_]?id\s*[:=]\s*)['\"]?([A-Za-z0-9]{4,12})['\"]?", re.IGNORECASE),
    re.compile(r"ey[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),  # JWT
    re.compile(r"\b[A-Za-z0-9]{32,}\b"),  # Long alphanumeric hashes
]


def redact_line(line: str) -> str:
    out = line
    for pat in SECRET_PATTERNS:
        out = pat.sub(r"\1***REDACTED***" if pat.groups > 0 else "***REDACTED***", out)
    return out


# ==============================================================================
# API Endpoints
# ==============================================================================

@app.get("/api/status")
def get_status(_: str = Depends(authenticate)) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode;")
        journal_mode = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM signals")
        total_signals = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM paper_trades WHERE status = 'OPEN'")
        open_trades = cur.fetchone()[0]

        cur.execute("SELECT created_at, timestamp, is_mock, signal FROM signals ORDER BY id DESC LIMIT 1")
        last_sig = cur.fetchone()

        if last_sig:
            dt_utc = parse_db_utc(last_sig["created_at"]) or parse_db_utc(last_sig["timestamp"])
            if dt_utc:
                diff_sec = (datetime.now(timezone.utc) - dt_utc).total_seconds()
                age_minutes = round(diff_sec / 60.0, 1)
                if age_minutes <= 5.5:
                    bot_status = "ACTIVE"
                elif age_minutes <= 10.0:
                    bot_status = "DELAYED"
                else:
                    bot_status = "STALE"
            else:
                age_minutes = None
                bot_status = "UNKNOWN"
            last_signal_info = {
                "created_at": last_sig["created_at"],
                "timestamp": last_sig["timestamp"],
                "signal": last_sig["signal"],
                "is_mock": bool(last_sig["is_mock"]),
                "age_minutes": age_minutes,
            }
        else:
            bot_status = "IDLE"
            last_signal_info = None

        return {
            "bot_status": bot_status,
            "journal_mode": journal_mode,
            "total_signals": total_signals,
            "open_trades": open_trades,
            "last_signal": last_signal_info,
            "data_dir": str(DATA_DIR),
            "db_size_bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        }
    finally:
        conn.close()


@app.get("/api/latest")
def get_latest_signal(_: str = Depends(authenticate)) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM signals ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if not row:
            return {"status": "EMPTY", "message": "No signals recorded yet"}

        data = dict(row)
        factors = {}
        if data.get("factors_json"):
            try:
                factors = json.loads(data["factors_json"])
            except Exception:
                factors = {}
        data["factors"] = factors
        return data
    finally:
        conn.close()


@app.get("/api/chain/latest")
def get_latest_chain(
    include_mock: bool = Query(False),
    _: str = Depends(authenticate),
) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        query = "SELECT * FROM angel_chain_snapshots"
        if not include_mock:
            query += " WHERE is_mock = 0"
        query += " ORDER BY id DESC LIMIT 1"

        cur.execute(query)
        row = cur.fetchone()
        if not row:
            return {
                "status": "EMPTY",
                "message": "No live Angel One chain snapshots available",
            }

        data = dict(row)
        try:
            data["summary"] = json.loads(data.get("summary_json", "{}"))
        except Exception:
            data["summary"] = {}

        try:
            data["strikes"] = json.loads(data.get("strikes_json", "[]"))
        except Exception:
            data["strikes"] = []

        return data
    finally:
        conn.close()


@app.get("/api/history")
def get_signal_history(
    include_mock: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    _: str = Depends(authenticate),
) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        query = "SELECT * FROM signals"
        if not include_mock:
            query += " WHERE is_mock = 0"
        query += " ORDER BY id DESC LIMIT ?"

        cur.execute(query, (limit,))
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("factors_json"):
                try:
                    d["factors"] = json.loads(d["factors_json"])
                except Exception:
                    d["factors"] = {}
            result.append(d)
        return result
    finally:
        conn.close()


@app.get("/api/trades")
def get_trades(
    include_mock: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    _: str = Depends(authenticate),
) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        query = "SELECT * FROM paper_trades"
        if not include_mock:
            query += " WHERE is_mock = 0"
        query += " ORDER BY id DESC LIMIT ?"

        cur.execute(query, (limit,))
        rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["pnl_points"] = d.get("pnl_points") or 0.0
            d["pnl_amount"] = d.get("pnl_amount") or 0.0
            result.append(d)
        return result
    finally:
        conn.close()


@app.get("/api/logs")
def get_logs(_: str = Depends(authenticate)) -> List[str]:
    log_files = [
        LOGS_DIR / "bot_runtime.log",
        LOGS_DIR / "signal_debug.log",
        LOGS_DIR / "capture_debug.log",
    ]
    warning_error_lines = []

    for lf in log_files:
        if lf.exists():
            try:
                # Read last 300 lines of each file
                text = lf.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()[-300:]
                for line in lines:
                    upper = line.upper()
                    if "[WARNING]" in upper or "[ERROR]" in upper or "WARNING" in upper or "ERROR" in upper:
                        warning_error_lines.append(redact_line(line))
            except Exception as e:
                warning_error_lines.append(f"[LOG_READER_ERROR] Could not read {lf.name}: {e}")

    # Return only the last 100 entries
    return warning_error_lines[-100:]


# Static UI mount
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index(_: str = Depends(authenticate)):
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Dashboard UI index.html not found")
    return FileResponse(index_file)

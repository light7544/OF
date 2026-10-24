"""angel_chain.py - Angel One SmartAPI Option Chain Fetch + Analysis (NIFTY).

Fetches live NIFTY option chain directly from Angel One SmartConnect API,
calculates Open Interest changes, Max Pain, PCR, Support/Resistance walls,
and provides confluence confirmation with Order Flow signals.

Setup:
    pip install smartapi-python pyotp pandas requests logzero websocket-client python-dotenv
    Set credentials in .env:
        ANGEL_API_KEY=your_api_key
        ANGEL_CLIENT_ID=your_client_id
        ANGEL_PIN=your_mpin
        ANGEL_TOTP_SECRET=your_totp_secret_key
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

# Optional dotenv support
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Angel One SmartAPI imports
try:
    import pyotp
    from SmartApi import SmartConnect
except ImportError:
    SmartConnect = None
    pyotp = None

logger = logging.getLogger("angel_chain")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DATA_DIR = Path(os.getenv("DATA_DIR", "C:/bot_data")).resolve()
MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
MASTER_CACHE = DATA_DIR / "scrip_master.json"
SNAP_FILE = DATA_DIR / "chain_prev.json"
NIFTY_SPOT = ("NSE", "Nifty 50", "99926000")  # exchange, symbol, token


# ==============================================================================
# 1. Authentication & Session Management (Zero-Leak Security)
# ==============================================================================

def get_env_credentials() -> Dict[str, str]:
    """Load and validate Angel One credentials from environment or .env."""
    creds = {
        "api_key": os.getenv("ANGEL_API_KEY", "").strip(),
        "client_id": os.getenv("ANGEL_CLIENT_ID", "").strip(),
        "pin": os.getenv("ANGEL_PIN", "").strip(),
        "totp_secret": os.getenv("ANGEL_TOTP_SECRET", "").strip(),
    }
    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise ValueError(
            f"Missing required Angel One credentials in .env: {', '.join(missing)}"
        )
    return creds


def login(creds: Optional[Dict[str, str]] = None) -> SmartConnect:
    """Authenticate with Angel One SmartAPI using TOTP without logging secrets."""
    if SmartConnect is None or pyotp is None:
        raise ImportError(
            "smartapi-python and pyotp are required. Run: python -m pip install --user smartapi-python pyotp"
        )

    if creds is None:
        creds = get_env_credentials()

    api = SmartConnect(api_key=creds["api_key"])
    totp = pyotp.TOTP(creds["totp_secret"]).now()

    res = api.generateSession(creds["client_id"], creds["pin"], totp)
    if not isinstance(res, dict) or not res.get("status"):
        err_msg = res.get("message", "Login rejected") if isinstance(res, dict) else "Login rejected"
        err_code = res.get("errorcode", "AUTH_FAILED") if isinstance(res, dict) else "ERR"
        raise RuntimeError(f"Angel One login failed: {err_msg} (code: {err_code})")

    logger.info("Successfully authenticated with Angel One SmartAPI")
    return api


# ==============================================================================
# 2. Instrument Scrip Master (Cached Daily)
# ==============================================================================

def load_master(force_refresh: bool = False) -> pd.DataFrame:
    """Download and cache the Angel One OpenAPIScripMaster JSON daily."""
    MASTER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    
    fresh = False
    if MASTER_CACHE.exists() and not force_refresh:
        try:
            mtime_date = date.fromtimestamp(MASTER_CACHE.stat().st_mtime)
            if mtime_date == date.today() and MASTER_CACHE.stat().st_size > 1024:
                fresh = True
        except Exception:
            fresh = False

    if not fresh:
        logger.info("Downloading fresh instrument master from Angel One (~35-40 MB)...")
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(MASTER_URL, headers=headers, timeout=90)
        resp.raise_for_status()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        MASTER_CACHE.write_bytes(resp.content)
        logger.info("Scrip master cached to %s (%d bytes)", MASTER_CACHE, len(resp.content))

    data = json.loads(MASTER_CACHE.read_text(encoding="utf-8"))
    return pd.DataFrame(data)


def option_contracts(
    master: pd.DataFrame, name: str = "NIFTY", expiry: Optional[str] = None
) -> pd.DataFrame:
    """Filter master for option index contracts and determine target expiry.
    
    Returns:
        pd.DataFrame: Filtered option contracts for selected expiry.
    """
    df = master[
        (master["name"] == name)
        & (master["instrumenttype"] == "OPTIDX")
        & (master["exch_seg"] == "NFO")
    ].copy()

    if df.empty:
        raise ValueError(f"No option contracts found for symbol '{name}' in NFO segment.")

    df["exp"] = pd.to_datetime(df["expiry"], format="%d%b%Y", errors="coerce")
    df = df.dropna(subset=["exp"])
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce").fillna(0.0) / 100.0
    df["type"] = df["symbol"].astype(str).str[-2:].str.upper()

    today = pd.Timestamp.today().normalize()
    if expiry is None:
        upcoming = df.loc[df["exp"] >= today, "exp"]
        if upcoming.empty:
            expiry_dt = df["exp"].max()
        else:
            expiry_dt = upcoming.min()
    else:
        expiry_dt = pd.to_datetime(expiry, format="%d%b%Y")

    expiry_str = expiry_dt.strftime("%d%b%Y").upper()
    selected = df[df["exp"] == expiry_dt].copy()
    logger.info("Target expiry selected: %s (%d contracts found)", expiry_str, len(selected))
    return selected


# ==============================================================================
# 3. Live Option Chain & Spot Fetching
# ==============================================================================

def get_spot(api: SmartConnect) -> float:
    """Fetch live spot LTP for NIFTY 50."""
    ex, sym, tok = NIFTY_SPOT
    resp = api.ltpData(ex, sym, tok)
    if not isinstance(resp, dict) or not resp.get("status"):
        raise RuntimeError(f"Failed to fetch spot price: {resp}")
    data = resp.get("data") or {}
    ltp = data.get("ltp")
    if ltp is None:
        raise ValueError(f"Spot price missing in response: {resp}")
    return float(ltp)


def fetch_chain(
    api: SmartConnect,
    contracts: pd.DataFrame,
    spot: float,
    width: int = 12,
    step: int = 50,
) -> pd.DataFrame:
    """Fetch live market depth (LTP, OI, Volume) for Near-ATM option strikes."""
    if contracts.empty:
        raise ValueError("Contracts DataFrame is empty.")

    atm = round(spot / step) * step
    lo, hi = atm - (width * step), atm + (width * step)
    sel = contracts[(contracts["strike"] >= lo) & (contracts["strike"] <= hi)].copy()
    tokens = sel["token"].astype(str).tolist()

    if not tokens:
        raise ValueError(f"No strikes found in range {lo} - {hi}")

    rows: List[Dict[str, Any]] = []
    # Angel One limit: 50 tokens per getMarketData request
    for i in range(0, len(tokens), 50):
        batch = tokens[i : i + 50]
        try:
            res = api.getMarketData("FULL", {"NFO": batch})
            if isinstance(res, dict) and res.get("status"):
                fetched = (res.get("data") or {}).get("fetched", [])
                rows.extend(fetched)
            else:
                logger.warning("getMarketData partial failure on batch %d: %s", i, res)
        except Exception as e:
            logger.error("Error fetching market data batch %d: %s", i, e)
        time.sleep(1.0)  # Politeness interval for API rate limits

    if not rows:
        raise RuntimeError("Failed to fetch market data rows from Angel One API.")

    q = pd.DataFrame(rows)
    if "symbolToken" in q.columns:
        q = q.rename(columns={"symbolToken": "token"})
    q["token"] = q["token"].astype(str)
    sel["token"] = sel["token"].astype(str)

    cols_to_keep = ["token"]
    for col in ["ltp", "opnInterest", "tradeVolume"]:
        if col in q.columns:
            cols_to_keep.append(col)
        else:
            q[col] = 0.0
            cols_to_keep.append(col)

    q = q[cols_to_keep]
    m = sel[["token", "strike", "type"]].merge(q, on="token", how="left").fillna(0)

    # Format Call and Put tables
    ce_mask = m["type"] == "CE"
    pe_mask = m["type"] == "PE"

    ce = (
        m[ce_mask]
        .set_index("strike")[["ltp", "opnInterest", "tradeVolume"]]
        .add_prefix("ce_")
    )
    pe = (
        m[pe_mask]
        .set_index("strike")[["ltp", "opnInterest", "tradeVolume"]]
        .add_prefix("pe_")
    )

    chain = ce.join(pe, how="outer").fillna(0.0).reset_index()
    rename_map = {
        "ce_opnInterest": "ce_oi",
        "pe_opnInterest": "pe_oi",
        "ce_tradeVolume": "ce_vol",
        "pe_tradeVolume": "pe_vol",
    }
    chain = chain.rename(columns=rename_map)
    chain = chain.sort_values("strike").reset_index(drop=True)
    return chain


# ==============================================================================
# 4. Open Interest Change Tracking
# ==============================================================================

def add_oi_change(chain: pd.DataFrame) -> pd.DataFrame:
    """Calculate OI change compared to previous 5-minute snapshot (today only)."""
    SNAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    chain = chain.copy()
    chain["ce_oi_chg"] = 0.0
    chain["pe_oi_chg"] = 0.0
    today_str = date.today().isoformat()

    if SNAP_FILE.exists():
        try:
            prev_raw = json.loads(SNAP_FILE.read_text(encoding="utf-8"))
            snap_date = prev_raw.get("date") if isinstance(prev_raw, dict) else None
            if snap_date == today_str:
                prev_records = prev_raw.get("data", [])
                prev_df = pd.DataFrame(prev_records)
                if not prev_df.empty and "strike" in prev_df.columns:
                    prev_indexed = prev_df.set_index("strike")
                    chain_indexed = chain.set_index("strike")

                    if "ce_oi" in prev_indexed.columns:
                        prev_ce = prev_indexed["ce_oi"].reindex(chain_indexed.index).fillna(chain_indexed["ce_oi"])
                        chain_indexed["ce_oi_chg"] = chain_indexed["ce_oi"] - prev_ce

                    if "pe_oi" in prev_indexed.columns:
                        prev_pe = prev_indexed["pe_oi"].reindex(chain_indexed.index).fillna(chain_indexed["pe_oi"])
                        chain_indexed["pe_oi_chg"] = chain_indexed["pe_oi"] - prev_pe

                    chain = chain_indexed.reset_index()
            else:
                logger.info("Previous snapshot is from a different date (%s vs %s); resetting OI change to 0.", snap_date, today_str)
        except Exception as e:
            logger.warning("Could not compute OI change from previous snapshot: %s", e)

    # Persist current snapshot with today's date for next run
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "date": today_str,
            "data": json.loads(chain.to_json(orient="records")),
        }
        SNAP_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to save snapshot cache: %s", e)

    return chain


# ==============================================================================
# 5. Option Chain Analysis (Max Pain, Walls, Buildup, Bias)
# ==============================================================================

def max_pain(chain: pd.DataFrame) -> float:
    """Calculate the Max Pain strike where option writers have minimal loss."""
    if chain.empty:
        return 0.0

    strikes = chain["strike"].values
    pain = {}
    for k in strikes:
        ce_loss = (chain["ce_oi"] * (k - strikes).clip(min=0)).sum()
        pe_loss = (chain["pe_oi"] * (strikes - k).clip(min=0)).sum()
        pain[k] = ce_loss + pe_loss

    return float(min(pain, key=pain.get)) if pain else 0.0


def analyze(chain: pd.DataFrame, spot: float) -> Dict[str, Any]:
    """Comprehensive analytical calculation of PCR, Resistance, Support, and Confluence."""
    if chain.empty:
        return {"status": "EMPTY_CHAIN", "spot": spot}

    atm_idx = (chain["strike"] - spot).abs().argmin()
    atm = chain.iloc[atm_idx]
    atm_strike = float(atm["strike"])

    total_ce_oi = max(float(chain["ce_oi"].sum()), 1.0)
    total_pe_oi = float(chain["pe_oi"].sum())
    total_ce_vol = max(float(chain["ce_vol"].sum()), 1.0)
    total_pe_vol = float(chain["pe_vol"].sum())

    pcr_oi = total_pe_oi / total_ce_oi
    pcr_vol = total_pe_vol / total_ce_vol

    # Call Wall (Resistance) & Put Wall (Support)
    above = chain[chain["strike"] >= spot]
    below = chain[chain["strike"] <= spot]

    if not above.empty and above["ce_oi"].max() > 0:
        res_strike = float(above.loc[above["ce_oi"].idxmax(), "strike"])
    else:
        res_strike = float(chain.loc[chain["ce_oi"].idxmax(), "strike"])

    if not below.empty and below["pe_oi"].max() > 0:
        sup_strike = float(below.loc[below["pe_oi"].idxmax(), "strike"])
    else:
        sup_strike = float(chain.loc[chain["pe_oi"].idxmax(), "strike"])

    # Fresh Writing (Max OI addition this cycle; show 'n/a' when OI change is all zero or non-positive)
    if not chain.empty and "ce_oi_chg" in chain.columns and chain["ce_oi_chg"].max() > 0:
        ce_build: Any = float(chain.loc[chain["ce_oi_chg"].idxmax(), "strike"])
    else:
        ce_build = "n/a"

    if not chain.empty and "pe_oi_chg" in chain.columns and chain["pe_oi_chg"].max() > 0:
        pe_build: Any = float(chain.loc[chain["pe_oi_chg"].idxmax(), "strike"])
    else:
        pe_build = "n/a"

    # Directional Bias Evaluation
    tot_pe_oi_chg = chain["pe_oi_chg"].sum()
    tot_ce_oi_chg = chain["ce_oi_chg"].sum()

    if pcr_oi > 1.2 and tot_pe_oi_chg > tot_ce_oi_chg:
        bias = "BULLISH"
    elif pcr_oi < 0.8 and tot_ce_oi_chg > tot_pe_oi_chg:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    straddle_price = float(atm.get("ce_ltp", 0.0) + atm.get("pe_ltp", 0.0))
    pain_strike = max_pain(chain)

    return {
        "spot": round(spot, 2),
        "atm": atm_strike,
        "straddle": round(straddle_price, 2),
        "pcr_oi": round(pcr_oi, 2),
        "pcr_vol": round(pcr_vol, 2),
        "resistance": res_strike,
        "support": sup_strike,
        "max_pain": pain_strike,
        "fresh_call_writing": ce_build,
        "fresh_put_writing": pe_build,
        "bias": bias,
        "ce_oi_total": int(total_ce_oi),
        "pe_oi_total": int(total_pe_oi),
        "ce_oi_chg_total": int(tot_ce_oi_chg),
        "pe_oi_chg_total": int(tot_pe_oi_chg),
    }


def compute_angel_chain_score(summary: Dict[str, Any]) -> float:
    """Compute a directional score between -1.0 (bearish) and +1.0 (bullish).

    Factors:
      1. PCR (OI): Center around 1.0 (0.6 -> -1.0, 1.4 -> +1.0).
      2. OI change direction: PE writing (+) vs CE writing (-).
      3. S/R distance: Upside room to resistance (+) vs downside risk near resistance (-).
    """
    if not summary or summary.get("status") == "EMPTY_CHAIN":
        return 0.0

    # 1. PCR component (bounded [-1.0, +1.0])
    pcr = float(summary.get("pcr_oi", 1.0))
    pcr_score = max(-1.0, min(1.0, (pcr - 1.0) / 0.4))

    # 2. OI change direction component (bounded [-1.0, +1.0])
    pe_oi_chg = float(summary.get("pe_oi_chg_total", 0.0))
    ce_oi_chg = float(summary.get("ce_oi_chg_total", 0.0))
    total_chg = abs(pe_oi_chg) + abs(ce_oi_chg)
    if total_chg > 0:
        oi_dir_score = max(-1.0, min(1.0, (pe_oi_chg - ce_oi_chg) / total_chg))
    else:
        bias = summary.get("bias", "NEUTRAL")
        oi_dir_score = 1.0 if bias == "BULLISH" else (-1.0 if bias == "BEARISH" else 0.0)

    # 3. Distance to Support / Resistance component (bounded [-1.0, +1.0])
    spot = float(summary.get("spot", 0.0))
    support = float(summary.get("support", 0.0))
    resistance = float(summary.get("resistance", 0.0))
    if resistance > support and support > 0 and spot > 0:
        pos = (spot - support) / (resistance - support)
        sr_dist_score = max(-1.0, min(1.0, 1.0 - 2.0 * pos))
    else:
        sr_dist_score = 0.0

    score = (0.35 * pcr_score) + (0.40 * oi_dir_score) + (0.25 * sr_dist_score)
    return max(-1.0, min(1.0, round(score, 4)))


def confirm_signal(of_signal: str, s: Dict[str, Any]) -> str:
    """Merge Order Flow signals ('BUY', 'SELL', 'CALL_BUY', 'PUT_BUY') with Option Chain context."""
    signal = of_signal.upper()
    spot = s.get("spot", 0.0)
    res = s.get("resistance", spot + 100)
    sup = s.get("support", spot - 100)
    bias = s.get("bias", "NEUTRAL")

    if signal in ("BUY", "CALL_BUY"):
        if bias == "BEARISH":
            return f"CONFLICT - Order flow is BUY but Option Chain bias is BEARISH (Heavy CE writing at {res})"
        if spot >= res - 15:
            return f"CONFLICT - BUY rejected: Spot ({spot}) is trading directly at Call Wall / Resistance ({res})"
        return f"CONFIRMED BUY | Target: ~{res} | Stop-Loss: below {sup} | Option Bias: {bias}"

    if signal in ("SELL", "PUT_BUY"):
        if bias == "BULLISH":
            return f"CONFLICT - Order flow is SELL but Option Chain bias is BULLISH (Heavy PE writing at {sup})"
        if spot <= sup + 15:
            return f"CONFLICT - SELL rejected: Spot ({spot}) is trading directly at Put Wall / Support ({sup})"
        return f"CONFIRMED SELL | Target: ~{sup} | Stop-Loss: above {res} | Option Bias: {bias}"

    return f"NEUTRAL / WAIT | Option Bias: {bias} (PCR: {s.get('pcr_oi')}) | Range: [{sup} - {res}]"


# ==============================================================================
# 6. Adapter for Project Schemas (src.models.schemas.OptionChainSnapshot)
# ==============================================================================

def to_project_snapshot(
    chain: pd.DataFrame, spot: float, expiry_str: str, summary: Dict[str, Any]
) -> Any:
    """Convert Angel One option chain DataFrame to the project's Pydantic OptionChainSnapshot."""
    try:
        from src.models.schemas import BuildupType, OptionChainSnapshot, OptionData, StrikeRow

        strikes: List[StrikeRow] = []
        for _, row in chain.iterrows():
            k = float(row["strike"])
            ce_oi_chg = int(row.get("ce_oi_chg", 0))
            pe_oi_chg = int(row.get("pe_oi_chg", 0))

            ce_buildup = BuildupType.LONG_BUILDUP if ce_oi_chg > 0 else BuildupType.NEUTRAL
            pe_buildup = BuildupType.SHORT_BUILDUP if pe_oi_chg > 0 else BuildupType.NEUTRAL

            call_data = OptionData(
                ltp=float(row.get("ce_ltp", 0.0)),
                change=0.0,
                volume=int(row.get("ce_vol", 0)),
                oi=int(row.get("ce_oi", 0)),
                oi_change=ce_oi_chg,
                buildup=ce_buildup,
            )
            put_data = OptionData(
                ltp=float(row.get("pe_ltp", 0.0)),
                change=0.0,
                volume=int(row.get("pe_vol", 0)),
                oi=int(row.get("pe_oi", 0)),
                oi_change=pe_oi_chg,
                buildup=pe_buildup,
            )
            strikes.append(StrikeRow(strike=k, call=call_data, put=put_data))

        return OptionChainSnapshot(
            symbol="NIFTY",
            timestamp=datetime.now(timezone.utc).isoformat(),
            underlying_price=spot,
            expiry=expiry_str,
            pcr=summary.get("pcr_oi", 1.0),
            max_pain=summary.get("max_pain", spot),
            strikes=strikes,
            is_mock=False,
        )
    except Exception as e:
        logger.debug("Could not convert to OptionChainSnapshot schema: %s", e)
        return None


# ==============================================================================
# 7. Mock Synthetic Chain Generator (When Market Closed or No Credentials)
# ==============================================================================

def generate_mock_chain(spot: float = 24850.0, width: int = 10, step: int = 50) -> pd.DataFrame:
    """Generate realistic synthetic chain for off-market simulation and testing.
    Does NOT call add_oi_change or write chain_prev.json; OI changes are 0.0.
    """
    atm = round(spot / step) * step
    strikes = [atm + i * step for i in range(-width, width + 1)]
    records = []
    for k in strikes:
        dist = (k - spot)
        ce_ltp = max(5.0, round(max(0.0, -dist) + 120.0 - abs(dist) * 0.15, 2))
        pe_ltp = max(5.0, round(max(0.0, dist) + 120.0 - abs(dist) * 0.15, 2))
        ce_oi = int(max(10000, 150000 - abs(k - (atm + 100)) * 250))
        pe_oi = int(max(10000, 160000 - abs(k - (atm - 100)) * 250))
        records.append({
            "strike": float(k),
            "ce_ltp": ce_ltp,
            "ce_oi": ce_oi,
            "ce_vol": ce_oi // 3,
            "ce_oi_chg": 0.0,
            "pe_ltp": pe_ltp,
            "pe_oi": pe_oi,
            "pe_vol": pe_oi // 3,
            "pe_oi_chg": 0.0,
        })
    return pd.DataFrame(records)


# ==============================================================================
# 8. Command-Line Entrypoint
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Angel One SmartAPI Option Chain Fetcher & Analyzer")
    parser.add_argument("--expiry", type=str, default=None, help="Target expiry (e.g. 24OCT2024)")
    parser.add_argument("--width", type=int, default=12, help="Number of strikes above/below ATM (default: 12)")
    parser.add_argument("--step", type=int, default=50, help="Strike step size (default: 50)")
    parser.add_argument("--signal", type=str, default="BUY", help="Order flow test signal to confirm (BUY/SELL)")
    parser.add_argument("--json", action="store_true", help="Output analysis summary as JSON")
    parser.add_argument("--mock", action="store_true", help="Run with synthetic mock data (no API login required)")
    parser.add_argument("--refresh-master", action="store_true", help="Force refresh scrip master cache")
    args = parser.parse_args()

    if args.mock:
        logger.info("Running in MOCK mode (synthetic chain)")
        spot = 24850.0
        chain = generate_mock_chain(spot=spot, width=args.width, step=args.step)
        summary = analyze(chain, spot)
        conf = confirm_signal(args.signal, summary)
    else:
        try:
            api = login()
            master = load_master(force_refresh=args.refresh_master)
            contracts = option_contracts(master, name="NIFTY", expiry=args.expiry)
            spot = get_spot(api)
            chain = fetch_chain(api, contracts, spot, width=args.width, step=args.step)
            chain = add_oi_change(chain)
            summary = analyze(chain, spot)
            conf = confirm_signal(args.signal, summary)
        except Exception as e:
            logger.error("Live execution failed: %s", e)
            print(f"\n[ERROR] {e}", file=sys.stderr)
            print("\nTip: To test without Angel credentials, run with --mock flag:\n  python angel_chain.py --mock\n")
            sys.exit(1)

    if args.json:
        output = {
            "summary": summary,
            "signal_confirmation": conf,
            "chain_rows": len(chain),
        }
        print(json.dumps(output, indent=2))
    else:
        print("\n" + "=" * 80)
        print(" NIFTY OPTION CHAIN (Near ATM)")
        print("=" * 80)
        display_cols = ["strike", "ce_ltp", "ce_oi", "ce_oi_chg", "pe_ltp", "pe_oi", "pe_oi_chg"]
        avail_cols = [c for c in display_cols if c in chain.columns]
        print(chain[avail_cols].to_string(index=False))

        print("\n" + "=" * 80)
        print(" OPTION CHAIN CONFLUENCE ANALYSIS")
        print("=" * 80)
        print(json.dumps(summary, indent=2))

        print("\n" + "=" * 80)
        print(" SIGNAL CONFIRMATION")
        print("=" * 80)
        print(f"Order Flow Signal Input : {args.signal}")
        print(f"Confluence Verdict      : {conf}")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    main()

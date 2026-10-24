"""
Vision Provider Accuracy Comparison Tool
=========================================
Runs the same Order Flow + Option Chain screenshot pair through ALL
configured vision providers and prints a side-by-side comparison table.

Usage:
  # Auto-pick the most recent screenshot pair:
  python compare_providers.py

  # Specify screenshots explicitly:
  python compare_providers.py \\
      --order-flow  data/screenshots/20260917_112255_order_flow.png \\
      --option-chain data/screenshots/20260917_112255_option_chain_main.png

  # Test only specific providers:
  python compare_providers.py --providers anthropic nvidia

Environment variables required per provider:
  anthropic        -> ANTHROPIC_API_KEY
  gemini           -> GEMINI_API_KEY
  nvidia           -> NVIDIA_API_KEY   (model: meta/llama-3.2-11b-vision-instruct)
  paligemma_nvidia -> NVIDIA_API_KEY   (model: google/paligemma)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path
from typing import List, Optional

# Make src/ importable from project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import VisionConfig
from src.models.schemas import OrderFlowSnapshot, OptionChainSnapshot
from src.vision.extractor import (
    AnthropicVisionExtractor,
    GeminiVisionExtractor,
    MockVisionExtractor,
    NvidiaVisionExtractor,
)

# ─────────────────────────────────────────────────────────────────────────────
# Provider registry
# ─────────────────────────────────────────────────────────────────────────────

ALL_PROVIDERS = ["anthropic", "gemini", "nvidia", "paligemma_nvidia"]

PROVIDER_DISPLAY = {
    "anthropic":        "Anthropic Claude 3.5 Sonnet",
    "gemini":           "Google Gemini 1.5 Flash",
    "nvidia":           "NVIDIA NIM Llama-3.2-11B",
    "paligemma_nvidia": "NVIDIA NIM google/paligemma",
}

PROVIDER_ENV = {
    "anthropic":        "ANTHROPIC_API_KEY",
    "gemini":           "GEMINI_API_KEY",
    "nvidia":           "NVIDIA_API_KEY",
    "paligemma_nvidia": "NVIDIA_API_KEY",
}


def build_extractor(provider: str, config: VisionConfig):
    if provider == "anthropic":
        return AnthropicVisionExtractor(config)
    if provider == "gemini":
        return GeminiVisionExtractor(config)
    if provider == "nvidia":
        return NvidiaVisionExtractor(config, model="meta/llama-3.2-11b-vision-instruct")
    if provider == "paligemma_nvidia":
        return NvidiaVisionExtractor(config, model="google/paligemma")
    raise ValueError(f"Unknown provider: {provider!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Auto-discover most-recent real (non-mock) screenshot pair
# ─────────────────────────────────────────────────────────────────────────────

def find_latest_screenshots() -> tuple[Optional[str], Optional[str]]:
    screenshots_dir = Path("data/screenshots")
    if not screenshots_dir.exists():
        return None, None

    of_files = sorted(
        [f for f in screenshots_dir.glob("*_order_flow.png") if "mock" not in f.name],
        reverse=True,
    )
    oc_files = sorted(
        [f for f in screenshots_dir.glob("*_option_chain_main.png") if "mock" not in f.name],
        reverse=True,
    )
    return (str(of_files[0]) if of_files else None,
            str(oc_files[0]) if oc_files else None)


# ─────────────────────────────────────────────────────────────────────────────
# Result collection
# ─────────────────────────────────────────────────────────────────────────────

class ProviderResult:
    def __init__(self, provider: str, display_name: str):
        self.provider = provider
        self.display_name = display_name
        self.of_snapshot: Optional[OrderFlowSnapshot] = None
        self.oc_snapshot: Optional[OptionChainSnapshot] = None
        self.of_error: Optional[str] = None
        self.oc_error: Optional[str] = None
        self.of_latency_s: float = 0.0
        self.oc_latency_s: float = 0.0


def run_provider(
    provider: str,
    config: VisionConfig,
    of_path: str,
    oc_path: str,
    verbose: bool = False,
) -> ProviderResult:
    result = ProviderResult(provider=provider, display_name=PROVIDER_DISPLAY[provider])

    print(f"\n  [{provider}] Initialising extractor...")
    try:
        extractor = build_extractor(provider, config)
    except Exception as e:
        result.of_error = f"INIT FAILED: {e}"
        result.oc_error = f"INIT FAILED: {e}"
        print(f"  [{provider}] x Init error: {e}")
        return result

    # Order Flow
    print(f"  [{provider}] Extracting Order Flow...", end="", flush=True)
    t0 = time.perf_counter()
    try:
        result.of_snapshot = extractor.extract_order_flow(of_path)
        result.of_latency_s = time.perf_counter() - t0
        print(f" OK ({result.of_latency_s:.1f}s)")
    except Exception as e:
        result.of_latency_s = time.perf_counter() - t0
        result.of_error = str(e)
        if verbose:
            traceback.print_exc()
        print(f" ERROR: {e}")

    # Option Chain
    print(f"  [{provider}] Extracting Option Chain...", end="", flush=True)
    t0 = time.perf_counter()
    try:
        result.oc_snapshot = extractor.extract_option_chain([oc_path])
        result.oc_latency_s = time.perf_counter() - t0
        print(f" OK ({result.oc_latency_s:.1f}s)")
    except Exception as e:
        result.oc_latency_s = time.perf_counter() - t0
        result.oc_error = str(e)
        if verbose:
            traceback.print_exc()
        print(f" ERROR: {e}")

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Pretty comparison table
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(value, fmt_str=None, fallback="—"):
    if value is None:
        return fallback
    if fmt_str:
        return fmt_str.format(value)
    return str(value)


def print_comparison_table(
    results: List[ProviderResult], of_path: str, oc_path: str
) -> None:
    col_w = 34
    label_w = 26
    n = len(results)
    total_w = label_w + 4 + col_w * n

    divider   = "-" * total_w
    thick_div = "=" * total_w

    def hrow():
        return f"  {'METRIC':<{label_w}}  " + "".join(
            f"{r.display_name:<{col_w}}" for r in results
        )

    def drow(label: str, values: list) -> str:
        vals = "".join(f"{str(v):<{col_w}}" for v in values)
        return f"  {label:<{label_w}}  {vals}"

    def section(title: str) -> str:
        pad = max(0, total_w - len(title) - 6)
        return f"\n  -- {title} {'-' * pad}"

    print()
    print(thick_div)
    print("  VISION PROVIDER ACCURACY COMPARISON")
    print(f"  Order Flow  : {of_path}")
    print(f"  Option Chain: {oc_path}")
    print(thick_div)
    print(hrow())
    print(divider)

    # ORDER FLOW section
    print(section("ORDER FLOW"))
    print(drow("Status", [
        "OK" if r.of_snapshot else f"ERR: {(r.of_error or '')[:28]}"
        for r in results
    ]))
    print(drow("Symbol", [
        _fmt(r.of_snapshot.symbol if r.of_snapshot else None) for r in results
    ]))
    print(drow("Current Price", [
        _fmt(r.of_snapshot.current_price if r.of_snapshot else None, "{:.2f}")
        for r in results
    ]))
    print(drow("Candle Interval", [
        _fmt(r.of_snapshot.candle_interval if r.of_snapshot else None)
        for r in results
    ]))
    print(drow("# Price Levels", [
        _fmt(len(r.of_snapshot.price_levels) if r.of_snapshot else None)
        for r in results
    ]))
    print(drow("# Candle Deltas", [
        _fmt(len(r.of_snapshot.candle_deltas) if r.of_snapshot else None)
        for r in results
    ]))

    def last_candle(r: ProviderResult) -> str:
        if not r.of_snapshot or not r.of_snapshot.candle_deltas:
            return "—"
        cd = r.of_snapshot.candle_deltas[-1]
        return f"d={cd.delta:+d} vol={cd.total_volume}"

    print(drow("Last Candle (delta/vol)", [last_candle(r) for r in results]))
    print(drow("Latency", [f"{r.of_latency_s:.2f}s" for r in results]))

    # OPTION CHAIN section
    print(section("OPTION CHAIN"))
    print(drow("Status", [
        "OK" if r.oc_snapshot else f"ERR: {(r.oc_error or '')[:28]}"
        for r in results
    ]))
    print(drow("Symbol", [
        _fmt(r.oc_snapshot.symbol if r.oc_snapshot else None) for r in results
    ]))
    print(drow("Underlying Price", [
        _fmt(r.oc_snapshot.underlying_price if r.oc_snapshot else None, "{:.2f}")
        for r in results
    ]))
    print(drow("Expiry", [
        _fmt(r.oc_snapshot.expiry if r.oc_snapshot else None) for r in results
    ]))
    print(drow("PCR", [
        _fmt(r.oc_snapshot.pcr if r.oc_snapshot else None, "{:.3f}")
        for r in results
    ]))
    print(drow("ATM IV (%)", [
        _fmt(r.oc_snapshot.atm_iv if r.oc_snapshot else None, "{:.2f}")
        for r in results
    ]))
    print(drow("Max Pain", [
        _fmt(r.oc_snapshot.max_pain if r.oc_snapshot else None, "{:.0f}")
        for r in results
    ]))
    print(drow("Days to Expiry", [
        _fmt(r.oc_snapshot.days_to_expiry if r.oc_snapshot else None)
        for r in results
    ]))
    print(drow("# Strike Rows", [
        _fmt(len(r.oc_snapshot.strikes) if r.oc_snapshot else None) for r in results
    ]))

    def atm_summary(r: ProviderResult) -> str:
        if not r.oc_snapshot or not r.oc_snapshot.strikes:
            return "—"
        spot = r.oc_snapshot.underlying_price or 0
        atm = min(r.oc_snapshot.strikes, key=lambda s: abs(s.strike - spot))
        c = _fmt(atm.call.ltp if atm.call else None, "{:.1f}")
        p = _fmt(atm.put.ltp if atm.put else None, "{:.1f}")
        return f"K={atm.strike:.0f} CE={c} PE={p}"

    print(drow("ATM Strike (CE/PE LTP)", [atm_summary(r) for r in results]))
    print(drow("Latency", [f"{r.oc_latency_s:.2f}s" for r in results]))

    # TOTALS section
    print(section("TOTALS"))
    print(drow("Total Latency", [
        f"{r.of_latency_s + r.oc_latency_s:.2f}s" for r in results
    ]))
    print(drow("Extractions OK", [
        f"{sum([r.of_snapshot is not None, r.oc_snapshot is not None])}/2"
        for r in results
    ]))

    print()
    print(thick_div)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare all vision providers on the same screenshot pair."
    )
    parser.add_argument("--order-flow",   "-of", default=None,
                        help="Path to order flow screenshot. Auto-selected if omitted.")
    parser.add_argument("--option-chain", "-oc", default=None,
                        help="Path to option chain screenshot. Auto-selected if omitted.")
    parser.add_argument("--providers", "-p", nargs="+", choices=ALL_PROVIDERS, default=None,
                        help=f"Providers to test. Default: all with env keys set.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show full tracebacks on errors.")
    args = parser.parse_args()

    # Resolve screenshot paths
    of_path, oc_path = args.order_flow, args.option_chain
    if not of_path or not oc_path:
        auto_of, auto_oc = find_latest_screenshots()
        of_path = of_path or auto_of
        oc_path = oc_path or auto_oc

    for label, path in [("Order Flow", of_path), ("Option Chain", oc_path)]:
        if not path or not Path(path).exists():
            print(f"ERROR: {label} screenshot not found: {path!r}")
            print("       Run  python main.py --run-once  first, or pass explicit path.")
            sys.exit(1)

    print(f"\nOrder Flow   : {of_path}")
    print(f"Option Chain : {oc_path}")

    # Determine providers
    if args.providers:
        providers_to_run = args.providers
    else:
        providers_to_run = [p for p in ALL_PROVIDERS if os.getenv(PROVIDER_ENV[p])]

    if not providers_to_run:
        print("\nWARN: No API keys detected in environment.")
        print("      Running Mock provider as structural reference only.")
        print("      Set ANTHROPIC_API_KEY / GEMINI_API_KEY / NVIDIA_API_KEY to test real providers.\n")

    else:
        print(f"\nProviders : {', '.join(providers_to_run)}")
        print("(Keys required: ANTHROPIC_API_KEY / GEMINI_API_KEY / NVIDIA_API_KEY)\n")

    config = VisionConfig(max_tokens=2500, temperature=0.0, mock_mode=False)

    results: List[ProviderResult] = []
    for provider in providers_to_run:
        if not os.getenv(PROVIDER_ENV[provider]):
            print(f"  [{provider}] SKIP — {PROVIDER_ENV[provider]} not set.")
            continue
        results.append(run_provider(provider, config, of_path, oc_path, verbose=args.verbose))

    # Fall back to mock if nothing ran
    if not results:
        print("  [mock] Running Mock extractor as structural reference...")
        r = ProviderResult(provider="mock", display_name="Mock (no API key — structure only)")
        m = MockVisionExtractor()
        r.of_snapshot = m.extract_order_flow(of_path)
        r.oc_snapshot = m.extract_option_chain([oc_path])
        results.append(r)

    print_comparison_table(results, of_path, oc_path)

    # Save raw JSON outputs
    from datetime import datetime
    out_dir = Path("data/provider_comparison")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    for r in results:
        if r.of_snapshot:
            (out_dir / f"{ts}_{r.provider}_order_flow.json").write_text(
                r.of_snapshot.model_dump_json(indent=2), encoding="utf-8"
            )
        if r.oc_snapshot:
            (out_dir / f"{ts}_{r.provider}_option_chain.json").write_text(
                r.oc_snapshot.model_dump_json(indent=2), encoding="utf-8"
            )

    print(f"  Full JSON outputs saved to: {out_dir}/")
    print(f"  Pattern: {ts}_<provider>_<type>.json\n")


if __name__ == "__main__":
    main()

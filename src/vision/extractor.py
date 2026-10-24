"""Vision LLM extractors for Order Flow and Option Chain screenshots."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.config import VisionConfig
from src.models.schemas import (
    BuildupType,
    CandleDelta,
    OptionChainSnapshot,
    OptionData,
    OptionGreek,
    OrderFlowSnapshot,
    PriceLevel,
    StrikeRow,
)
from src.vision.prompts import (
    OPTION_CHAIN_SYSTEM_PROMPT,
    ORDER_FLOW_MULTI_TIMEFRAME_PROMPT,
    ORDER_FLOW_SYSTEM_PROMPT,
)

logger = logging.getLogger("vision_extractor")


def _clean_json_response(raw_text: str) -> str:
    """Robustly extract and clean JSON string from LLM responses."""
    text = (raw_text or "").strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1).strip()
    else:
        # Extract outermost { ... }
        brace_match = re.search(r"(\{[\s\S]*\})", text)
        if brace_match:
            text = brace_match.group(1).strip()

    # Strip single-line (//) and multi-line (/* */) comments
    text = re.sub(r"//.*?\n", "\n", text)
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)

    # Convert Python/JS non-JSON tokens to valid JSON
    text = re.sub(r"\bNone\b", "null", text)
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNaN\b", "null", text)
    text = re.sub(r"\bundefined\b", "null", text)

    text = re.sub(r"\b-?Infinity\b", "null", text)
    # Bare placeholders like N/A, -, -- , ? used as values -> null
    text = re.sub(r":\s*(?:N/A|NA|n/a|--?|\u2014|\?)\s*(?=[,}\]])", ": null", text)
    # Empty values  ->  "key": ,   or   "key": }
    text = re.sub(r":\s*(?=[,}\]])", ": null", text)

    # Strip trailing commas before } or ]
    text = re.sub(r",\s*(\}|\])", r"\1", text)
    return text


def safe_json_loads(raw_text: str) -> Dict[str, Any]:
    """Parse JSON with multi-layered fallback and repair for LLM responses."""
    cleaned = _clean_json_response(raw_text)
    try:
        return json.loads(cleaned)
    except Exception as primary_err:
        logger.warning("Primary json.loads failed (%s). Attempting AST/regex recovery.", primary_err)

        # 1. Fallback: try ast.literal_eval for python-formatted dicts
        import ast
        try:
            val = ast.literal_eval(cleaned)
            if isinstance(val, dict):
                return val
        except Exception:
            pass

        # 2. Fallback: find any balanced json-like block
        match = re.search(r"(\{[\s\S]*\})", cleaned)
        if match:
            candidate = match.group(1)
            candidate = re.sub(r",\s*(\}|\])", r"\1", candidate)
            try:
                return json.loads(candidate)
            except Exception:
                pass

        logger.error("Failed to parse LLM JSON payload:\n%s", raw_text)
        raise primary_err


def _encode_image_b64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


class MockVisionExtractor:
    """Deterministic mock extractor for offline testing, closed markets, and unit tests."""

    def __init__(self, config: Optional[VisionConfig] = None):
        self.config = config

    def extract_order_flow(self, image_path: Optional[str] = None) -> OrderFlowSnapshot:
        spot = 24850.0
        levels = [
            PriceLevel(price=24800.0, bid_volume=4500, ask_volume=2100, total_volume=6600, delta=2400, imbalance_buy=True),
            PriceLevel(price=24825.0, bid_volume=7200, ask_volume=4100, total_volume=11300, delta=3100, imbalance_buy=False),
            PriceLevel(price=24850.0, bid_volume=12500, ask_volume=8900, total_volume=21400, delta=3600, imbalance_buy=False),
            PriceLevel(price=24875.0, bid_volume=6800, ask_volume=5200, total_volume=12000, delta=1600, imbalance_buy=False),
            PriceLevel(price=24900.0, bid_volume=3100, ask_volume=4800, total_volume=7900, delta=-1700, imbalance_sell=False),
        ]
        candle_deltas = [
            CandleDelta(timestamp="11:05", open=24820.0, high=24840.0, low=24815.0, close=24835.0, delta=320, cumulative_delta=850, total_volume=35000),
            CandleDelta(timestamp="11:10", open=24835.0, high=24855.0, low=24830.0, close=24845.0, delta=480, cumulative_delta=1330, total_volume=42000),
            CandleDelta(timestamp="11:15", open=24845.0, high=24860.0, low=24840.0, close=24850.0, delta=610, cumulative_delta=1940, total_volume=48000),
        ]
        return OrderFlowSnapshot(
            symbol="NIFTY-FUT",
            current_price=spot,
            candle_interval="5m",
            cumulative_delta=1940,
            price_levels=levels,
            candle_deltas=candle_deltas,
            poc_price=24850.0,
            vah_price=24875.0,
            val_price=24825.0,
            is_mock=True,
        )

    def extract_option_chain(self, image_paths: Optional[Union[List[str], str]] = None) -> OptionChainSnapshot:
        spot = 24850.0
        strikes: List[StrikeRow] = []

        for strike in [24600.0, 24650.0, 24700.0, 24750.0, 24800.0, 24850.0, 24900.0, 24950.0, 25000.0, 25050.0, 25100.0]:
            dist = strike - spot
            call_ltp = max(5.0, round(max(0.0, -dist) + 120.0 - abs(dist) * 0.4, 1))
            put_ltp = max(5.0, round(max(0.0, dist) + 110.0 - abs(dist) * 0.4, 1))

            call_delta = max(0.05, min(0.95, round(0.5 - (dist / 600.0), 2)))
            put_delta = max(-0.95, min(-0.05, round(-0.5 - (dist / 600.0), 2)))

            # Near ATM bullish writing: Put additions > Call additions
            call_oi = int(120000 + abs(dist) * 200)
            put_oi = int(160000 + abs(dist) * 150)
            call_oi_chg = int(2500 - (dist * 10))
            put_oi_chg = int(18500 + (dist * 10))

            call_data = OptionData(
                ltp=call_ltp,
                change=2.5,
                volume=85000,
                oi=call_oi,
                oi_change=call_oi_chg,
                buildup=BuildupType.LONG_BUILDUP if call_oi_chg > 0 else BuildupType.SHORT_COVERING,
                greeks=OptionGreek(delta=call_delta, iv=13.5),
            )
            put_data = OptionData(
                ltp=put_ltp,
                change=-3.0,
                volume=95000,
                oi=put_oi,
                oi_change=put_oi_chg,
                buildup=BuildupType.SHORT_BUILDUP if put_oi_chg > 0 else BuildupType.LONG_UNWINDING,
                greeks=OptionGreek(delta=put_delta, iv=14.1),
            )
            strikes.append(StrikeRow(strike=strike, call=call_data, put=put_data))

        return OptionChainSnapshot(
            symbol="NIFTY",
            underlying_price=spot,
            expiry="CURRENT_WEEKLY",
            days_to_expiry=4,
            pcr=1.28,
            atm_iv=13.8,
            max_pain=24850.0,
            strikes=strikes,
            is_mock=True,
        )


class AnthropicVisionExtractor:
    def __init__(self, config: VisionConfig):
        self.config = config
        import anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
        self.client = anthropic.Anthropic(api_key=api_key)

    def extract_order_flow(self, image_path: Union[List[str], str]) -> OrderFlowSnapshot:
        paths = image_path if isinstance(image_path, list) else [image_path]
        content_items: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": "Extract all Order Flow and Footprint metrics from these chart images into JSON.",
            }
        ]
        for p in paths:
            b64 = _encode_image_b64(p)
            content_items.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            })
        sys_prompt = ORDER_FLOW_MULTI_TIMEFRAME_PROMPT if len(paths) > 1 else ORDER_FLOW_SYSTEM_PROMPT
        response = self.client.messages.create(
            model=self.config.model or "claude-3-5-sonnet-20241022",
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=sys_prompt,
            messages=[{"role": "user", "content": content_items}],
        )
        raw_text = response.content[0].text
        data = safe_json_loads(raw_text)
        return OrderFlowSnapshot(**data)

    def extract_option_chain(self, image_paths: Union[List[str], str]) -> OptionChainSnapshot:
        path = image_paths[0] if isinstance(image_paths, list) else image_paths
        b64 = _encode_image_b64(path)
        response = self.client.messages.create(
            model=self.config.model or "claude-3-5-sonnet-20241022",
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=OPTION_CHAIN_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extract all Option Chain table and Greeks rows into JSON.",
                        },
                    ],
                }
            ],
        )
        raw_text = response.content[0].text
        data = safe_json_loads(raw_text)
        return OptionChainSnapshot(**data)


class GeminiVisionExtractor:
    def __init__(self, config: VisionConfig):
        self.config = config
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        self.client = genai.Client(api_key=api_key)
        self.model_name = (
            self.config.model
            if self.config and self.config.model and "claude" not in self.config.model
            else "gemini-2.5-flash"
        )

    FALLBACK_MODELS = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]

    def _generate_json(self, prompt: str, img, model_cls, attempts: int = 3):
        """Call Gemini and parse into model_cls; automatically rotates fallback models on 429 / RESOURCE_EXHAUSTED."""
        from google.genai import types

        candidate_models = [self.model_name] + [m for m in self.FALLBACK_MODELS if m != self.model_name]
        last_err: Optional[Exception] = None

        for cur_model in candidate_models:
            for i in range(attempts):
                temp = self.config.temperature if i == 0 else 0.2 * i
                cfg = types.GenerateContentConfig(
                    temperature=temp,
                    max_output_tokens=max(self.config.max_tokens, 8192),
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                )
                try:
                    contents = [prompt] + (img if isinstance(img, list) else [img])
                    response = self.client.models.generate_content(
                        model=cur_model, contents=contents, config=cfg
                    )
                    data = safe_json_loads(response.text or "{}")
                    if cur_model != self.model_name:
                        logger.info("Switched active Gemini model from %s to working fallback %s", self.model_name, cur_model)
                        self.model_name = cur_model
                    return model_cls(**data)
                except Exception as e:
                    last_err = e
                    err_str = str(e)
                    is_quota = (
                        "429" in err_str
                        or "RESOURCE_EXHAUSTED" in err_str
                        or "quota" in err_str.lower()
                        or getattr(e, "code", None) == 429
                        or getattr(e, "status_code", None) == 429
                    )
                    if is_quota:
                        logger.warning(
                            "Gemini model '%s' hit 429 / RESOURCE_EXHAUSTED: %s. Rotating to next fallback model immediately.",
                            cur_model,
                            e,
                        )
                        break
                    logger.warning("Gemini extraction attempt %d/%d with model '%s' failed: %s", i + 1, attempts, cur_model, e)

        raise last_err  # type: ignore[misc]

    def extract_order_flow(self, image_path: Union[List[str], str]) -> OrderFlowSnapshot:
        from PIL import Image

        paths = image_path if isinstance(image_path, list) else [image_path]
        imgs = [Image.open(p) for p in paths]
        if len(paths) > 1:
            prompt = (
                f"{ORDER_FLOW_MULTI_TIMEFRAME_PROMPT}\n"
                "Extract all visible Order Flow / Footprint metrics into valid JSON. "
                "Synthesize the 15m macro institutional footprint context (POC, VAH/VAL value areas, absorption) "
                "with the 5m sniper execution footprint (candle delta flips, initiative buy/sell imbalances). "
                "Cross-check 15m institutional POC/VAH/VAL levels with 5m footprint breakout/absorption imbalances."
            )
        else:
            prompt = f"{ORDER_FLOW_SYSTEM_PROMPT}\nExtract all visible Order Flow / Footprint metrics into valid JSON."
        return self._generate_json(prompt, imgs, OrderFlowSnapshot)

    def extract_option_chain(self, image_paths: Union[List[str], str]) -> OptionChainSnapshot:
        from PIL import Image

        path = image_paths[0] if isinstance(image_paths, list) else image_paths
        img = Image.open(path)
        prompt = f"{OPTION_CHAIN_SYSTEM_PROMPT}\nExtract all visible Option Chain and Greeks metrics into valid JSON."
        return self._generate_json(prompt, img, OptionChainSnapshot)


class NvidiaVisionExtractor:
    def __init__(self, config: VisionConfig, model: str = "meta/llama-3.2-11b-vision-instruct"):
        self.config = config
        self.model_name = model
        from openai import OpenAI

        api_key = os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise ValueError("NVIDIA_API_KEY environment variable is not set")
        self.client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)

    def extract_order_flow(self, image_path: Union[List[str], str]) -> OrderFlowSnapshot:
        paths = image_path if isinstance(image_path, list) else [image_path]
        content_items: List[Dict[str, Any]] = [
            {"type": "text", "text": "Extract all Order Flow metrics into valid JSON."}
        ]
        for p in paths:
            b64 = _encode_image_b64(p)
            content_items.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        sys_prompt = ORDER_FLOW_MULTI_TIMEFRAME_PROMPT if len(paths) > 1 else ORDER_FLOW_SYSTEM_PROMPT
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": content_items},
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        raw_text = response.choices[0].message.content or "{}"
        data = safe_json_loads(raw_text)
        return OrderFlowSnapshot(**data)

    def extract_option_chain(self, image_paths: Union[List[str], str]) -> OptionChainSnapshot:
        path = image_paths[0] if isinstance(image_paths, list) else image_paths
        b64 = _encode_image_b64(path)
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": OPTION_CHAIN_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all Option Chain metrics into valid JSON."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                },
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        raw_text = response.choices[0].message.content or "{}"
        data = safe_json_loads(raw_text)
        return OptionChainSnapshot(**data)


class OpenAIVisionExtractor:
    def __init__(self, config: VisionConfig):
        self.config = config
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        self.client = OpenAI(api_key=api_key)

    def extract_order_flow(self, image_path: Union[List[str], str]) -> OrderFlowSnapshot:
        paths = image_path if isinstance(image_path, list) else [image_path]
        content_items: List[Dict[str, Any]] = [
            {"type": "text", "text": "Extract all Order Flow metrics into valid JSON."}
        ]
        for p in paths:
            b64 = _encode_image_b64(p)
            content_items.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        sys_prompt = ORDER_FLOW_MULTI_TIMEFRAME_PROMPT if len(paths) > 1 else ORDER_FLOW_SYSTEM_PROMPT
        response = self.client.chat.completions.create(
            model=self.config.model or "gpt-4o",
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": content_items},
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        raw_text = response.choices[0].message.content or "{}"
        data = safe_json_loads(raw_text)
        return OrderFlowSnapshot(**data)

    def extract_option_chain(self, image_paths: Union[List[str], str]) -> OptionChainSnapshot:
        path = image_paths[0] if isinstance(image_paths, list) else image_paths
        b64 = _encode_image_b64(path)
        response = self.client.chat.completions.create(
            model=self.config.model or "gpt-4o",
            messages=[
                {"role": "system", "content": OPTION_CHAIN_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all Option Chain metrics into valid JSON."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                },
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        raw_text = response.choices[0].message.content or "{}"
        data = safe_json_loads(raw_text)
        return OptionChainSnapshot(**data)


# Backward-compatible alias
ClaudeVisionExtractor = AnthropicVisionExtractor

